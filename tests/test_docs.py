import importlib.util
import json
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _examples():
    spec = importlib.util.spec_from_file_location(
        "docs_examples", ROOT / "scripts" / "docs_examples.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DOCS = _examples()
CASES = [(page, i, code) for page in DOCS.PAGES for i, code in enumerate(DOCS.examples(page), 1)]


@pytest.mark.parametrize(("page", "i", "code"), CASES, ids=[f"{p.stem}-{i}" for p, i, _ in CASES])
def test_api_docs_example_runs(page, i, code, tmp_path):
    pytest.importorskip("matplotlib")
    res = DOCS.run(code, tmp_path)
    assert res.returncode == 0, res.stderr
    assert list((tmp_path / "experiments").glob("*/runs/*/run.json"))


def test_api_docs_have_a_page_for_every_method_in_the_menu():
    import nuboard as nb

    api = ROOT / "docs" / "api"
    nav = (ROOT / "mkdocs.yml").read_text("utf-8")
    text = "".join(p.read_text("utf-8") for p in DOCS.PAGES)
    public = [n for n in dir(nb.Run) if n.startswith(("add_", "use_")) or n in ("finish", "flush")]

    for n in public:
        assert (api / f"{n}.md").exists() or f"## `{n}`" in text, n

    for page in api.glob("*.md"):
        assert f"api/{page.name}" in nav, page.name


def test_get_started_page_shows_the_script_as_it_is():
    page = (ROOT / "docs" / "get-started.md").read_text("utf-8")
    shown = page.split('??? example "examples/get_started.py"', 1)[1]
    shown = shown.split("```python\n", 1)[1].rsplit("    ```", 1)[0]
    script = (ROOT / "examples" / "get_started.py").read_text("utf-8")
    assert textwrap.dedent(shown) == script


def test_get_started_script_logs_every_media_kind(tmp_path):
    script = str(ROOT / "examples" / "get_started.py")
    res = DOCS.run(f"import runpy\nrunpy.run_path({script!r})['train'](0.2, epochs=5)", tmp_path)
    assert res.returncode == 0, res.stderr
    run = next((tmp_path / "experiments" / "get-started" / "runs").iterdir())
    assert json.loads((run / "run.json").read_text())["config"]["lr"] == 0.2
    assert (run / "media.r0.pack").stat().st_size > 0
