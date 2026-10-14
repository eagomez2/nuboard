"""Put a blank line between a block statement and its neighbouring statements.

A block statement is `if`, `for`, `while`, `with`, `try`, `match` (and their
`async` forms). Within any statement list, a blank line separates a block from
the statement before it and the statement after it, so each block stands on its
own. Comments directly above a statement stay attached to it.

Usage:
    python scripts/blank_lines.py [--check] PATH...

With `--check`, files are not changed and the exit code is 1 when one would be.
"""

from __future__ import annotations

import ast
import itertools
import sys
from pathlib import Path

BLOCKS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.Match)

if sys.version_info >= (3, 11):
    BLOCKS = (*BLOCKS, ast.TryStar)


def _bodies(node: ast.AST) -> list[list[ast.stmt]]:
    """Return every statement list held directly by `node`."""
    out = []

    for field in ("body", "orelse", "finalbody"):
        value = getattr(node, field, None)

        if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
            out.append(value)

    for handler in getattr(node, "handlers", []):
        out.append(handler.body)

    for case in getattr(node, "cases", []):
        out.append(case.body)

    return out


def _start(stmt: ast.stmt) -> int:
    """Return the first line of `stmt`, decorators included (1-based)."""
    decorators = getattr(stmt, "decorator_list", [])
    return min([stmt.lineno, *(d.lineno for d in decorators)])


def missing_blank_lines(source: str) -> list[int]:
    """Return the 0-based line indices that need a blank line inserted above them.

    Args:
        source: Python source code.

    Returns:
        Sorted line indices, each the first line (or first attached comment) of a
        statement that should be preceded by a blank line.
    """
    lines = source.splitlines()
    tree = ast.parse(source)
    found: set[int] = set()

    for node in ast.walk(tree):
        for body in _bodies(node):
            for prev, stmt in itertools.pairwise(body):
                if not (isinstance(prev, BLOCKS) or isinstance(stmt, BLOCKS)):
                    continue

                top = _start(stmt) - 1  # 0-based

                while top - 1 > (prev.end_lineno or 0) - 1 and lines[top - 1].lstrip().startswith(
                    "#"
                ):
                    top -= 1

                if top > 0 and lines[top - 1].strip():
                    found.add(top)

    return sorted(found)


def fix(source: str) -> str:
    """Return `source` with the missing blank lines inserted."""
    lines = source.splitlines(keepends=True)

    for index in reversed(missing_blank_lines(source)):
        lines.insert(index, "\n")

    return "".join(lines)


def main(argv: list[str]) -> int:
    """Fix or check the given files and folders; return the exit code."""
    check = "--check" in argv
    paths = [Path(a) for a in argv if a != "--check"]
    files = [f for p in paths for f in (sorted(p.rglob("*.py")) if p.is_dir() else [p])]
    changed = []

    for path in files:
        source = path.read_text(encoding="utf-8")
        fixed = fix(source)

        if fixed != source:
            changed.append(path)

            if not check:
                path.write_text(fixed, encoding="utf-8")

    for path in changed:
        print(f"{'would fix' if check else 'fixed'} {path}")

    return 1 if check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
