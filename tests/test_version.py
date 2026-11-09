"""`NAME version`: the copyright line and its fallback for narrow console encodings."""

from __future__ import annotations

import io
import sys

import pytest

from nuboard import __version__
from nuboard._meta import copyright_line, printable
from nuboard.cli import main


def test_single_year_then_range() -> None:
    assert copyright_line("1.2.3", 2026) == (
        "NuBoard 1.2.3 Copyright © 2026 Esteban Gómez (MIT License)"
    )
    assert copyright_line("1.2.3", 2025) == copyright_line("1.2.3", 2026)
    assert "© 2026–2028 " in copyright_line("1.2.3", 2028)


@pytest.mark.parametrize("encoding", ["utf-8", "cp1252", "cp437", "ascii", None])
def test_printable_encodes(encoding: str | None) -> None:
    line = printable(copyright_line("1.2.3", 2028), encoding)
    line.encode(encoding or "ascii")  # never raises

    if encoding == "ascii" or encoding is None:
        assert line == "NuBoard 1.2.3 Copyright (c) 2026-2028 Esteban Gomez (MIT License)"

    if encoding == "utf-8":
        assert "©" in line and "ó" in line


def test_cli_on_cp437_console(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp437")
    monkeypatch.setattr(sys, "stdout", buf)
    main(["version"])
    buf.flush()
    out = buf.buffer.getvalue().decode("cp437")  # type: ignore[attr-defined]
    assert out.startswith(f"NuBoard {__version__} Copyright ")
    assert "Esteban G" in out
