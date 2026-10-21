"""
sched_probe.py — Module 1 user-space loader (Owner: Pranjal Sharma)

Loads sched_probe.bpf.c via BCC, polls the `cpu_ns` BPF hash map at a fixed
interval, and yields a per-PID nanosecond delta since the previous poll
("windowed" CPU time). This windowed delta is what Module 3 (Attribution
Engine) combines with Module 2's per-window Joule readings.

Modes:
  --simulate   Pure-Python synthetic scheduler model. Runs on any OS with no
               root/kernel/BCC dependency.
  (default)    Real eBPF path. Requires Linux >= 5.8, BCC installed, root.

Extras added for final review:
  * running slices are included: a task that is ON the CPU when we poll (e.g.
    a CPU hog that was never preempted) has its in-progress slice added, so
    it is not under-reported.
  * dead PIDs are pruned from the BPF map after their last delta is read.
  * --export-json PATH writes every window to a JSON file ATOMICALLY
    (temp file + os.replace) so a concurrent reader never sees partial JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field

try:                                    # package import (python -m src....)
    from src.common.atomic_json import write_json_atomic
    from src.common.procinfo import pid_alive
except ImportError:                     # direct script execution
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from src.common.atomic_json import write_json_atomic
    from src.common.procinfo import pid_alive


@dataclass
class ProbeWindow:
    """Pure logic for turning cumulative BPF-map counters into per-window
    deltas. Kept separate from BCC I/O so it can be unit-tested without a
    kernel."""

    _last: dict[int, int] = field(default_factory=dict)

    def delta(self, cumulative_by_pid: dict[int, int]) -> dict[int, int]:
        """Given the latest cumulative cpu_ns snapshot, return the ns each
        PID accrued since the previous call. New PIDs get their full
        cumulative value; PIDs absent from a later snapshot are dropped.
        A counter that appears to go backwards (benign read race between the
        two BPF maps) yields no delta and is NOT allowed to lower the
        baseline, so nothing is double counted in the following window."""
        out: dict[int, int] = {}
        new_last: dict[int, int] = {}
        for pid, cumulative in cumulative_by_pid.items():
            prev = self._last.get(pid, 0)
            d = cumulative - prev
            if d > 0:
                out[pid] = d
            new_last[pid] = max(cumulative, prev)
        self._last = new_last
        return out


BPF_SOURCE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sched_probe.bpf.c")


class EbpfProbe:
    """Live eBPF probe. `sample()` returns {tid: ns on-CPU since last sample}."""

    def __init__(self, source_path: str = BPF_SOURCE_PATH):
        try:
            from bcc import BPF  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "python 'bcc' module not found. Install with: "
                "sudo apt install bpfcc-tools python3-bpfcc linux-headers-$(uname -r)  "
                "(run with system python3, not inside a venv)"
            ) from exc
        with open(source_path) as f:
            source = f.read()
        self.bpf = BPF(text=source)     # needs root + kernel headers
        self.window = ProbeWindow()
        self.attach_errors = 0

    def cumulative(self) -> dict[int, int]:
        cpu_table = self.bpf["cpu_ns"]
        # read finished slices first, then in-progress ones (see module docstring)
        cumulative = {k.value: v.value for k, v in cpu_table.items()}
        now = time.monotonic_ns()       # same clock as bpf_ktime_get_ns()
        for k, v in self.bpf["start_ns"].items():
            running = now - v.value
            if running > 0:
                cumulative[k.value] = cumulative.get(k.value, 0) + running
        return cumulative

    def sample(self) -> dict[int, int]:
        cum = self.cumulative()
        deltas = self.window.delta(cum)
        self._prune_dead(cum)
        return deltas

    def _prune_dead(self, cum: dict[int, int]) -> None:
        table = self.bpf["cpu_ns"]
        for tid in list(cum):
            if not pid_alive(tid):
                try:
                    del table[table.Key(tid)]
                except (KeyError, Exception):
                    pass

    def close(self) -> None:
        try:
            self.bpf.cleanup()
        except Exception:
            pass


class SimulatedProbe:
    """Synthetic scheduler: a fixed pool of fake PIDs each 'run' for a random
    share of every window. Deterministic when `seed` is given."""

    FAKE_PIDS = [1001, 1002, 1003, 1004]

    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def sample(self, interval: float = 1.0) -> dict[int, int]:
        window_ns = int(interval * 1_000_000_000)
        weights = [self._rng.random() + 0.05 for _ in self.FAKE_PIDS]
        total_w = sum(weights)
        return {pid: int(window_ns * w / total_w) for pid, w in zip(self.FAKE_PIDS, weights)}

    def close(self) -> None:
        pass


def _export(path: str | None, index: int, deltas: dict[int, int]) -> None:
    if path:
        write_json_atomic(path, {"type": "cpu_ns_window", "window": index,
                                 "ts": time.time(), "data": {str(k): v for k, v in deltas.items()}})


def run_real(interval: float, duration: float, export_json: str | None = None):
    probe = EbpfProbe()
    try:
        probe.sample()                  # discard: establishes baseline at t0
        start = time.monotonic()
        i = 0
        while time.monotonic() - start < duration:
            time.sleep(interval)
            i += 1
            deltas = probe.sample()
            _export(export_json, i, deltas)
            yield deltas
    finally:
        probe.close()


def run_simulated(interval: float, duration: float, seed: int | None = None,
                  export_json: str | None = None):
    probe = SimulatedProbe(seed)
    elapsed = 0.0
    i = 0
    while elapsed < duration:
        time.sleep(min(interval, 0.05))  # keep demo/test runs fast
        elapsed += interval
        i += 1
        deltas = probe.sample(interval)
        _export(export_json, i, deltas)
        yield deltas


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interval", type=float, default=1.0, help="Poll interval (s)")
    parser.add_argument("--duration", type=float, default=5.0, help="Total run time (s)")
    parser.add_argument("--simulate", action="store_true", help="Run without eBPF/root")
    parser.add_argument("--seed", type=int, default=None, help="Simulation RNG seed")
    parser.add_argument("--export-json", default=None,
                        help="Atomically (re)write each window to this JSON file")
    args = parser.parse_args()

    gen = (
        run_simulated(args.interval, args.duration, args.seed, args.export_json)
        if args.simulate
        else run_real(args.interval, args.duration, args.export_json)
    )

    for window_deltas in gen:
        print(json.dumps({"type": "cpu_ns_window", "data": window_deltas}))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
