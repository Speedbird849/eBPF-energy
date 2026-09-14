"""
sched_probe.py — Module 1 user-space loader (Owner: Pranjal Sharma)

Loads sched_probe.bpf.c via BCC, polls the `cpu_ns` BPF hash map at a fixed
interval, and yields a per-PID nanosecond delta since the previous poll
("windowed" CPU time). This windowed delta is what Module 3 (Attribution
Engine) combines with Module 2's per-window Joule readings.

Two modes:
  --simulate   Pure-Python synthetic scheduler model. Runs on any OS with no
               root/kernel/BCC dependency. Used for Review 2 CI-style testing
               and for demonstrating the full pipeline on non-Linux dev
               machines. NOT a substitute for the real probe — the real path
               below is unit-testable in isolation but only runs on Linux.
  (default)    Real eBPF path. Requires Linux >= 5.8, BCC installed, root.

Unit validation performed for Review 2 (see tests/test_probe_window.py):
  - windowing logic (delta-since-last-poll) is pure Python and tested
    directly, independent of whether BCC/eBPF is available.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass, field


@dataclass
class ProbeWindow:
    """Pure logic for turning cumulative BPF-map counters into per-window
    deltas. Kept separate from BCC I/O so it can be unit-tested without a
    kernel."""

    _last: dict[int, int] = field(default_factory=dict)

    def delta(self, cumulative_by_pid: dict[int, int]) -> dict[int, int]:
        """Given the latest cumulative cpu_ns snapshot, return the ns each
        PID accrued since the previous call. Handles PIDs that appear for
        the first time (delta = full cumulative value) and PIDs that exit
        and are absent from a later snapshot (dropped, not carried forward).
        """
        out: dict[int, int] = {}
        for pid, cumulative in cumulative_by_pid.items():
            prev = self._last.get(pid, 0)
            d = cumulative - prev
            if d > 0:
                out[pid] = d
        self._last = dict(cumulative_by_pid)
        return out


def _load_real_bpf():
    """Compile and attach the real eBPF program via BCC. Linux-only."""
    from bcc import BPF  # type: ignore

    with open(
        __file__.replace("sched_probe.py", "sched_probe.bpf.c"), "r"
    ) as f:
        source = f.read()
    return BPF(text=source)


def run_real(interval: float, duration: float):
    bpf = _load_real_bpf()
    window = ProbeWindow()
    elapsed = 0.0
    while elapsed < duration:
        time.sleep(interval)
        elapsed += interval
        table = bpf["cpu_ns"]
        cumulative = {k.value: v.value for k, v in table.items()}
        yield window.delta(cumulative)


def run_simulated(interval: float, duration: float, seed: int | None = None):
    """Synthetic scheduler: a fixed pool of fake PIDs each "run" for a random
    share of every window, mimicking sched_switch accounting without a
    kernel. Deterministic when `seed` is given (used by tests/demo)."""
    rng = random.Random(seed)
    fake_pids = [1001, 1002, 1003, 1004]
    elapsed = 0.0
    while elapsed < duration:
        time.sleep(min(interval, 0.05))  # keep demo/test runs fast
        elapsed += interval
        window_ns = int(interval * 1_000_000_000)
        weights = [rng.random() + 0.05 for _ in fake_pids]
        total_w = sum(weights)
        deltas = {
            pid: int(window_ns * w / total_w)
            for pid, w in zip(fake_pids, weights)
        }
        yield deltas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=1.0, help="Poll interval (s)")
    parser.add_argument("--duration", type=float, default=5.0, help="Total run time (s)")
    parser.add_argument("--simulate", action="store_true", help="Run without eBPF/root")
    parser.add_argument("--seed", type=int, default=None, help="Simulation RNG seed")
    args = parser.parse_args()

    gen = (
        run_simulated(args.interval, args.duration, args.seed)
        if args.simulate
        else run_real(args.interval, args.duration)
    )

    for window_deltas in gen:
        print(json.dumps({"type": "cpu_ns_window", "data": window_deltas}))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
