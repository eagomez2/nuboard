"""What every route module of the viewer shares: the catalog, the store, settings and lookups."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import _fs
from ..artifacts import find_artifact_projects
from ..catalog import Catalog
from ..reports import MediaRef
from .common import _NotFound, with_notes
from .data import Store


@dataclass
class Context:
    """The state and settings of one viewer app, handed to each `routes(ctx)`.

    Args:
        catalog: Metadata of every run under the root.
        store: Cached readers and derived data of the runs.
        cache_dir: Folder for the catalog cache, or None for the default.
        edit_artifacts: Allow adding, unlinking and restoring artifact versions.
        read_only_reports: Refuse every change to reports.
        read_only_hypotheses: Refuse every change to hypothesis boards.
        lock_directions: Refuse changes to `directions.json`.
        max_image_bytes: Size limit of an image uploaded into a report.
        max_text_bytes: Size limit of a text file uploaded into a report.
        max_audio_bytes: Size limit of an audio file uploaded into a report.
    """

    catalog: Catalog
    store: Store
    cache_dir: Path | None
    edit_artifacts: bool
    read_only_reports: bool
    read_only_hypotheses: bool
    lock_directions: bool
    max_image_bytes: int
    max_text_bytes: int
    max_audio_bytes: int

    def record_or_404(self, key: str) -> dict[str, Any]:
        """Return a run's catalog record, refreshing once if missing; else raise `_NotFound`."""
        record = self.catalog.get(key)

        if record is None:
            self.catalog.refresh()
            record = self.catalog.get(key)

        if record is None:
            raise _NotFound(key)

        return record

    def project_dir(self, name: str) -> Path | None:
        """Return the folder of a known project, or None if it is unknown."""
        return self.catalog.project_dir(name)

    def name_of(self, folder: Path) -> str | None:
        """Return the project name of a folder under the root, or None outside it."""
        root = self.catalog.root.resolve()

        try:
            rel = folder.resolve().relative_to(root)
        except ValueError:
            return None

        return rel.as_posix() if rel.parts else root.name

    def artifact_project(self, name: str) -> Path | None:
        """Return the folder of a project with runs or artifacts, or None if there is none."""
        pdir = self.project_dir(name)

        if pdir is not None:
            return pdir

        return next(
            (p for p in find_artifact_projects(self.catalog.root) if self.name_of(p) == name),
            None,
        )

    def storage_projects(self) -> list[tuple[str, Path]]:
        """Return every project folder with runs or artifacts, with its name."""
        root = self.catalog.root
        dirs = {(root / r["path"]).parent.parent for r in self.catalog.runs()}
        dirs |= set(find_artifact_projects(root))
        return sorted((self.name_of(d) or d.name, d) for d in dirs)

    def audio_notes_of(self, key: str) -> dict[str, Any]:
        """Return a run's audio notes, by `<media key>@<step>`."""
        path = self.catalog.path_of(key)
        ann = _fs.read_json(path / "annotations.json", {}) if path else {}
        notes = ann.get("audio_notes") if isinstance(ann, dict) else None
        return notes if isinstance(notes, dict) else {}

    def run_key_of(self, project: str, run_id: str) -> str | None:
        """Return the catalog key of run `run_id` of `project`, or None."""

        for refresh in (False, True):
            if refresh:
                self.catalog.refresh()

            for r in self.catalog.runs():
                if r["project"] == project and run_id in (r["id"], Path(r["path"]).name):
                    return r["key"]

        return None

    def find_item(self, project: str, ref: MediaRef) -> tuple[str, dict[str, Any]] | None:
        """Return the run key and media list entry a reference points to, or None."""
        key = self.run_key_of(project, ref.run_id)
        reader = self.store.fresh_reader(key) if key else None

        if key is None or reader is None:
            return None

        found: dict[str, Any] | None = None

        for e in reader.media(latest=True):
            if e.key == ref.key and e.step == ref.step:
                found = {"key": e.key, "step": e.step, "time": e.time, "index": e.uid, **e.meta}
                found = with_notes(found, self.audio_notes_of(key))

        for t in reader.texts(ref.key, latest=True):
            if t.step == ref.step:
                found = {"key": t.key, "step": t.step, "time": t.time, "kind": "text"}
                found.update({"mime": "text/plain", "text": t.text})

        return (key, found) if found else None
