"""Release consistency: version strings and the frontend's lockfile."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_frontend_dependencies_match_the_lockfile():
    package = json.loads((ROOT / "frontend" / "package.json").read_text("utf-8"))
    lock = (ROOT / "frontend" / "pnpm-lock.yaml").read_text("utf-8")
    locked = dict(re.findall(r"^      '?([^'\s:]+)'?:\n        specifier: (\S+)$", lock, re.M))
    wanted = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
    assert wanted == locked, "package.json and pnpm-lock.yaml disagree; run pnpm install"


def test_versions_agree():
    pyproject = (ROOT / "pyproject.toml").read_text("utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)  # type: ignore[union-attr]
    package = json.loads((ROOT / "frontend" / "package.json").read_text("utf-8"))
    assert package["version"] == version
    assert "pip install nuboard\n" in (ROOT / "README.md").read_text("utf-8")
    assert f"nuboard {version}" in (ROOT / "docs" / "installation.md").read_text("utf-8")
    assert f"## {version}" in (ROOT / "docs" / "changelog.md").read_text("utf-8")
