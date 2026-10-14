"""The run query language used by the viewer's query bar and `Project.runs`.

A query is an optional filter expression followed by any of `group by`, `agg`,
`order by` and `limit` clauses. Example queries:

    where status != crashed order by started desc
    where tags has "sweep" and config.lr < 1e-3 group by config.lr agg mean±std
    train/loss.min < 2.5 order by train/loss.min limit 10

Fields: `name status project tags notes starred archived reviewed group host
commit created started ended duration id collections alerts`,
`config.<dotted.key>` (or a bare top-level config key such as `lr`),
`fields.<name>` for custom fields (or the bare name), and
`<metric>.<last|min|max|count|step>`. `alerts` is the number of health alerts.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

_TOKEN = re.compile(
    r"""\s*(?:
      (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
    | (?P<num>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?(?![\w/]))
    | (?P<op>==|!=|<=|>=|!~|=|<|>|~|\(|\)|,)
    | (?P<word>[A-Za-z_][\w./\-±+]*)
    )""",
    re.VERBOSE,
)
_KEYWORDS = {
    "where",
    "and",
    "or",
    "not",
    "group",
    "by",
    "agg",
    "order",
    "asc",
    "desc",
    "has",
    "in",
    "limit",
    "exists",
}
_TOP = {
    "name",
    "status",
    "project",
    "tags",
    "notes",
    "starred",
    "archived",
    "reviewed",
    "group",
    "host",
    "commit",
    "created",
    "started",
    "ended",
    "duration",
    "id",
    "path",
    "world_size",
    "collections",
    "fields",
}
_STATS = {"last", "min", "max", "count", "step", "nonfinite"}
AGGS = {
    "mean±std": "std",
    "mean+-std": "std",
    "std": "std",
    "mean": "none",
    "none": "none",
    "min-max": "minmax",
    "minmax": "minmax",
    "mean±sem": "sem",
    "sem": "sem",
    "median": "median",
}


class QueryError(ValueError):
    """Raised when a query string cannot be tokenized or parsed."""


@dataclass
class Query:
    """A parsed run query.

    Attributes:
        text: The original query text.
        where: The filter expression tree (nested tuples such as
            `("cmp", "<", "config.lr", 0.001)`), or None to match every run.
        group_by: Field to group runs by in the viewer, or None.
        agg: How grouped curves are aggregated: `"std"`, `"sem"`, `"minmax"`,
            `"median"` or `"none"` (see `AGGS` for the accepted spellings).
        order_by: Field to sort runs by, or None to keep the input order.
        descending: Whether `order_by` sorts in descending order.
        limit: Maximum number of runs to keep after sorting, or None.
        fields: Extra field names attached to the query (not set by the parser).
    """

    text: str = ""
    where: Any = None
    group_by: str | None = None
    agg: str = "std"
    order_by: str | None = None
    descending: bool = False
    limit: int | None = None
    fields: list[str] = field(default_factory=list)

    def matches(self, run: dict[str, Any]) -> bool:
        """Check whether a run satisfies the query's filter.

        Args:
            run: A catalog record for one run.

        Returns:
            True if the query has no filter or the filter evaluates truthy.
        """
        return self.where is None or bool(_eval(self.where, run))

    def apply(self, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter, sort and limit a list of runs.

        Runs whose `order_by` value is missing (None or NaN) are placed after
        the sorted runs, regardless of the sort direction.

        Args:
            runs: Catalog records to process.

        Returns:
            A new list holding the matching runs in query order, cut to `limit`.
        """
        out = [r for r in runs if self.matches(r)]

        if self.order_by:
            key = self.order_by
            present = [r for r in out if _is_set(resolve(r, key))]
            missing = [r for r in out if not _is_set(resolve(r, key))]
            present.sort(key=lambda r: _sort_key(resolve(r, key)), reverse=self.descending)
            out = present + missing

        if self.limit is not None:
            out = out[: self.limit]

        return out

    def to_json(self) -> dict[str, Any]:
        """Return the presentation options of the query as a JSON-ready dict.

        Returns:
            A dict with the `group_by`, `agg`, `order_by`, `descending` and
            `limit` values. The filter expression is not included.
        """
        return {
            "group_by": self.group_by,
            "agg": self.agg,
            "order_by": self.order_by,
            "descending": self.descending,
            "limit": self.limit,
        }


def _is_set(v: Any) -> bool:
    """Return whether `v` is a present value (neither None nor NaN)."""
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _sort_key(v: Any) -> tuple[int, Any]:
    """Return a sort key that orders numbers before case-insensitive strings."""

    if isinstance(v, bool):
        return (0, int(v))

    if isinstance(v, (int, float)):
        return (0, v)

    return (1, str(v).lower())


def resolve(run: dict[str, Any], name: str) -> Any:
    """Return the value of field `name` for a catalog record.

    Names are looked up in this order: `alerts` (the number of alerts), the
    top-level record fields, `fields.<name>`, `config.<dotted.key>`, metric
    summaries (`<metric>.<stat>` or a bare metric name, which gives its last
    value; an optional `summary.` prefix is ignored), a top-level or dotted
    config key, and finally a custom field with that name.

    Args:
        run: A catalog record for one run.
        name: The field name as written in a query.

    Returns:
        The field value, or None if the run does not have it. Summary values
        stored as the strings `"nan"`, `"inf"` or `"-inf"` are returned as floats.
    """

    if name == "alerts":
        return len(run.get("alerts") or [])

    if name in _TOP:
        return run.get(name)

    if name.startswith("fields."):
        return (run.get("fields") or {}).get(name[7:])

    if name.startswith("config."):
        return _dig(run.get("config") or {}, name[7:])

    if name.startswith("summary."):
        name = name[8:]

    summary = run.get("summary") or {}
    metric, _, stat = name.rpartition(".")

    if metric and stat in _STATS and metric in summary:
        value = summary[metric].get(stat)
        return _num(value)

    if name in summary:
        return _num(summary[name].get("last"))

    config = run.get("config") or {}

    if name in config:
        return config[name]

    found = _dig(config, name)

    if found is None:
        found = (run.get("fields") or {}).get(name)

    return found


def _dig(obj: Any, dotted: str) -> Any:
    """Follow a dotted key path through nested dicts, returning None if any part is missing."""

    for part in dotted.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None

    return obj


def _num(v: Any) -> Any:
    """Convert the strings `"nan"`, `"inf"` and `"-inf"` to floats; return other values as is."""

    if isinstance(v, str) and v in ("nan", "inf", "-inf"):
        return float(v)

    return v


def tokenize(text: str) -> list[tuple[str, Any]]:
    """Split a query string into tokens.

    Args:
        text: The query text.

    Returns:
        A list of `(kind, value)` pairs where kind is `"val"` (a quoted string
        or a number), `"op"` (an operator, parenthesis or comma), `"kw"` (a
        lowercased keyword) or `"word"` (a field name or bare value).

    Raises:
        QueryError: If the text contains a character that starts no token.
    """
    tokens: list[tuple[str, Any]] = []
    pos = 0
    text = text.strip()

    while pos < len(text):
        m = _TOKEN.match(text, pos)

        if not m or m.end() == pos:
            raise QueryError(f"unexpected character {text[pos]!r} at {pos}")

        pos = m.end()

        if m.group("str") is not None:
            raw = m.group("str")[1:-1]
            tokens.append(("val", re.sub(r"\\(.)", r"\1", raw)))
        elif m.group("num") is not None:
            num = m.group("num")
            tokens.append(("val", float(num) if any(c in num for c in ".eE") else int(num)))
        elif m.group("op") is not None:
            tokens.append(("op", m.group("op")))
        else:
            word = m.group("word")
            kw = word.lower()
            tokens.append(("kw", kw) if kw in _KEYWORDS else ("word", word))

    return tokens


class _Parser:
    """Recursive-descent parser that turns a token list into a `Query`."""

    def __init__(self, tokens: list[tuple[str, Any]]) -> None:
        self.t = tokens
        self.i = 0

    def peek(self, kind: str | None = None, value: Any = None) -> bool:
        """Return whether the next token matches `kind` and `value` (None matches anything)."""

        if self.i >= len(self.t):
            return False

        k, v = self.t[self.i]
        return (kind is None or k == kind) and (value is None or v == value)

    def take(self, kind: str | None = None, value: Any = None) -> Any:
        """Consume the next token and return its value; raise `QueryError` on a mismatch."""

        if not self.peek(kind, value):
            got = self.t[self.i][1] if self.i < len(self.t) else "end of query"
            raise QueryError(f"expected {value or kind}, got {got!r}")

        self.i += 1
        return self.t[self.i - 1][1]

    def field(self) -> str:
        """Consume and return a field name."""

        if self.peek("word"):
            return self.take()

        raise QueryError("expected a field name")

    def query(self, text: str) -> Query:
        """Parse a whole query: an optional filter followed by its clauses."""
        q = Query(text=text)

        if self.peek("kw", "where"):
            self.take()
            q.where = self.expr()
        elif self.i < len(self.t) and not self.peek("kw"):
            q.where = self.expr()

        while self.i < len(self.t):
            if self.peek("kw", "group"):
                self.take()
                self.take("kw", "by")
                q.group_by = self.field()
            elif self.peek("kw", "agg"):
                self.take()
                name = str(self.take()).lower()

                if name not in AGGS:
                    raise QueryError(f"unknown aggregation {name!r}; use mean±std, min-max, median")

                q.agg = AGGS[name]
            elif self.peek("kw", "order"):
                self.take()
                self.take("kw", "by")
                q.order_by = self.field()

                if self.peek("kw", "desc"):
                    self.take()
                    q.descending = True
                elif self.peek("kw", "asc"):
                    self.take()
            elif self.peek("kw", "limit"):
                self.take()
                q.limit = int(self.take("val"))
            else:
                raise QueryError(f"unexpected {self.t[self.i][1]!r}")

        return q

    def expr(self) -> Any:
        """Parse an `or` expression."""
        node = self.conj()

        while self.peek("kw", "or"):
            self.take()
            node = ("or", node, self.conj())

        return node

    def conj(self) -> Any:
        """Parse an `and` expression."""
        node = self.unary()

        while self.peek("kw", "and"):
            self.take()
            node = ("and", node, self.unary())

        return node

    def unary(self) -> Any:
        """Parse a `not` expression, a parenthesized expression or a condition."""

        if self.peek("kw", "not"):
            self.take()
            return ("not", self.unary())

        if self.peek("op", "("):
            self.take()
            node = self.expr()
            self.take("op", ")")
            return node

        return self.cond()

    def cond(self) -> Any:
        """Parse one condition such as `lr < 1e-3`, `tags has x` or `status in (a, b)`."""
        name = self.field()

        if self.peek("kw", "has"):
            self.take()
            return ("has", name, self.value())

        if self.peek("kw", "exists"):
            self.take()
            return ("exists", name)

        if self.peek("kw", "in"):
            self.take()
            self.take("op", "(")
            values = [self.value()]

            while self.peek("op", ","):
                self.take()
                values.append(self.value())

            self.take("op", ")")
            return ("in", name, values)

        if self.peek("kw", "not"):
            self.take()
            self.take("kw", "in")
            return ("not", self.cond_in(name))

        op = self.take("op")

        if op in ("(", ")", ","):
            raise QueryError(f"expected a comparison after {name!r}")

        return ("cmp", op, name, self.value())

    def cond_in(self, name: str) -> Any:
        """Parse the parenthesized value list of an `in` condition on `name`."""
        self.take("op", "(")
        values = [self.value()]

        while self.peek("op", ","):
            self.take()
            values.append(self.value())

        self.take("op", ")")
        return ("in", name, values)

    def value(self) -> Any:
        """Parse a value; the bare words true, false, null and none become Python constants."""

        if self.peek("val"):
            return self.take()

        if self.peek("word"):
            word = self.take()
            return {"true": True, "false": False, "null": None, "none": None}.get(
                word.lower(), word
            )

        raise QueryError("expected a value")


def parse(text: str | None) -> Query:
    """Parse a query string into a `Query`.

    Args:
        text: The query text. None or an empty string gives a query that
            matches every run.

    Returns:
        The parsed query.

    Raises:
        QueryError: If the text is not a valid query.
    """
    text = (text or "").strip()

    if not text:
        return Query()

    p = _Parser(tokenize(text))
    q = p.query(text)
    return q


def _eq(a: Any, b: Any) -> bool:
    """Compare a run value with a query value loosely (case-insensitive, numbers vs strings)."""

    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b) if isinstance(b, bool) else str(a).lower() == str(b).lower()

    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b or (math.isnan(a) and isinstance(b, float) and math.isnan(b))

    if isinstance(a, (int, float)) and isinstance(b, str):
        try:
            return a == float(b)
        except ValueError:
            return False

    if a is None or b is None:
        return a is None and b is None

    return str(a).lower() == str(b).lower()


