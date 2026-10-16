"""Import TensorBoard event files (`events.out.tfevents.*`) as runs.

Standard library only: event files are TFRecord files of `Event` protocol
buffers, and both are decoded here without TensorFlow, TensorBoard or protobuf.
Logs written by TensorFlow 1 and 2, PyTorch's `SummaryWriter` and tensorboardX
are understood.

Each folder holding event files becomes one run, named after its path relative to
the log folder. Scalars, images, audio, text, PR curves and hyperparameters
(the HParams plugin) are imported; histograms, graphs, embeddings and other plugins are
counted and skipped. A folder that holds only `add_hparams` output (PyTorch writes
it to a timestamped sub-folder) is merged into its parent run.

Example:
    >>> from nuboard.tensorboard import import_logdir
    >>> results = import_logdir("runs/", project="mnist")
"""

from __future__ import annotations

import hashlib
import os
import struct
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import _fs
from ._media import pr_curve_json
from .run import Run

# TensorFlow DataType enum values and their struct formats (little-endian).
_DTYPES: dict[int, str] = {
    1: "f",  # DT_FLOAT
    2: "d",  # DT_DOUBLE
    3: "i",  # DT_INT32
    4: "B",  # DT_UINT8
    5: "h",  # DT_INT16
    6: "b",  # DT_INT8
    9: "q",  # DT_INT64
    10: "?",  # DT_BOOL
    17: "H",  # DT_UINT16
    19: "e",  # DT_HALF
    22: "I",  # DT_UINT32
    23: "Q",  # DT_UINT64
}
_DT_STRING = 7
_DT_BFLOAT16 = 14


# -- protocol buffer wire format ----------------------------------------------


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    """Decode a base-128 varint at `pos`; return its value and the next position."""
    result = shift = 0

    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift

        if not byte & 0x80:
            return result, pos

        shift += 7


def _fields(buf: bytes) -> Iterator[tuple[int, int, Any]]:
    """Yield `(field_number, wire_type, value)` for each field of a message.

    Varints are returned as unsigned ints, length-delimited fields as bytes and
    fixed-width fields as their raw 4 or 8 bytes.

    Raises:
        ValueError: On a wire type this decoder does not support (groups).
    """
    pos, end = 0, len(buf)

    while pos < end:
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7

        if wire == 0:
            value, pos = _varint(buf, pos)
        elif wire == 1:
            value, pos = buf[pos : pos + 8], pos + 8
        elif wire == 2:
            size, pos = _varint(buf, pos)
            value, pos = buf[pos : pos + size], pos + size
        elif wire == 5:
            value, pos = buf[pos : pos + 4], pos + 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")

        yield number, wire, value


def _signed(value: int) -> int:
    """Reinterpret an unsigned 64-bit varint as a signed int64."""
    return value - (1 << 64) if value >= 1 << 63 else value


def _double(raw: bytes) -> float:
    """Decode a little-endian float64."""
    return struct.unpack("<d", raw)[0]


def _float(raw: bytes) -> float:
    """Decode a little-endian float32."""
    return struct.unpack("<f", raw)[0]


# -- TensorBoard messages ------------------------------------------------------


@dataclass
class TBValue:
    """One `Summary.Value` of an event, decoded.

    Attributes:
        tag: The value's tag, such as `train/loss`.
        plugin: Plugin name from the value's metadata, or `""` when it has none.
        plugin_content: Plugin-specific metadata bytes (used by HParams).
        kind: `"scalar"`, `"image"`, `"audio"`, `"histograms"`, `"tensor"` or
            `"other"`.
        scalar: The value of a TF1 `simple_value`.
        image: Encoded image bytes of a TF1 `Summary.Image`.
        audio: Encoded audio bytes of a TF1 `Summary.Audio`.
        sample_rate: Sample rate of the TF1 audio.
        tensor: Decoded `TensorProto` as `(dtype, shape, values)`.
    """

    tag: str = ""
    plugin: str = ""
    plugin_content: bytes = b""
    kind: str = "other"
    scalar: float | None = None
    image: bytes | None = None
    audio: bytes | None = None
    sample_rate: float | None = None
    tensor: tuple[int, list[int], list[Any]] | None = None


