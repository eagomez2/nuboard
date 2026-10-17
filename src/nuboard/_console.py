"""Console capture: copy what the script prints to `files/output.log`.

`sys.stdout` and `sys.stderr` are replaced by `Tee` objects that write to the
original stream and to the log file. Only output written through Python's
`sys.stdout` and `sys.stderr` is captured (print, logging, warnings, tqdm,
tracebacks), not output that C extensions write to the file descriptors
directly.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import IO, Any

MAX_BYTES = 64 * 1024**2  # the log stops growing past this, with a note at its end


class Tee:
    """Write to a stream and to a shared log.

    Args:
        stream: The original stream, which keeps receiving everything.
        log: The log the copy goes to.
    """

    def __init__(self, stream: Any, log: ConsoleLog) -> None:
        self._stream = stream
        self._log = log

    def write(self, text: str) -> int:
        """Write `text` to the stream, then to the log."""
        n = self._stream.write(text)
        self._log.write(text)
        return n

    def flush(self) -> None:
        """Flush the stream."""
        self._stream.flush()

    def __getattr__(self, name: str) -> Any:
        """Delegate everything else (`encoding`, `isatty`, `fileno`, ...) to the stream."""
        return getattr(self._stream, name)


class ConsoleLog:
    """Capture `sys.stdout` and `sys.stderr` into `path` until `close`.

    Args:
        path: The log file, appended to (a resumed run continues its log). It is
            created on the first output, so a quiet script leaves no file.
        header: A line written before the first output, such as the session's
            start time.
    """

    def __init__(self, path: Path, header: str | None = None) -> None:
        self._path = path
        self._file: IO[str] | None = None
        self._open = True  # until closed, or stopped at MAX_BYTES
        self._header = header + "\n" if header and not header.endswith("\n") else header
        self._lock = threading.Lock()
        self._size = 0
        self._flushed = time.monotonic()
        self._out, self._err = sys.stdout, sys.stderr
        self._tees = (Tee(sys.stdout, self), Tee(sys.stderr, self))
        sys.stdout, sys.stderr = self._tees  # type: ignore[assignment]

    def write(self, text: str) -> None:
        """Append `text` to the log; the file is flushed when a second has passed."""

        with self._lock:
            if not self._open or not text:
                return

            if self._file is None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._file = open(self._path, "a", encoding="utf-8", errors="replace")
                self._size = self._path.stat().st_size
                text = (self._header or "") + text

            f = self._file
            self._size += len(text)

            if self._size > MAX_BYTES:
                f.write(f"\n[nuboard: console log stopped at {MAX_BYTES // 1024**2} MB]\n")
                f.close()
                self._file, self._open = None, False
                return

            f.write(text)
            now = time.monotonic()

            if now - self._flushed > 1.0:
                f.flush()
                self._flushed = now

    def flush(self) -> None:
        """Write what is buffered to the file; the run calls it on each heartbeat."""

        with self._lock:
            if self._file is not None:
                self._file.flush()
                self._flushed = time.monotonic()

    def close(self) -> None:
        """Put the original streams back and close the log. Safe to call twice."""

        if sys.stdout is self._tees[0]:
            sys.stdout = self._out

        if sys.stderr is self._tees[1]:
            sys.stderr = self._err

        with self._lock:  # a stream replaced after us keeps its Tee, which then only passes through
            self._open = False

            if self._file is not None:
                self._file.close()
                self._file = None
