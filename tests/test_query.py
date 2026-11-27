from __future__ import annotations

import pytest

from nuboard.query import QueryError, parse

RUNS = [
    {
        "name": "a",
        "status": "finished",
        "tags": ["sweep"],
        "config": {"lr": 1e-3, "opt": {"wd": 0.1}},
        "summary": {"train/loss": {"last": 2.5, "min": 2.4}},
        "started": 3,
    },
    {
        "name": "b",
        "status": "crashed",
        "tags": [],
        "config": {"lr": 3e-4, "opt": {"wd": 0.0}},
        "summary": {"train/loss": {"last": "nan", "min": 2.9}},
        "started": 1,
    },
    {
        "name": "c",
        "status": "running",
        "tags": ["sweep", "seeds"],
        "config": {"lr": 1e-3},
        "summary": {},
        "started": 2,
    },
]


def names(q):
    return [r["name"] for r in parse(q).apply(RUNS)]


@pytest.mark.parametrize(
    "q,expected",
    [
        ("", ["a", "b", "c"]),
        ("where status != crashed", ["a", "c"]),
        ('tags has "sweep"', ["a", "c"]),
        ("config.lr = 1e-3 and not status = running", ["a"]),
        ("lr < 5e-4", ["b"]),
        ("config.opt.wd >= 0.1 or name = c", ["a", "c"]),
        ("train/loss.min < 2.5", ["a"]),
        ("train/loss exists", ["a", "b"]),
        ("status in (crashed, running)", ["b", "c"]),
        ("name ~ '^[ab]$'", ["a", "b"]),
        ("order by started desc", ["a", "c", "b"]),
        ("order by train/loss.min limit 1", ["a"]),
    ],
)
def test_queries(q, expected):
    assert names(q) == expected


def test_group_and_agg():
    q = parse('where tags has "sweep" group by config.lr agg min-max')
    assert q.group_by == "config.lr" and q.agg == "minmax"
    assert parse("group by lr agg mean±std").agg == "std"


@pytest.mark.parametrize("bad", ["where", "status !", "group lr", "agg nope", "where (a = 1"])
def test_errors(bad):
    with pytest.raises(QueryError):
        parse(bad)


def test_group_is_also_a_field():
    q = parse('where group = "fit/run1" group by group')
    assert q.where == ("cmp", "=", "group", "fit/run1")
    assert q.group_by == "group"


def test_vocabulary_lists_fields_with_their_common_values():
    from nuboard.query import vocabulary

    runs = [
        *RUNS,
        {"name": "d", "config": {"flag": True, "n": 1, "big": [1, 2]}, "fields": {"stage": "b"}},
    ]
    fields = {f["name"]: f for f in vocabulary(runs)}
    assert fields["status"]["kind"] == "run"
    assert set(fields["status"]["values"]) == {"finished", "crashed", "running"}
    assert fields["tags"]["values"][0] == "sweep"  # most common first
    assert fields["config.lr"]["values"] == [1e-3, 3e-4] and fields["config.lr"]["runs"] == 3
    assert fields["config.opt.wd"]["kind"] == "config"
    assert fields["config.flag"]["values"] == [True] and fields["config.n"]["values"] == [1]
    assert fields["config.big"]["values"] == []  # lists are not offered as values
    assert fields["fields.stage"] == {
        "name": "fields.stage",
        "kind": "field",
        "runs": 1,
        "values": ["b"],
    }
    assert fields["train/loss"]["kind"] == "metric" and fields["train/loss"]["runs"] == 2
    assert fields["starred"]["values"] == [False]
    kinds = [f["kind"] for f in vocabulary(runs)]
    assert kinds == sorted(kinds, key=["run", "config", "field", "metric"].index)


def test_vocabulary_caps_values_and_keys():
    from nuboard.query import vocabulary

    runs = [{"config": {f"k{i}": i, "s": "x" * 100}} for i in range(30)]
    fields = vocabulary(runs, max_values=5, max_keys=10)
    config = [f for f in fields if f["kind"] == "config"]
    assert len(config) == 10
    assert all(len(f["values"]) <= 5 for f in fields)
    assert not [f for f in config if f["name"] == "config.s" and f["values"]]
