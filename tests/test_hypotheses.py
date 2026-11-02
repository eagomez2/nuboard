from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

import nuboard as nb
from nuboard.hypotheses import (
    DEFAULT_OUTCOMES,
    DEFAULT_VERDICTS,
    MAX_CATEGORIES,
    HypothesisError,
    clean_board,
    delete_board,
    delete_hypothesis,
    list_boards,
    load_board,
    save_board,
    save_hypothesis,
)
from nuboard.server import create_app


def test_empty_project_has_default_board(tmp_path):
    data = load_board(tmp_path)
    assert data["hypotheses"] == []
    assert data["board"]["verdicts"] == DEFAULT_VERDICTS
    assert data["board"]["outcomes"] == DEFAULT_OUTCOMES
    assert data["board"]["card"] is None and data["board"]["title"] == ""


def test_save_load_and_delete(tmp_path):
    h = save_hypothesis(tmp_path, {"title": "Is it the lr?", "runs": ["a", {"id": "b", "star": 1}]})
    assert h["id"].startswith("h-")
    assert (tmp_path / "hypotheses" / "main" / f"{h['id']}.json").exists()
    assert [r["id"] for r in h["runs"]] == ["a", "b"]
    assert h["runs"][0]["outcome"] == "open" and h["runs"][1]["star"] is True
    assert h["verdict"] == "open" and h["show_reason"] is True

    again = save_hypothesis(tmp_path, {**h, "verdict": "supported"})
    assert again["created"] == h["created"] and again["verdict"] == "supported"
    assert [x["id"] for x in load_board(tmp_path)["hypotheses"]] == [h["id"]]

    assert delete_hypothesis(tmp_path, h["id"]) is True
    assert delete_hypothesis(tmp_path, h["id"]) is False
    assert load_board(tmp_path)["hypotheses"] == []


def test_a_run_belongs_to_one_hypothesis(tmp_path):
    first = save_hypothesis(tmp_path, {"id": "first", "runs": ["a", "b"]})
    save_hypothesis(tmp_path, {"id": "second", "runs": ["b"], "parent_run": "a"})
    by_id = {h["id"]: h for h in load_board(tmp_path)["hypotheses"]}
    assert [r["id"] for r in by_id["first"]["runs"]] == ["a"]
    assert [r["id"] for r in by_id["second"]["runs"]] == ["b"]
    assert first["id"] == "first"


def test_loops_are_refused(tmp_path):
    save_hypothesis(tmp_path, {"id": "root", "runs": ["a"]})
    save_hypothesis(tmp_path, {"id": "child", "runs": ["b"], "parent_run": "a"})
    save_hypothesis(tmp_path, {"id": "grandchild", "runs": ["c"], "parent_run": "b"})

    with pytest.raises(HypothesisError, match="loop"):
        save_hypothesis(tmp_path, {"id": "root", "runs": ["a"], "parent_run": "c"})

    with pytest.raises(HypothesisError, match="loop"):
        save_hypothesis(tmp_path, {"id": "solo", "runs": ["x"], "parent_run": "x"})

    # a parent that no hypothesis lists (a deleted run, say) is fine
    assert save_hypothesis(tmp_path, {"id": "root", "runs": ["a"], "parent_run": "gone"})


def test_several_boards_per_project(tmp_path):
    save_hypothesis(tmp_path, {"id": "a", "runs": ["r1"]})
    save_board(tmp_path, {"title": "Data study"}, board="data")
    save_hypothesis(tmp_path, {"id": "b", "runs": ["r1"]}, board="data")

    # the same run can be on two boards; each board keeps its own
    assert [h["id"] for h in load_board(tmp_path)["hypotheses"]] == ["a"]
    assert [r["id"] for r in load_board(tmp_path)["hypotheses"][0]["runs"]] == ["r1"]
    assert [h["id"] for h in load_board(tmp_path, "data")["hypotheses"]] == ["b"]
    assert list_boards(tmp_path) == [
        {"name": "data", "title": "Data study", "count": 1},
        {"name": "main", "title": "", "count": 1},
    ]

    assert delete_board(tmp_path, "data") is True
    assert delete_board(tmp_path, "data") is False
    assert [b["name"] for b in list_boards(tmp_path)] == ["main"]

    with pytest.raises(HypothesisError, match="board"):
        load_board(tmp_path, "../up")


