"""Hatch build hook: bundle the built frontend into the wheel.

If `src/<package>/static/index.html` is missing, it runs `pnpm install` and
`pnpm build` in `frontend/` (Node is needed only by people building wheels,
never by users). Set `SKIP_FRONTEND_BUILD=1` to skip.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class FrontendBuildHook(BuildHookInterface):
    """Build hook that builds the frontend into the package's `static/` folder."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        """Build the frontend with pnpm before the wheel is assembled.

        Nothing is done for editable builds, when `static/index.html` already
        exists, when `SKIP_FRONTEND_BUILD` is set, or when there is no
        `frontend/` folder (an sdist that already contains `static/`). Without
        a `pnpm` executable, `npx --yes pnpm@10` is used.

        Args:
            version: The build version, such as `"standard"` or `"editable"`.
            build_data: Hatch build data (not modified).

        Raises:
            subprocess.CalledProcessError: If `pnpm install` or `pnpm build` fails.
        """
        root = Path(self.root)
        package = self.metadata.name.replace("-", "_")
        static = root / "src" / package / "static"

        if (
            version == "editable"
            or (static / "index.html").exists()
            or os.environ.get("SKIP_FRONTEND_BUILD")
        ):
            return

        frontend = root / "frontend"

        if not frontend.exists():
            return  # building from an sdist that already contains static/

        pnpm = shutil.which("pnpm")
        cmd = [pnpm] if pnpm else [shutil.which("npx") or "npx", "--yes", "pnpm@10"]
        subprocess.run([*cmd, "install", "--frozen-lockfile"], cwd=frontend, check=True)
        subprocess.run([*cmd, "build"], cwd=frontend, check=True)
