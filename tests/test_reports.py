from __future__ import annotations

import io
import zipfile

import pytest

from nuboard.reports import (
    MediaRef,
    check_field,
    clean_fields,
    parse_ref,
    read_fields,
    report_names,
    save_fields,
    save_report,
)
from nuboard.reports import export_report as export


def test_parse_ref():
    assert parse_ref("20261016T0815-f01a036a/samples/recon@1200") == MediaRef(
        "20261016T0815-f01a036a", "samples/recon", 1200
    )

    for bad in ("run-only", "run/key", "run/key@x", "/key@1"):
        with pytest.raises(ValueError):
            parse_ref(bad)


def test_save_and_list_reports(tmp_path):
    save_report(tmp_path, "My findings!", "# Findings\n\ntext\n")
    [info] = report_names(tmp_path)
    assert info["title"] == "Findings"
    assert (tmp_path / "reports" / f"{info['name']}.md").read_text("utf-8").startswith("# Find")


def test_export_report_bundles_items():
    text = (
        "# R\n\n![a sample](media:r1/img@3)\n\n![log](media:r1/log@0)\n\n"
        "![fig](media:r1/fig@3)\n\n![gone](media:r2/img@9)\n"
    )
    items = {
        "img": ({"kind": "image", "mime": "image/png"}, b"PNG"),
        "log": ({"kind": "text", "mime": "text/plain", "text": "hello"}, b""),
        "fig": ({"kind": "figure", "mime": "application/vnd.plotly.v1+json"}, b"{}"),
    }

    def resolve(ref):
        return items.get(ref.key) if ref.run_id == "r1" else None

    zf = zipfile.ZipFile(io.BytesIO(export(text, resolve, "R")))
    md = zf.read("R.md").decode()
    assert "![a sample](files/r1-img-3.png)" in md
    assert "```text\nhello\n```" in md
    assert "[fig](files/r1-fig-3.plotly.json)" in md
    assert "*(missing: img at step 9 of run r2)*" in md
    assert zf.read("files/r1-img-3.png") == b"PNG"


def test_fields_are_validated(tmp_path):
    out = clean_fields(
        [
            {"name": "verdict", "type": "choice", "options": ["keep", "", "drop"], "x": 1},
            {"name": "gpu", "type": "number", "unit": "h"},
            {"name": "verdict", "type": "text"},
        ]
    )
    assert out == [
        {"name": "verdict", "type": "choice", "options": ["keep", "drop"]},
        {"name": "gpu", "type": "number", "unit": "h"},
    ]

    with pytest.raises(ValueError, match="unknown property type"):
        clean_fields([{"name": "a", "type": "color"}])

    with pytest.raises(ValueError, match="needs a name"):
        clean_fields([{"type": "text"}])

    assert read_fields(tmp_path) == []
    save_fields(tmp_path, out)
    assert read_fields(tmp_path) == out


def test_values_must_fit_their_property():
    choice = {"name": "verdict", "type": "choice", "options": ["keep", "drop"]}
    tags = {"name": "split", "type": "tags", "options": ["train", "val"]}
    check_field(choice, "keep")
    check_field(tags, ["train", "val"])
    check_field({"name": "gpu", "type": "number"}, 7.5)
    check_field({"name": "day", "type": "date"}, "2026-10-16")
    check_field({"name": "paper", "type": "link"}, "https://arxiv.org/abs/1")
    check_field(choice, None)  # clearing is always allowed

    with pytest.raises(ValueError, match="one of: keep, drop"):
        check_field(choice, "maybe")

    with pytest.raises(ValueError, match="takes tags from"):
        check_field(tags, ["train", "test"])

    with pytest.raises(ValueError, match="not a number"):
        check_field({"name": "gpu", "type": "number"}, "lots")

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        check_field({"name": "day", "type": "date"}, "yesterday")

    with pytest.raises(ValueError, match="http"):
        check_field({"name": "paper", "type": "link"}, "arxiv")

    with pytest.raises(ValueError, match="yes/no"):
        check_field({"name": "ok", "type": "bool"}, "maybe")
