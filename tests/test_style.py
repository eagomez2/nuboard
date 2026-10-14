import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _checker():
    spec = importlib.util.spec_from_file_location(
        "blank_lines", ROOT / "scripts" / "blank_lines.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_blank_line_rule_inserts_around_blocks():
    fix = _checker().fix
    src = (
        "def f(x):\n    y = 1\n    if x:\n        return y\n"
        "    # note\n    for i in x:\n        y += i\n    return y\n"
    )
    assert fix(src) == (
        "def f(x):\n    y = 1\n\n    if x:\n        return y\n\n    # note\n"
        "    for i in x:\n        y += i\n\n    return y\n"
    )
    assert fix(fix(src)) == fix(src)


def test_repository_follows_the_blank_line_rule():
    missing = _checker().missing_blank_lines
    files = [
        p
        for d in ("src", "tests", "scripts", "examples", "benchmarks")
        for p in (ROOT / d).rglob("*.py")
    ]
    offenders = [str(p.relative_to(ROOT)) for p in files if missing(p.read_text(encoding="utf-8"))]
    assert offenders == []
