"""
atomic_json.py — race-free JSON hand-off between the probe and the CLI.

Problem (Review 2 "pending hardening"): the probe exports metrics to a JSON
file once per window. If a reader opens the file while the writer is
truncating/rewriting it, the reader sees half a document -> JSONDecodeError.

Fix, two layers:
  1. WRITER  : write to a temp file in the SAME directory, flush + fsync, then
               os.replace() it over the target. rename(2) is atomic on POSIX,
               so a reader sees either the complete old file or the complete
               new file — never a partial one.
  2. READER  : read_json_with_retry() retries a few times on
               FileNotFoundError / JSONDecodeError (defence in depth, e.g.
               for network filesystems or a writer that is not using this
               helper) and returns None if it still cannot get a valid
               document, so the caller can simply skip that window.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def write_json_atomic(path: str | os.PathLike, data: Any, indent: int | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_json_with_retry(
    path: str | os.PathLike,
    retries: int = 5,
    delay: float = 0.005,
) -> Any | None:
    """Return the parsed JSON, or None if no valid document could be read."""
    for attempt in range(retries):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            if attempt < retries - 1:
                time.sleep(delay)
    return None