@dataclass
class TBEvent:
    """One `Event` record with its summary values.

    Attributes:
        wall_time: Unix time the event was written.
        step: Global step.
        values: The summary values (empty for non-summary events).
    """

    wall_time: float = 0.0
    step: int = 0
    values: list[TBValue] = field(default_factory=list)


def _tensor(buf: bytes) -> tuple[int, list[int], list[Any]]:
    """Decode a `TensorProto` into `(dtype, shape, flat values)`."""
    dtype, shape, content = 0, [], b""
    values: list[Any] = []

    for number, wire, value in _fields(buf):
        if number == 1:
            dtype = value
        elif number == 2:  # TensorShapeProto
            for n, _, dim in _fields(value):
                if n == 2:
                    size = next((v for k, _, v in _fields(dim) if k == 1), 0)
                    shape.append(_signed(size))
        elif number == 4:
            content = value
        elif number == 8:
            values.append(value)
        elif number in (5, 6):  # float_val, double_val
            width, fmt = (4, "<f") if number == 5 else (8, "<d")

            if wire == 2:  # packed
                values.extend(struct.unpack(f"<{len(value) // width}{fmt[1]}", value))
            else:
                values.append(struct.unpack(fmt, value)[0])
        elif number in (7, 10, 11, 13):  # int_val, int64_val, bool_val, half_val
            if wire == 2:
                pos, items = 0, []

                while pos < len(value):
                    item, pos = _varint(value, pos)
                    items.append(item)
            else:
                items = [value]

            if number == 13:  # float16 bits
                values.extend(struct.unpack("<e", struct.pack("<H", v & 0xFFFF))[0] for v in items)
            elif number == 11:
                values.extend(bool(v) for v in items)
            else:  # negative int32 values are sign-extended to 64 bits on the wire
                values.extend(_signed(v) for v in items)

    if content and dtype in _DTYPES:
        fmt = _DTYPES[dtype]
        count = len(content) // struct.calcsize(fmt)
        values = list(struct.unpack(f"<{count}{fmt}", content[: count * struct.calcsize(fmt)]))
    elif content and dtype == _DT_BFLOAT16:
        values = [
            struct.unpack("<f", b"\0\0" + content[i : i + 2])[0] for i in range(0, len(content), 2)
        ]

    return dtype, shape, values


def _summary_value(buf: bytes) -> TBValue:
    """Decode one `Summary.Value`."""
    out = TBValue()

    for number, _, value in _fields(buf):
        if number == 1:
            out.tag = value.decode("utf-8", "replace")
        elif number == 7 and not out.tag:  # node_name, used by very old writers
            out.tag = value.decode("utf-8", "replace")
        elif number == 2:
            out.kind, out.scalar = "scalar", _float(value)
        elif number == 4:  # Summary.Image
            out.kind = "image"
            out.image = next((v for k, _, v in _fields(value) if k == 4), b"")
        elif number == 6:  # Summary.Audio
            out.kind = "audio"

            for k, _, v in _fields(value):
                if k == 1:
                    out.sample_rate = _float(v)
                elif k == 4:
                    out.audio = v
        elif number == 5:
            out.kind = "histograms"
        elif number == 8:
            out.kind, out.tensor = "tensor", _tensor(value)
        elif number == 9:  # SummaryMetadata
            for k, _, v in _fields(value):
                if k == 1:  # PluginData
                    for pk, _, pv in _fields(v):
                        if pk == 1:
                            out.plugin = pv.decode("utf-8", "replace")
                        elif pk == 2:
                            out.plugin_content = pv

    return out


