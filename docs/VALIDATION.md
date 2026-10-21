# Repeatable validation procedure (real hardware)

Everything below is run on the **target Ubuntu machine** (bare metal, or a VM that exposes
RAPL). The sandbox where the code was finalised had no RAPL/eBPF, so *no real-hardware numbers
are included in this repository* — the scripts below produce them, and save them in `evidence/`.

| # | Step | Command | Evidence file(s) |
|---|------|---------|------------------|
| 0 | Install | `sudo apt install bpfcc-tools python3-bpfcc linux-headers-$(uname -r) stress-ng` | – |
| 1 | Environment check | `sudo bash scripts/preflight.sh` | `evidence/preflight.txt` |
| 2 | Unit + integration tests, simulation | `bash scripts/final_check.sh` | `evidence/final_check_output.txt` |
| 3 | Real-mode run (eBPF + RAPL + JSON hand-off) | `sudo bash scripts/run_real_demo.sh 30` | `evidence/real_run_terminal.txt`, `evidence/real_run_report.json` |
| 4 | Stress test + checks | `sudo bash scripts/run_stress_test.sh 30 2` | `evidence/stress_*.txt/json`, `evidence/idle_report.json` |
| 5 | Overhead benchmark | `sudo python3 scripts/measure_overhead.py` | `evidence/overhead_report.json` |
| 6 | Manual probe check (below) | see below | screenshot |

## Manual probe check (shows the eBPF program really sees the scheduler)
Terminal A: `sudo python3 -m src.module1_ebpf_probe.sched_probe --duration 10`
Terminal B: `yes > /dev/null &  echo $!` (note the PID, `kill` it afterwards)
**Expected:** each printed JSON window contains B's PID with ≈ 1,000,000,000 ns (one fully busy core
per second); idle shells do not appear with large values.
Cross-check: `cat /proc/<PID>/schedstat` — first number is the task's total on-CPU ns; its *increase*
over 10 s should match the probe's sum for that PID within a few %.

## What each check proves / does not prove
* **Conservation** (`sum attributed J == raw RAPL J`): true *by construction* of the formula
  `E_i = T_i / Σ T_j × E_pkg`; it verifies bookkeeping (no window lost, no double count, wraparound OK).
* **Stress share / utilisation**: shows the right PIDs get the right share, and that measured CPU time
  matches what `stress-ng --cpu N` should consume (≈ N / #CPUs).
* **Load vs idle power**: shows RAPL actually responds to the workload.
* **Not proven**: per-process *physical* energy. RAPL measures the whole package; splitting it by CPU time
  is a model (it ignores that different instructions cost different energy, and assigns idle/uncore power
  to active processes). No external power meter was used unless you add one — state this as a limitation.

## Failure modes handled in the combined system
| Situation | Behaviour (tested in `tests/test_integration.py`) |
|-----------|---------------------------------------------------|
| PID exits mid-run | its last delta is counted, entry pruned from the BPF map, no error |
| CPU idle window | nothing scheduled → no attribution, energy counted as "attributed to nobody" |
| RAPL unreadable one window | window skipped, CPU time carried to next window, RAPL baseline kept so no energy is lost |
| RAPL absent / no permission | clear error with fix hint, exit code 2 |
| JSON read during write | atomic `os.replace` writer + retrying reader; skip-on-error, never crashes |
| RAPL counter wraparound | handled via `max_energy_range_uj` |

## Recording results (fill in after your runs)
```
Machine / CPU / kernel : ...
RAPL domain            : intel-rapl:0 (package)
Real run               : PIDs seen = ..., total J = ..., conservation error = ...%
Stress (N cores)       : stress-ng share = ...%, util = ...% (expected ...%), load W = ..., idle W = ...
Overhead               : cpu = ...%, ctxsw = ...%, profiler CPU = ...% of a core  (rounds x runs = ...)
External power meter   : not available / value ...
```
