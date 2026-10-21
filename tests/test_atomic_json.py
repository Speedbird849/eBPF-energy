"""Tests for the JSON hand-off hardening (Review 2 'race condition' item)."""
import json
import multiprocessing as mp
import os
import threading
import time

from src.common.atomic_json import read_json_with_retry, write_json_atomic


def test_write_then_read_roundtrip(tmp_path):
    p = tmp_path / "m.json"
    write_json_atomic(p, {"a": 1})
    assert read_json_with_retry(p) == {"a": 1}


def test_no_temp_files_left_behind(tmp_path):
    p = tmp_path / "m.json"
    for i in range(20):
        write_json_atomic(p, {"i": i})
    assert [f.name for f in tmp_path.iterdir()] == ["m.json"]


def test_missing_file_returns_none_instead_of_raising(tmp_path):
    assert read_json_with_retry(tmp_path / "nope.json", retries=2, delay=0.001) is None


def test_corrupt_file_returns_none_instead_of_raising(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"half": ')
    assert read_json_with_retry(p, retries=2, delay=0.001) is None


def test_retry_recovers_when_writer_finishes_mid_read(tmp_path):
    p = tmp_path / "late.json"
    p.write_text('{"half": ')
    threading.Timer(0.02, lambda: write_json_atomic(p, {"ok": True})).start()
    assert read_json_with_retry(p, retries=50, delay=0.005) == {"ok": True}


def _hammer(path, stop_at):
    payload = {"data": {str(i): i for i in range(2000)}}   # large -> non-trivial write
    n = 0
    while time.time() < stop_at:
        payload["n"] = n
        write_json_atomic(path, payload)
        n += 1


def test_concurrent_reader_never_sees_partial_json(tmp_path):
    """A separate PROCESS rewrites the file continuously while this process
    reads it thousands of times. Every read must be complete, valid JSON."""
    p = str(tmp_path / "live.json")
    write_json_atomic(p, {"data": {}, "n": -1})
    stop_at = time.time() + 1.0
    proc = mp.Process(target=_hammer, args=(p, stop_at))
    proc.start()
    reads = bad = 0
    while time.time() < stop_at:
        try:
            with open(p) as f:
                doc = json.load(f)          # NO retry: raw read must still be valid
            assert "n" in doc
            reads += 1
        except (json.JSONDecodeError, FileNotFoundError):
            bad += 1
    proc.join()
    assert reads > 100
    assert bad == 0