def _event(buf: bytes) -> TBEvent:
    """Decode one `Event`."""
    out = TBEvent()

    for number, _, value in _fields(buf):
        if number == 1:
            out.wall_time = _double(value)
        elif number == 2:
            out.step = _signed(value)
        elif number == 5:  # Summary
            out.values = [_summary_value(v) for k, _, v in _fields(value) if k == 1]

    return out


def read_records(path: str | os.PathLike[str]) -> Iterator[bytes]:
    """Yield the payload of each record in a TFRecord file.

    Each record is a little-endian uint64 length, a 4-byte CRC of the length, the
    payload and a 4-byte CRC of the payload. CRCs are not verified; a truncated
    record at the end (a writer that was killed) ends the file.

    Args:
        path: The TFRecord file.

    Yields:
        Each record's payload bytes.
    """

    with open(path, "rb") as f:
        while True:
            header = f.read(12)

            if len(header) < 12:
                return

            (length,) = struct.unpack("<Q", header[:8])
            data = f.read(length)

            if len(data) < length or len(f.read(4)) < 4:
                return

            yield data


def read_events(path: str | os.PathLike[str]) -> Iterator[TBEvent]:
    """Yield the decoded events of one event file.

    Args:
        path: An `events.out.tfevents.*` file.

    Yields:
        Each event, in file order. Records that fail to decode are skipped.
    """

    for record in read_records(path):
        try:
            yield _event(record)
        except (ValueError, IndexError, struct.error):
            continue


def _proto_value(buf: bytes) -> Any:
    """Decode a `google.protobuf.Value` into a Python value."""

    for number, _, value in _fields(buf):
        if number == 1:
            return None

        if number == 2:
            number_value = _double(value)
            return int(number_value) if number_value.is_integer() else number_value

        if number == 3:
            return value.decode("utf-8", "replace")

        if number == 4:
            return bool(value)

        if number == 6:  # ListValue
            return [_proto_value(v) for k, _, v in _fields(value) if k == 1]

    return None


def parse_hparams(content: bytes) -> dict[str, Any]:
    """Extract the hyperparameters from HParams plugin metadata.

    Args:
        content: `plugin_data.content` of an HParams summary value.

    Returns:
        The session's hyperparameters, or an empty dict if `content` holds no
        `SessionStartInfo` (for example the experiment definition).
    """
    params: dict[str, Any] = {}

    for number, _, value in _fields(content):
        if number != 3:  # SessionStartInfo
            continue

        for k, _, entry in _fields(value):
            if k != 1:  # map<string, Value> hparams
                continue

            name, item = "", None

            for ek, _, ev in _fields(entry):
                if ek == 1:
                    name = ev.decode("utf-8", "replace")
                elif ek == 2:
                    item = _proto_value(ev)

            if name:
                params[name] = item

    return params


# -- import --------------------------------------------------------------------


@dataclass
class ImportResult:
    """What importing one TensorBoard run folder produced.

    Attributes:
        source: The folder the events came from.
        name: The run's name.
        run_id: The new run's id, or the existing one when `skipped` is True.
        path: The run's folder.
        skipped: True when the run was imported before and left unchanged.
        scalars: Number of scalar points imported.
        media: Number of images, audio clips and texts imported.
        hparams: Number of hyperparameters stored as the run's config.
        ignored: Counts of values that were not imported, by kind or plugin.
    """

    source: Path
    name: str
    run_id: str
    path: Path
    skipped: bool = False
    scalars: int = 0
    media: int = 0
    hparams: int = 0
    ignored: Counter[str] = field(default_factory=Counter)


def find_event_dirs(logdir: str | os.PathLike[str]) -> dict[Path, list[Path]]:
    """Find the folders under `logdir` that hold event files.

    Args:
        logdir: The TensorBoard log folder (what `tensorboard --logdir` takes).

    Returns:
        Each folder mapped to its event files, sorted by name (which sorts them by
        creation time). Folders are in sorted order.
    """
    found: dict[Path, list[Path]] = {}

    for dirpath, dirnames, filenames in os.walk(logdir):
        dirnames.sort()
        files = sorted(f for f in filenames if "tfevents" in f)

        if files:
            found[Path(dirpath)] = [Path(dirpath) / f for f in files]

    return found


