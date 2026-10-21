"""
energy_profiler.py — Integration CLI (Owner: Chirag Goyal)

End-to-end integration of Module 1 (eBPF kernel probe), Module 2 (RAPL
reader) and Module 3 (attribution engine).

Usage:
    python3 -m src.cli.energy_profiler --duration 10 --interval 1 --simulate
    sudo python3 -m src.cli.energy_profiler --duration 30 --interval 1      # real

Key design points (final-review version):
  * ONE sampling loop: sleep once per window, then read the probe and RAPL
    back-to-back, so both cover the same wall-clock window.
  * Windows where RAPL gives no reading are not lost: the probe's CPU time is
    carried over and merged into the next window that has a reading.
  * Threads are aggregated into their process (--group-by tgid, default).
  * Report holds per-window raw RAPL Joules, attributed Joules, utilisation
    and a conservation check, plus totals per PID and per process name.
  * --handoff-file: probe -> JSON file -> CLI path (atomic write + retry read).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.atomic_json import read_json_with_retry, write_json_atomic
from src.common.procinfo import TgidResolver
from src.module1_ebpf_probe.sched_probe import EbpfProbe, SimulatedProbe
from src.module2_rapl_reader.rapl_reader import (
    RAPL_BASE, RaplReader, RaplUnavailable, SimulatedRapl, check_rapl,
)
from src.module3_attribution_engine.attribution import attribute_energy, merge_windows


def _print_window(index: int, results: dict, resolver: TgidResolver, joules: float,
                  dt: float, util: float) -> None:
    watts = joules / dt if dt > 0 else 0.0
    print(f"\n--- Window {index}: {joules:.4f} J over {dt:.2f}s ({watts:.1f} W), "
          f"CPU utilisation {util * 100:.1f}% ---")
    if not results:
        print("  (no scheduled activity this window)")
        return
    print(f"{'PID':>8}  {'NAME':<16}  {'CPU SHARE':>10}  {'JOULES':>10}")
    for pid, r in sorted(results.items(), key=lambda kv: -kv[1].joules)[:15]:
        print(f"{pid:>8}  {resolver.name(pid):<16}  {r.cpu_share * 100:>9.1f}%  {r.joules:>10.4f}")


def _merge_ns(a: dict[int, int], b: dict[int, int]) -> dict[int, int]:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return out


def run(duration: float, interval: float, simulate: bool, seed: int | None, out_path: Path,
        group_by: str = "tgid", rapl_dir: str = RAPL_BASE, handoff_file: str | None = None,
        quiet: bool = False, ready_file: str | None = None) -> dict:
    ncpu = os.cpu_count() or 1
    resolver = TgidResolver()

    if simulate:
        probe, rapl = SimulatedProbe(seed), SimulatedRapl(seed=seed)
    else:
        ok, msg = check_rapl(rapl_dir)
        if not ok:
            raise RaplUnavailable(msg)
        rapl = RaplReader(rapl_dir)
        probe = EbpfProbe()

    history, rows = [], []
    pending_ns: dict[int, int] = {}
    skipped = 0
    handoff_misses = 0
    try:
        # baseline: discard everything accumulated before t0
        if simulate:
            t_prev = time.monotonic()
        else:
            probe.sample()
            rapl.poll()
            t_prev = time.monotonic()
        t0 = t_prev
        if ready_file:                    # lets scripts know the probe is attached
            Path(ready_file).write_text(str(os.getpid()))
        index = 0
        # simulate mode runs fast, so it counts windows instead of wall time
        while (index * interval < duration) if simulate else (time.monotonic() - t0 < duration):
            time.sleep(min(interval, 0.05) if simulate else interval)
            index += 1
            now = time.monotonic()
            dt = interval if simulate else now - t_prev
            t_prev = now

            cpu_ns = probe.sample(interval) if simulate else probe.sample()

            if handoff_file:   # exercise the atomic JSON handoff path
                write_json_atomic(handoff_file, {"window": index, "data": {str(k): v for k, v in cpu_ns.items()}})
                doc = read_json_with_retry(handoff_file)
                if doc is None or doc.get("window") != index:
                    handoff_misses += 1          # skip-on-error: never crash
                    pending_ns = _merge_ns(pending_ns, cpu_ns)
                    continue
                cpu_ns = {int(k): v for k, v in doc["data"].items()}

            joules = rapl.poll(interval) if simulate else rapl.poll()
            if joules is None:
                skipped += 1                       # RAPL unavailable this window
                pending_ns = _merge_ns(pending_ns, cpu_ns)
                continue

            cpu_ns = _merge_ns(pending_ns, cpu_ns)
            pending_ns = {}
            if group_by == "tgid" and not simulate:
                cpu_ns = resolver.aggregate(cpu_ns)

            result = attribute_energy(cpu_ns, joules)
            history.append(result)
            active_ns = sum(cpu_ns.values())
            util = min(1.0, active_ns / (dt * 1e9 * ncpu)) if dt > 0 else 0.0
            attributed = sum(r.joules for r in result.values())
            rows.append({
                "window": index, "dt_s": round(dt, 4), "raw_rapl_joules": joules,
                "attributed_joules": attributed, "active_cpu_ns": active_ns,
                "cpu_utilisation": util,
                "per_pid": {str(p): {"name": resolver.name(p), "cpu_ns": r.cpu_ns,
                                     "cpu_share": r.cpu_share, "joules": r.joules}
                            for p, r in result.items()},
            })
            if not quiet:
                _print_window(index, result, resolver, joules, dt, util)
    finally:
        probe.close()

    totals = merge_windows(history)
    by_name: dict[str, float] = {}
    for pid, j in totals.items():
        by_name[resolver.name(pid)] = by_name.get(resolver.name(pid), 0.0) + j

    raw_sum = sum(r["raw_rapl_joules"] for r in rows)
    attr_sum = sum(r["attributed_joules"] for r in rows)
    active_rows = [r for r in rows if r["per_pid"]]
    raw_active = sum(r["raw_rapl_joules"] for r in active_rows)
    attr_active = sum(r["attributed_joules"] for r in active_rows)
    err = abs(raw_active - attr_active) / raw_active * 100 if raw_active else 0.0

    if not quiet:
        print("\n=== Run Totals (per PID) ===")
        print(f"{'PID':>8}  {'NAME':<16}  {'TOTAL JOULES':>12}")
        for pid, j in sorted(totals.items(), key=lambda kv: -kv[1])[:20]:
            print(f"{pid:>8}  {resolver.name(pid):<16}  {j:>12.4f}")
        print("\n=== Consistency check ===")
        print(f"  windows used            : {len(rows)}  (RAPL-skipped: {skipped}, handoff-skipped: {handoff_misses})")
        print(f"  raw RAPL energy (active): {raw_active:.4f} J")
        print(f"  sum attributed energy   : {attr_active:.4f} J   (difference {err:.6f}%)")
        print(f"  raw RAPL energy (all)   : {raw_sum:.4f} J  (idle windows are attributed to nobody)")

    report = {
        "config": {"duration": duration, "interval": interval, "simulate": simulate, "seed": seed,
                   "group_by": group_by, "cpus": ncpu, "rapl_dir": None if simulate else rapl_dir},
        "windows": len(history),
        "skipped_rapl_windows": skipped,
        "skipped_handoff_windows": handoff_misses,
        "totals_joules": {str(k): v for k, v in totals.items()},
        "totals_joules_by_name": by_name,
        "validation": {"raw_rapl_joules_all": raw_sum, "raw_rapl_joules_active_windows": raw_active,
                       "attributed_joules": attr_active, "conservation_error_percent": err,
                       "note": "Attribution redistributes the measured package energy, so the sum "
                               "matches RAPL by construction; it validates the pipeline's bookkeeping, "
                               "not per-process physical accuracy."},
        "per_window": rows,
    }
    write_json_atomic(out_path, report, indent=2)
    if not quiet:
        print(f"\nReport written to {out_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out", type=Path, default=Path("energy_report.json"))
    parser.add_argument("--group-by", choices=["tgid", "tid"], default="tgid")
    parser.add_argument("--rapl-dir", default=RAPL_BASE)
    parser.add_argument("--handoff-file", default=None,
                        help="route probe data through this JSON file (atomic write + retrying read)")
    parser.add_argument("--quiet", action="store_true", help="no per-window table (report still written)")
    parser.add_argument("--ready-file", default=None, help="touch this file once the probe is attached")
    args = parser.parse_args()

    if not args.simulate and sys.platform != "linux":
        print("Real eBPF/RAPL mode requires Linux. Use --simulate on this platform.", file=sys.stderr)
        sys.exit(1)
    if not args.simulate and hasattr(os, "geteuid") and os.geteuid() != 0:
        print("Real mode needs root (eBPF + RAPL energy_uj). Re-run with sudo.", file=sys.stderr)
        sys.exit(1)

    try:
        run(args.duration, args.interval, args.simulate, args.seed, args.out,
            args.group_by, args.rapl_dir, args.handoff_file, args.quiet, args.ready_file)
    except (RaplUnavailable, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