def test_bad_ids_are_refused(tmp_path):
    for bad in ("../x", "a b", "x" * 65):
        with pytest.raises(HypothesisError):
            save_hypothesis(tmp_path, {"id": bad})

    with pytest.raises(HypothesisError):
        delete_hypothesis(tmp_path, "../board")


def test_corrupt_and_hand_edited_files_never_break_reading(tmp_path):
    folder = tmp_path / "hypotheses" / "main"
    folder.mkdir(parents=True)
    (folder / "broken.json").write_text("{not json", "utf-8")
    (folder / "list.json").write_text("[1, 2]", "utf-8")
    (folder / "bad name!.json").write_text("{}", "utf-8")
    (folder / "board.json").write_text(json.dumps({"verdicts": "nope", "card": 3}), "utf-8")
    (folder / "odd.json").write_text(
        json.dumps(
            {
                "id": "other",  # the file name wins
                "title": 5,
                "runs": ["a", "a", 7, {"id": ""}, {"id": "b", "outcome": None}],
                "also": [{"run": "a"}, "x", {"reason": "no run"}],
                "position": {"dx": "nan", "dy": float("inf")},
                "reports": ["r", 3, ""],
                "folded": "yes",
                "created": "soon",
            }
        ),
        "utf-8",
    )
    data = load_board(tmp_path)
    assert data["board"]["verdicts"] == DEFAULT_VERDICTS and data["board"]["card"] is None
    [h] = data["hypotheses"]
    assert h["id"] == "odd" and h["title"] == "Untitled hypothesis"
    assert [(r["id"], r["outcome"]) for r in h["runs"]] == [("a", "open"), ("b", "open")]
    assert h["also"] == [{"run": "a", "reason": ""}]
    assert h["position"] == {"dx": 0.0, "dy": 0.0} and h["folded"] is None
    assert h["reports"] == ["r"] and h["created"] > 0


def test_board_categories_are_cleaned_and_capped(tmp_path):
    many = [{"label": f"C{i}", "color": "s1", "icon": "star"} for i in range(MAX_CATEGORIES + 3)]
    board = save_board(
        tmp_path,
        {
            "title": " My board ",
            "verdicts": many,
            "outcomes": [
                {"id": "x", "label": "Kept", "color": "nope"},
                {"id": "x", "label": "Kept", "dead_end": 1},
            ],
            "card": {"metric": "val/loss", "stat": "weird", "higher": 0},
            "unknown": "ignored",
        },
    )
    assert board["title"] == "My board" and "unknown" not in board
    assert len(board["verdicts"]) == MAX_CATEGORIES
    assert board["verdicts"][0] == {"id": "c0", "label": "C0", "color": "s1", "icon": "star"}
    ids = [o["id"] for o in board["outcomes"]]
    assert ids[0] == "x" and len(set(ids)) == 2 and board["outcomes"][1]["dead_end"] is True
    assert board["outcomes"][0]["color"] in ("s4", "s5", "s1", "s2", "s3", "s6", "s7", "gray")
    assert board["card"] == {"metric": "val/loss", "stat": "best", "higher": False}

    # a partial update keeps the rest; an empty list falls back to the defaults
    board = save_board(tmp_path, {"description": "why", "verdicts": []})
    assert board["title"] == "My board" and board["description"] == "why"
    assert board["verdicts"] == DEFAULT_VERDICTS
    assert clean_board(None)["outcomes"] == DEFAULT_OUTCOMES