def _is_hparams_only(files: list[Path]) -> bool:
    """Return True if the files hold HParams session info and no media or text."""
    has_session = False

    for path in files:
        for event in read_events(path):
            for v in event.values:
                if v.plugin == "hparams":
                    has_session = has_session or bool(parse_hparams(v.plugin_content))
                elif v.kind in ("image", "audio") or v.plugin in ("images", "audio", "text"):
                    return False

    return has_session


def _scan(files: list[Path]) -> tuple[float | None, float | None, dict[str, Any]]:
    """Return the first and last wall time and the hyperparameters of event files."""
    first = last = None
    hparams: dict[str, Any] = {}

    for path in files:
        for event in read_events(path):
            if event.wall_time:
                first = event.wall_time if first is None else min(first, event.wall_time)
                last = event.wall_time if last is None else max(last, event.wall_time)

            for v in event.values:
                if v.plugin == "hparams":
                    hparams.update(parse_hparams(v.plugin_content))

    return first, last, hparams


def _strings(values: list[Any]) -> list[bytes]:
    """Return the bytes items of a tensor's values."""
    return [v for v in values if isinstance(v, bytes)]


def _write(run: Run, files: list[Path], result: ImportResult, prefix: str = "") -> None:
    """Log the contents of event files into `run`, counting what was imported."""

    for path in files:
        plugins: dict[str, str] = {}  # TF2 writes a tag's metadata only with its first value

        for event in read_events(path):
            scalars: dict[str, float] = {}
            step, t = event.step, event.wall_time or None

            for v in event.values:
                tag = prefix + v.tag

                if v.plugin:
                    plugins[tag] = v.plugin

                plugin = plugins.get(tag, "")

                if v.kind == "scalar" and v.scalar is not None:
                    scalars[tag] = v.scalar
                elif v.kind == "image" and v.image:
                    run.add_image(tag, v.image, step, time=t)
                    result.media += 1
                elif v.kind == "audio" and v.audio:
                    run.add_audio(tag, v.audio, step, time=t)
                    result.media += 1
                elif v.kind == "tensor" and v.tensor is not None:
                    dtype, shape, values = v.tensor

                    if plugin == "hparams":
                        continue

                    if plugin == "images":  # [width, height, image, image, ...]
                        images = _strings(values)[2:]

                        for i, image in enumerate(images):
                            run.add_image(
                                tag if len(images) == 1 else f"{tag}/{i}", image, step, time=t
                            )

                        result.media += len(images)
                    elif plugin == "audio":  # [[audio, label], ...] or [audio, ...]
                        clips = _strings(values)[:: 2 if len(shape) == 2 and shape[1] == 2 else 1]

                        for i, clip in enumerate(clips):
                            run.add_audio(
                                tag if len(clips) == 1 else f"{tag}/{i}", clip, step, time=t
                            )

                        result.media += len(clips)
                    elif plugin == "pr_curves" and len(shape) == 2 and shape[0] == 6:
                        # rows: TP, FP, TN, FN, precision, recall; one column per threshold
                        n = shape[1]
                        rows = [values[i * n : (i + 1) * n] for i in range(6)]
                        names = ("tp", "fp", "tn", "fn", "precision", "recall")
                        counts = dict(zip(names, rows, strict=True))
                        run._put_media(
                            tag, step, lambda c=counts: pr_curve_json(c), {"kind": "pr"}, t
                        )
                        result.media += 1
                    elif plugin == "text" or dtype == _DT_STRING:
                        text = "\n".join(s.decode("utf-8", "replace") for s in _strings(values))
                        key = tag.removesuffix("/text_summary")  # PyTorch, tensorboardX
                        run.add_text(key, text, step, time=t)
                        result.media += 1
                    elif len(values) == 1 and isinstance(values[0], (int, float)):
                        scalars[tag] = float(values[0])
                    else:
                        result.ignored[plugin or "tensor"] += 1
                elif v.plugin == "hparams" or plugin == "hparams":
                    continue
                else:
                    result.ignored[plugin or v.kind] += 1

            if scalars:
                run.log(scalars, step=step, time=t)
                result.scalars += len(scalars)