def _eval(node: Any, run: dict[str, Any]) -> bool:
    """Evaluate a filter expression tree against a run."""
    kind = node[0]

    if kind == "and":
        return _eval(node[1], run) and _eval(node[2], run)

    if kind == "or":
        return _eval(node[1], run) or _eval(node[2], run)

    if kind == "not":
        return not _eval(node[1], run)

    if kind == "exists":
        return resolve(run, node[1]) is not None

    if kind == "has":
        v = resolve(run, node[1])

        if isinstance(v, (list, tuple, set)):
            return any(_eq(x, node[2]) for x in v)

        return v is not None and str(node[2]).lower() in str(v).lower()

    if kind == "in":
        v = resolve(run, node[1])
        return any(_eq(v, x) for x in node[2])

    _, op, name, value = node
    v = resolve(run, name)

    if op in ("=", "=="):
        return _eq(v, value)

    if op == "!=":
        return not _eq(v, value)

    if op in ("~", "!~"):
        try:
            hit = v is not None and re.search(str(value), str(v), re.IGNORECASE) is not None
        except re.error:
            hit = v is not None and str(value).lower() in str(v).lower()

        return hit if op == "~" else not hit

    if v is None:
        return False

    try:
        if isinstance(value, str) or isinstance(v, str):
            return _order(op, str(v).lower(), str(value).lower())

        return _order(op, float(v), float(value))
    except (TypeError, ValueError):
        return False


def _order(op: str, a: Any, b: Any) -> bool:
    """Apply the ordering comparison `op` (`<`, `<=`, `>` or `>=`) to `a` and `b`."""

    if op == "<":
        return a < b

    if op == "<=":
        return a <= b

    if op == ">":
        return a > b

    return a >= b
