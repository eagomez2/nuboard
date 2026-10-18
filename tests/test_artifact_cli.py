from __future__ import annotations

import argparse
import json

import pytest

import nuboard as nb
from nuboard import _artifact_cli as cli


def _args(*argv):
    parser = argparse.ArgumentParser()
    cli.add_parser(parser.add_subparsers(dest="cmd"), "NUBOARD", "experiments")
    return parser.parse_args(["artifact", *argv])


def _run(argv, answers=(), interactive=True):
    """Run a command with scripted answers; return (exit code, printed lines, prompts)."""
    said, asked, left = [], [], list(answers)

    def ask(prompt):
        asked.append(prompt)

        if not left:
            raise EOFError

        return left.pop(0)

    code = cli.main(_args(*argv), ask=ask, say=said.append, interactive=interactive)
    return code, said, asked


@pytest.fixture
def data(tmp_path):
    folder = tmp_path / "data" / "fw"
    folder.mkdir(parents=True)
    (folder / "a.txt").write_text("hello")
    (folder / "b.txt").write_text("bye")
    return folder


def test_checks_reject_bad_values_with_a_reason(data):
    with pytest.raises(cli.Invalid, match="give the project"):
        cli.check_name("fineweb")

    with pytest.raises(cli.Invalid, match="letters, digits"):
        cli.check_name("datasets/fine web")

    assert cli.check_name(" /datasets/fineweb-edu/ ") == "datasets/fineweb-edu"

    with pytest.raises(cli.Invalid, match="does not exist"):
        cli.check_path(str(data / "nope"))

    (data.parent / "empty").mkdir()

    with pytest.raises(cli.Invalid, match="has no files"):
        cli.check_path(str(data.parent / "empty"))

    assert cli.check_store("r") == "reference" and cli.check_type("ch") == "checkpoint"

    with pytest.raises(cli.Invalid):
        cli.check_type("data set")

    with pytest.raises(cli.Invalid):
        cli.check_description("   ")


def test_metadata_values_get_their_type():
    assert cli.parse_meta("rows=1200000") == ("rows", 1200000)
    assert cli.parse_meta("lr=3e-4") == ("lr", 3e-4)
    assert cli.parse_meta("dedup=true") == ("dedup", True)
    assert cli.parse_meta("tokens=12B") == ("tokens", "12B")
    assert cli.parse_meta("split:str=0001") == ("split", "0001")
    assert cli.parse_meta('langs:json=["en", "es"]') == ("langs", ["en", "es"])

    for bad in ("rows", "bad key=1", "n:int=1.5", "x:date=1"):
        with pytest.raises(cli.Invalid):
            cli.parse_meta(bad)


def test_flags_add_a_version_without_asking(data):
    code, said, asked = _run(
        [
            "add",
            "datasets/fw",
            str(data),
            "--ref",
            "-t",
            "dataset",
            "-d",
            "two files",
            "-m",
            "rows=2",
            "-m",
            "src:str=01",
        ],
        interactive=False,
    )
    assert code == 0 and asked == []
    assert said[0].startswith("Added datasets/fw:v1 (reference, 2 files")
    art = nb.get_artifact("datasets/fw")
    assert art.manifest["description"] == "two files"
    assert art.manifest["metadata"] == {"rows": 2, "src": "01"}
    assert art.manifest["created_by"]["host"]


def test_every_flag_error_is_reported_and_nothing_is_written(data):
    code, said, _ = _run(
        ["add", "fw", str(data / "nope"), "--copy", "--checksum", "-t", "x", "-m", "bad"],
        interactive=False,
    )
    assert code == 2 and len(said) == 5  # name, path, type, checksum, meta
    code, said, _ = _run(["add", "datasets/fw", str(data)], interactive=False)
    assert code == 2 and said == ["✗ missing: --ref or --copy, --type, --description"]
    assert not list(data.parent.parent.rglob("manifest.json"))


def test_prompts_check_each_answer_go_back_and_edit_metadata(data):
    answers = [
        "fw",  # no project: asked again
        "datasets/fw",
        str(data / "nope"),  # asked again
        str(data),
        "copy",
        "<",  # back to store
        "reference",
        "dataset",
        "",  # empty description: asked again
        "two files",
        "",  # checksum: keep n
        "rows=2",
        "tokens=12B",
        "1 rows=3",  # edit line 1
        "-2",  # delete line 2
        "9 x=1",  # no line 9
        "",  # done with metadata
        "5",  # change the description from the review
        "two small files",
        "y",
    ]
    code, said, asked = _run(["add"], answers)
    assert code == 0
    assert sum("✗" in s for s in said) == 4
    assert sum(a.startswith("Store") for a in asked) == 2  # asked again after going back
    art = nb.get_artifact("datasets/fw")
    assert art.reference is not None
    assert art.manifest["description"] == "two small files"
    assert art.manifest["metadata"] == {"rows": 3}


def test_flags_fill_the_prompts_and_quitting_writes_nothing(data):
    answers = ["model", "the weights", "", "q"]  # type, description, no metadata, quit
    code, said, asked = _run(["add", "datasets/fw", str(data), "--copy"], answers)
    assert asked[0].startswith("Type") and code == 1 and said[-1] == "Nothing written."
    assert not (data.parent.parent / "exp" / "datasets").exists()
    code, said, _ = _run(["add", "datasets/fw"], [])  # Ctrl-D at the first prompt
    assert code == 1 and said[-1] == "Nothing written."


def test_ls_and_show(data, capsys):
    _run(["add", "datasets/fw", str(data), "--ref", "-t", "dataset", "-d", "two files"])
    code, said, _ = _run(["ls"])
    assert code == 0 and said[0].startswith("datasets/fw:v1") and "two files" in said[0]
    code, said, _ = _run(["show", "datasets/fw"])
    assert code == 0 and said[-1] == "  ✓ files match the manifest"
    (data / "a.txt").unlink()
    code, said, _ = _run(["show", "datasets/fw:v1"])
    assert code == 1 and "  ✗ missing: a.txt" in said
    assert _run(["show", "datasets/nope"])[0] == 1
    json.dumps(said)  # plain strings