def _run_id(source: Path, name: str, started: float) -> str:
    """Return a stable run id, so importing the same folder twice is detected."""
    digest = hashlib.sha1(str(source.resolve()).encode()).hexdigest()[:6]
    stamp = datetime.fromtimestamp(started).strftime("%Y%m%d-%H%M")
    return f"{stamp}_{_fs.sanitize(name)}_{digest}"


def import_logdir(
    logdir: str | os.PathLike[str],
    project: str | None = None,
    *,
    dir: str | os.PathLike[str] | None = None,
    tags: list[str] | None = None,
) -> list[ImportResult]:
    """Import every TensorBoard run under `logdir` into a project.

    Each folder holding event files becomes a run named after its path relative to
    `logdir` (for example `lr0.01/train`), with its parent path as the run's
    group. Wall times, steps and hyperparameters are kept, and the run is marked
    finished at its last event. Importing the same folder again skips it.

    Args:
        logdir: The TensorBoard log folder, or a single run folder.
        project: Project to import into. Defaults to the name of `logdir`.
        dir: Root folder for projects, as in `init`. Defaults to `$NUBOARD_DIR` or
            `./experiments`.
        tags: Tags for the new runs. Defaults to `["tensorboard"]`.

    Returns:
        One result per run, in folder order.

    Raises:
        FileNotFoundError: If `logdir` does not exist or holds no event files.
    """
    root = Path(logdir).expanduser()

    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a folder")

    found = find_event_dirs(root)

    if not found:
        raise FileNotFoundError(f"no TensorBoard event files (*tfevents*) under {root}")

    project = project or root.resolve().name
    tags = ["tensorboard"] if tags is None else tags

    # PyTorch's add_hparams writes to a sub-folder of the run; fold it into the run
    merged: dict[Path, list[Path]] = {}

    for folder, files in found.items():
        if folder != root and folder.parent in found and _is_hparams_only(files):
            merged.setdefault(folder.parent, []).extend(files)

    folded = {f.parent for files in merged.values() for f in files}
    results = []

    for folder, files in found.items():
        if folder in folded:
            continue

        extra = merged.get(folder, [])
        rel = folder.relative_to(root).as_posix()
        name = root.resolve().name if rel == "." else rel
        group = None if rel == "." or "/" not in rel else rel.rsplit("/", 1)[0]
        first, last, hparams = _scan(files + extra)
        started = first if first is not None else os.path.getmtime(files[0])
        ended = last if last is not None else started
        run_id = _run_id(folder, name, started)
        run_dir = Path(dir) if dir is not None else None
        result = ImportResult(folder, name, run_id, Path(), hparams=len(hparams))

        try:
            run = Run(
                project,
                name=name,
                config=hparams,
                dir=run_dir,
                tags=tags,
                group=group,
                notes=f"Imported from TensorBoard logs in {folder.resolve()}",
                run_id=run_id,
                capture_env=False,
                _started=started,
            )
        except FileExistsError:
            result.skipped = True
            result.path = _existing(project, run_dir, run_id)
            results.append(result)
            continue

        result.path = run.path

        try:
            _write(run, files, result)
            _write(run, extra, result)
        except BaseException:
            run.finish("crashed", exit_code=1, error="TensorBoard import failed", _ended=ended)
            raise

        run.finish(_ended=ended)
        results.append(result)

    return results


def _existing(project: str, dir: Path | None, run_id: str) -> Path:
    """Return the folder of an already imported run."""
    from .run import project_dir

    return project_dir(project, dir) / "runs" / run_id
