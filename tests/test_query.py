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