@pytest.fixture
def client(tmp_path):
    for name in ("base", "warmup"):
        with nb.init("proj", run_name=name, capture_env=False) as run:
            for s in range(5):
                run.add_scalar({"loss": 1 / (s + 1)}, step=s)

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache")

    with TestClient(app) as c:
        yield c


def test_api_board_with_missing_runs_and_reports(client):
    runs = {r["name"]: r for r in client.get("/api/runs").json()["runs"]}
    base, warmup = runs["base"]["id"], runs["warmup"]["id"]
    res = client.post(
        "/api/hypotheses",
        json={
            "project": "proj",
            "hypothesis": {
                "title": "Does warmup help?",
                "runs": [warmup, "20200101-0000_deleted_abc123"],
                "parent_run": base,
                "also": [{"run": "gone-too", "reason": "x"}],
                "reports": ["no-such-report"],
            },
        },
    ).json()
    hid = res["hypothesis"]["id"]
    client.post("/api/hypotheses", json={"project": "proj", "settings": {"title": "LR study"}})

    data = client.get("/api/hypotheses", params={"project": "proj"}).json()
    assert data["board"]["title"] == "LR study" and data["name"] == "main"
    assert data["boards"] == [{"name": "main", "title": "LR study", "count": 1}]
    assert [h["id"] for h in data["hypotheses"]] == [hid]
    assert set(data["runs"]) == {base, warmup}  # missing ids are left out, not an error
    assert data["runs"][warmup]["key"] == runs["warmup"]["key"]
    assert "loss" in data["runs"][warmup]["summary"]
    assert data["reports"] == [] and data["read_only"] is False

    assert client.post("/api/hypotheses", json={"project": "proj", "delete": hid}).json()["existed"]
    assert client.get("/api/hypotheses", params={"project": "proj"}).json()["hypotheses"] == []

    # a second board is picked by name; deleting it leaves the first
    client.post("/api/hypotheses", json={"project": "proj", "board": "b2", "settings": {}})
    two = client.get("/api/hypotheses", params={"project": "proj", "board": "b2"}).json()
    assert two["name"] == "b2" and [b["name"] for b in two["boards"]] == ["b2", "main"]
    gone = {"project": "proj", "board": "b2", "delete_board": True}
    assert client.post("/api/hypotheses", json=gone).json()["existed"] is True


def test_api_errors(client):
    assert client.get("/api/hypotheses", params={"project": "nope"}).status_code == 404
    assert client.get("/api/hypotheses").status_code == 404
    post = client.post
    assert post("/api/hypotheses", json={"project": "nope", "settings": {}}).status_code == 404
    assert post("/api/hypotheses", json={"project": "proj"}).status_code == 400
    assert post("/api/hypotheses", json=[1]).status_code == 400
    bad = post("/api/hypotheses", json={"project": "proj", "hypothesis": {"id": "../x"}})
    assert bad.status_code == 400 and "id" in bad.json()["error"]
    loop = post(
        "/api/hypotheses",
        json={"project": "proj", "hypothesis": {"id": "a", "runs": ["r"], "parent_run": "r"}},
    )
    assert loop.status_code == 400 and "loop" in loop.json()["error"]
    assert (
        client.get("/api/hypotheses", params={"project": "proj", "board": "../x"}).status_code
        == 400
    )
    bad_board = post("/api/hypotheses", json={"project": "proj", "board": "a/b", "settings": {}})
    assert bad_board.status_code == 400


def test_api_read_only(tmp_path):
    with nb.init("proj", run_name="x", capture_env=False):
        pass

    app = create_app(tmp_path / "exp", cache_dir=tmp_path / "cache", read_only_reports=True)

    with TestClient(app) as c:
        res = c.post("/api/hypotheses", json={"project": "proj", "settings": {"title": "t"}})
        assert res.status_code == 403
        assert c.get("/api/hypotheses", params={"project": "proj"}).json()["read_only"] is True
