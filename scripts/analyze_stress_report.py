#!/usr/bin/env python3
"""Checks a stress-ng profiler report. Prints PASS/FAIL/INFO lines.

  1. stress-ng processes were tracked at all
  2. their combined energy share is dominant (default >= 80 %)
  3. measured CPU utilisation ~ cores/ncpu that stress-ng should consume
  4. sum(attributed J) == raw RAPL J (bookkeeping conservation, < 0.01 %)
  5. average package power under load vs idle baseline (INFO; shows the
     RAPL signal really responds to the workload)
External power-meter comparison is NOT done here: record it manually if you
have a meter, otherwise state it as a limitation in the report."""
import argparse
import json
import sys


def avg_watts(rep):
    rows = rep["per_window"]
    j = sum(r["raw_rapl_joules"] for r in rows)
    t = sum(r["dt_s"] for r in rows)
    return j / t if t else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--idle")
    ap.add_argument("--cores", type=int, default=2)
    ap.add_argument("--process-prefix", default="stress-ng")
    ap.add_argument("--min-share", type=float, default=80.0)
    a = ap.parse_args()
    rep = json.load(open(a.report))
    ok = True

    by_name = rep["totals_joules_by_name"]
    total = sum(by_name.values())
    mine = {n: j for n, j in by_name.items() if n.startswith(a.process_prefix)}
    share = 100 * sum(mine.values()) / total if total else 0.0
    print(f"Energy by process name (top 8):")
    for n, j in sorted(by_name.items(), key=lambda kv: -kv[1])[:8]:
        print(f"   {n:<20} {j:10.3f} J  {100 * j / total if total else 0:5.1f} %")

    def line(passed, text):
        nonlocal ok
        ok &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] {text}")

    line(bool(mine), f"'{a.process_prefix}*' processes were tracked ({', '.join(mine) or 'none'})")
    line(share >= a.min_share, f"{a.process_prefix} share of attributed energy = {share:.1f} % (>= {a.min_share} %)")

    ncpu = rep["config"]["cpus"]
    exp = 100 * a.cores / ncpu
    util = 100 * sum(r["cpu_utilisation"] for r in rep["per_window"]) / max(1, len(rep["per_window"]))
    line(abs(util - exp) <= 15 or util >= exp, f"mean CPU utilisation {util:.1f} % vs expected ~{exp:.1f} % ({a.cores}/{ncpu} CPUs)")

    err = rep["validation"]["conservation_error_percent"]
    line(err < 0.01, f"sum attributed J ({rep['validation']['attributed_joules']:.3f}) vs raw RAPL J "
                     f"({rep['validation']['raw_rapl_joules_active_windows']:.3f}): diff {err:.6f} %")

    w_load = avg_watts(rep)
    print(f"[INFO] average package power under load: {w_load:.2f} W")
    if a.idle:
        w_idle = avg_watts(json.load(open(a.idle)))
        print(f"[INFO] average package power idle      : {w_idle:.2f} W")
        print(f"[INFO] load - idle                     : {w_load - w_idle:+.2f} W "
              f"({'RAPL responds to workload' if w_load > w_idle else 'WARNING: no increase seen'})")
    print("[INFO] external power meter: not measured here (record manually or document as a limitation)")
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
