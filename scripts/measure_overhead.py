#!/usr/bin/env python3
"""
measure_overhead.py — Task 4: baseline-vs-profiler overhead benchmark.

Method (block design, repeated to cancel thermal / frequency drift):
  for round in 1..ROUNDS:
      run RUNS baseline trials of each workload            (profiler OFF)
      start the real profiler, wait until the probe is attached
      run RUNS profiled trials of each workload            (profiler ON)
      stop the profiler
Workloads
  cpu   : fixed amount of pure CPU work in one process (few context switches)
  ctxsw : two processes ping-pong over pipes (context-switch heavy = WORST case
          for a sched_switch probe, since cost is per event)
Overhead % = (mean_profiled - mean_baseline) / mean_baseline * 100, reported with
the standard error. The profiler's own CPU time is reported as well.
We do NOT claim the <1 % target is met unless the numbers say so: the verdict line
compares the mean overhead AND its ~95 % upper bound to 1 %.

Run (needs root + working BCC):  sudo python3 scripts/measure_overhead.py
Quick check without root:        python3 scripts/measure_overhead.py --dry-run
"""
import argparse
import json
import math
import os
import signal
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def work_cpu(n=4_000_000):
    t = time.perf_counter()
    s = 0
    for i in range(n):
        s += i * i
    return time.perf_counter() - t


def work_ctxsw(round_trips=60_000):
    r1, w1 = os.pipe()
    r2, w2 = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(w1)          # child must not hold the write end, or EOF never arrives
        os.close(r2)
        try:
            while True:
                b = os.read(r1, 1)
                if not b:
                    break
                os.write(w2, b)
        finally:
            os._exit(0)
    t = time.perf_counter()
    for _ in range(round_trips):
        os.write(w1, b"x")
        os.read(r2, 1)
    dt = time.perf_counter() - t
    os.close(w1)
    os.waitpid(pid, 0)
    for fd in (r1, r2, w2):
        os.close(fd)
    return dt


WORKLOADS = {"cpu": work_cpu, "ctxsw": work_ctxsw}


def start_profiler(dry):
    ready = tempfile.mktemp(prefix="ready-")
    cmd = [sys.executable, "-m", "src.cli.energy_profiler", "--duration", "100000", "--interval", "1",
           "--quiet", "--out", os.path.join(tempfile.gettempdir(), "overhead_profiler_report.json"),
           "--ready-file", ready]
    if dry:
        cmd += ["--simulate"]
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(300):
        if os.path.exists(ready):
            return p
        if p.poll() is not None:
            raise SystemExit("profiler failed to start:\n" + p.stderr.read().decode())
        time.sleep(0.1)
    p.kill()
    raise SystemExit("profiler did not become ready in 30 s")


def cpu_seconds(pid):
    try:
        f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
        return (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")
    except OSError:
        return float("nan")


def stats(xs):
    m = statistics.mean(xs)
    sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return m, sd, sd / math.sqrt(len(xs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--runs", type=int, default=5, help="trials per workload per block")
    ap.add_argument("--workloads", default="cpu,ctxsw")
    ap.add_argument("--out", default=os.path.join(ROOT, "evidence", "overhead_report.json"))
    ap.add_argument("--dry-run", action="store_true", help="use --simulate profiler (tests the harness only)")
    a = ap.parse_args()
    if not a.dry_run and os.geteuid() != 0:
        raise SystemExit("Run with sudo (real eBPF probe needs root), or use --dry-run")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)

    names = a.workloads.split(",")
    res = {n: {"base": [], "prof": []} for n in names}
    prof_cpu = []
    for rd in range(1, a.rounds + 1):
        print(f"== round {rd}/{a.rounds}: baseline block ==", flush=True)
        for n in names:
            res[n]["base"] += [WORKLOADS[n]() for _ in range(a.runs)]
        print(f"== round {rd}/{a.rounds}: profiler block ==", flush=True)
        p = start_profiler(a.dry_run)
        c0, t0 = cpu_seconds(p.pid), time.time()
        for n in names:
            res[n]["prof"] += [WORKLOADS[n]() for _ in range(a.runs)]
        c1, t1 = cpu_seconds(p.pid), time.time()
        prof_cpu.append(100 * (c1 - c0) / (t1 - t0))
        p.send_signal(signal.SIGINT)
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()

    out = {"method": f"{a.rounds} rounds x {a.runs} runs per workload per condition",
           "dry_run": a.dry_run, "workloads": {}, "profiler_own_cpu_percent_of_one_core": prof_cpu}
    print("\nWorkload   baseline (s)        profiled (s)        overhead %   (+2 SE)")
    verdict_ok = True
    for n in names:
        bm, bs, bse = stats(res[n]["base"])
        pm, ps, pse = stats(res[n]["prof"])
        ov = 100 * (pm - bm) / bm
        se = 100 * math.sqrt((pse / bm) ** 2 + (pm * bse / bm ** 2) ** 2)
        upper = ov + 2 * se
        verdict_ok &= upper < 1.0
        print(f"{n:<10} {bm:7.4f} ± {bs:.4f}   {pm:7.4f} ± {ps:.4f}   {ov:+7.3f}     ({upper:+.3f})")
        out["workloads"][n] = {"baseline": res[n]["base"], "profiled": res[n]["prof"],
                               "overhead_percent": ov, "overhead_upper95_percent": upper}
    print(f"\nProfiler user-space CPU use: {statistics.mean(prof_cpu):.2f} % of one core (mean of rounds)")
    print("VERDICT (<1 % target):", "SUPPORTED by these measurements" if verdict_ok else
          "NOT demonstrated: at least one workload's mean+2SE overhead is >= 1 % (report it honestly)")
    if a.dry_run:
        print("(dry-run: simulated profiler => this only tests the harness, NOT eBPF overhead)")
    out["verdict_supported"] = bool(verdict_ok) and not a.dry_run
    with open(a.out, "w") as f:
        json.dump(out, f, indent=2)
    print("saved", a.out)


if __name__ == "__main__":
    main()
