"""
energy_profiler.py — Integration CLI (Owner: Chirag Goyal)

End-to-end integration of Module 1 (eBPF kernel probe), Module 2 (RAPL
reader) and Module 3 (attribution engine) into a single runnable tool. This
is the "integrated prototype showing meaningful end-to-end execution"
required for Review 2.

Usage:
    python -m src.cli.energy_profiler --duration 10 --interval 1 --simulate

    (drop --simulate on a Linux host with BCC + RAPL + root for the real
    pipeline; see README.md "Running on real hardware")

Each window: pulls one CPU-time delta snapshot from Module 1, one Joule
reading from Module 2, feeds both into Module 3, prints a live per-PID
table, and — at the end of the run — a run-total table plus a JSON report
written to the --out path for the test-evidence / repository record.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.module1_ebpf_probe.sched_probe import ProbeWindow, run_real as probe_run_real, run_simulated as probe_run_simulated
from src.module2_rapl_reader.rapl_reader import run_real as rapl_run_real, run_simulated as rapl_run_simulated
from src.module3_attribution_engine.attribution import attribute_energy, merge_windows

# Optional: resolve PID -> process name for a friendlier table. Falls back
# gracefully when /proc is unavailable (non-Linux, or simulated fake PIDs).
def _process_name(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return f"pid-{pid}"


def _print_window(index: int, results: dict) -> None:
    print(f"\n--- Window {index} ---")
    if not results:
        print("  (no scheduled activity this window)")
        return
    print(f"{'PID':>8}  {'NAME':<16}  {'CPU SHARE':>10}  {'JOULES':>10}")
    for pid, r in sorted(results.items(), key=lambda kv: -kv[1].joules):
        print(f"{pid:>8}  {_process_name(pid):<16}  {r.cpu_share * 100:>9.1f}%  {r.joules:>10.4f}")


def run(duration: float, interval: float, simulate: bool, seed: int | None, out_path: Path) -> dict:
    probe_gen = (
        probe_run_simulated(interval, duration, seed)
        if simulate
        else probe_run_real(interval, duration)
    )
    rapl_gen = (
        rapl_run_simulated(interval, duration, seed=seed)
        if simulate
        else rapl_run_real(interval, duration)
    )

    history = []
    for i, (cpu_ns_window, joules) in enumerate(zip(probe_gen, rapl_gen), start=1):
        if joules is None:
            continue  # first RAPL sample has no baseline yet
        window_result = attribute_energy(cpu_ns_window, joules)
        history.append(window_result)
        _print_window(i, window_result)

    totals = merge_windows(history)
    print("\n=== Run Totals ===")
    print(f"{'PID':>8}  {'NAME':<16}  {'TOTAL JOULES':>12}")
    for pid, joules in sorted(totals.items(), key=lambda kv: -kv[1]):
        print(f"{pid:>8}  {_process_name(pid):<16}  {joules:>12.4f}")

    report = {
        "config": {"duration": duration, "interval": interval, "simulate": simulate, "seed": seed},
        "windows": len(history),
        "totals_joules": totals,
    }
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nReport written to {out_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out", type=Path, default=Path("energy_report.json"))
    args = parser.parse_args()

    if not args.simulate and sys.platform != "linux":
        print(
            "Real eBPF/RAPL mode requires Linux with BCC + root + RAPL sysfs. "
            "Use --simulate on this platform, or run inside the project VM "
            "(see README.md).",
            file=sys.stderr,
        )
        sys.exit(1)

    run(args.duration, args.interval, args.simulate, args.seed, args.out)


if __name__ == "__main__":
    main()
