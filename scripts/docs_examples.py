"""Run the complete examples of the Python API docs.

A complete example is a `python` code block that starts with an import and
calls `nb.init`; the other blocks are fragments. Each example runs in its own
process, in a working folder whose `experiments/` receives the runs.

Usage:
    python scripts/docs_examples.py [DIR]

DIR defaults to a new temporary folder; it is printed at the end.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = sorted((ROOT / "docs" / "api").glob("*.md"))
BLOCK = re.compile(r"^```python\n(.*?)^```", re.S | re.M)


def examples(page: Path) -> list[str]:
    """Return the complete examples of a docs page, in order."""
    return [
        code
        for code in BLOCK.findall(page.read_text("utf-8"))
        if code.startswith(("import ", "from ")) and "nb.init(" in code
    ]


def run(code: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one example with `cwd` as its working folder, in a new process."""
    env = {**os.environ, "NUBOARD_DIR": str(cwd / "experiments"), "MPLBACKEND": "Agg"}
    return subprocess.run(
        [sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True
    )


def main() -> int:
    """Run every example, stopping at the first failure."""
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="docs-"))
    out.mkdir(parents=True, exist_ok=True)

    for page in PAGES:
        for i, code in enumerate(examples(page), 1):
            res = run(code, out)

            if res.returncode:
                print(f"{page.name} example {i} failed:\n{res.stderr}", file=sys.stderr)
                return 1

            print(f"{page.name} example {i}: ok")

    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
