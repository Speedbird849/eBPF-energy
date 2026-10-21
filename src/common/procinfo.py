"""procinfo.py — small /proc helpers (thread -> process, process name)."""
from __future__ import annotations

import os


def process_name(pid: int) -> str:
    for path in (f"/proc/{pid}/comm",):
        try:
            with open(path) as f:
                return f.read().strip()
        except OSError:
            pass
    return f"pid-{pid}"


def pid_alive(pid: int) -> bool:
    return os.path.exists(f"/proc/{pid}")


class TgidResolver:
    """Maps a thread id (what sched_switch reports) to its process id (TGID).

    Results are cached. A thread that has already exited cannot be resolved
    and is reported under its own id (it is then shown as its own row)."""

    def __init__(self) -> None:
        self._cache: dict[int, int] = {}
        self._names: dict[int, str] = {}

    def tgid(self, tid: int) -> int:
        hit = self._cache.get(tid)
        if hit is not None:
            return hit
        tgid = tid
        try:
            with open(f"/proc/{tid}/status") as f:
                for line in f:
                    if line.startswith("Tgid:"):
                        tgid = int(line.split()[1])
                        break
            self._cache[tid] = tgid          # only cache successful lookups
        except (OSError, ValueError):
            pass
        return tgid

    def name(self, pid: int) -> str:
        n = process_name(pid)
        if n.startswith("pid-"):
            return self._names.get(pid, n)   # remember last known name of dead PIDs
        self._names[pid] = n
        return n

    def aggregate(self, by_tid: dict[int, int]) -> dict[int, int]:
        out: dict[int, int] = {}
        for tid, ns in by_tid.items():
            t = self.tgid(tid)
            out[t] = out.get(t, 0) + ns
        return out
