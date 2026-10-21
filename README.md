# eBPF-Based Granular Energy Profiler for Green Cloud Computing

**Course:** BCSE307 (Compiler Design / Systems) — VIT University
**Team ID:** A27
**Members:**
| Name | Reg No. | Module |
|---|---|---|
| Pranjal Sharma | 24BAI0113 | Module 1 — eBPF Kernel Probe |
| Kalparun Sarkar | 24BCE2162 | Module 2 — RAPL Hardware Reader |
| Aryan Gupta | 24BCE2311 | Module 3 — Attribution Engine |
| Chirag Goyal | 24BCE2982 | Integration, CLI, Testing & Deployment |

## What this is

A zero-instrumentation energy profiler that attributes real-time CPU energy
consumption (in Joules) to individual processes/microservices on a single
Linux host, by correlating nanosecond-precision eBPF scheduling data
(`sched_switch`) with node-level Intel RAPL power metrics. See
[`docs/architecture.md`](docs/architecture.md) for the full data-flow design,
[`docs/Review2_Progress_Document.docx`](docs/Review2_Progress_Document.docx)
for the Review 2 submission writeup, and
[`PROJECT_EXPLAINED.md`](PROJECT_EXPLAINED.md) (also as
[`docs/PROJECT_EXPLAINED.pdf`](docs/PROJECT_EXPLAINED.pdf)) for a
plain-language walkthrough of what was required, what was built, and how.

## Repository layout

```
src/
  module1_ebpf_probe/       Kernel probe: sched_switch tracepoint (C) + BCC loader (Python)
  module2_rapl_reader/      RAPL sysfs reader, wraparound-aware Joule delta calc
  module3_attribution_engine/  Pure proportional-attribution logic (no I/O, fully unit-tested)
  cli/                      energy_profiler.py — integrates all three modules end-to-end
tests/                      pytest unit + integration tests (30 tests)
docs/                       architecture notes + Review 2 progress document
scripts/                    preflight, real demo, stress test, overhead benchmark, final check
evidence/                   outputs of the above (generated)
```

## Quick start (copy-paste)

```bash
# 0) one-time install (Ubuntu/Debian) -- real mode only; simulation needs only python3 + pytest
sudo apt update
sudo apt install -y python3-pytest bpfcc-tools python3-bpfcc linux-headers-$(uname -r) stress-ng

# 1) tests + simulation (any OS, no root)            -> evidence/final_check_output.txt
bash scripts/final_check.sh

# 2) can this machine run the real thing?            -> evidence/preflight.txt
sudo bash scripts/preflight.sh

# 3) real mode (eBPF + RAPL), 30 s                    -> evidence/real_run_*.{txt,json}
sudo bash scripts/run_real_demo.sh 30
#    or directly:  sudo python3 -m src.cli.energy_profiler --duration 30 --interval 1

# 4) stress-ng validation (idle baseline + load)      -> evidence/stress_*
sudo bash scripts/run_stress_test.sh 30 2

# 5) probe overhead benchmark                         -> evidence/overhead_report.json
sudo python3 scripts/measure_overhead.py
```
Use the **system** `python3` for real mode (BCC is installed by apt, not pip, so it is not visible inside a venv).
On Windows/macOS only the simulation is possible: `python -m src.cli.energy_profiler --duration 10 --interval 1 --simulate --seed 42`.

CLI options: `--group-by tgid|tid` (default tgid = threads merged into their process), `--handoff-file F`
(probe data goes through an atomically written JSON file), `--quiet`, `--rapl-dir`, `--out`.
Real mode needs **root** (eBPF, and `energy_uj` is root-only on Linux >= 5.10) and a CPU/VM that exposes
`/sys/class/powercap/intel-rapl:0`.

## What was added for the final review
| Review-2 gap | What is in the repo now |
|---|---|
| Real-mode run | `scripts/preflight.sh`, `scripts/run_real_demo.sh`; one synchronised sampling loop (probe + RAPL read at the same instant), running slices counted, idle task excluded, dead PIDs pruned, clear errors for missing RAPL/BCC/root |
| Stress test | `scripts/run_stress_test.sh` (+ idle baseline) and `scripts/analyze_stress_report.py` (PASS/FAIL checks) |
| JSON hand-off race | `src/common/atomic_json.py` (tmp file + `os.replace`, retrying reader); 6 tests incl. a cross-process hammer test |
| Overhead evidence | `scripts/measure_overhead.py` (baseline vs profiler, interleaved rounds, SE, honest verdict) |
| Repeatable validation | `docs/VALIDATION.md` |
| Tests | **30 tests** (was 20): +5 atomic-JSON, +4 integration (PID exit, idle window, RAPL gap, handoff, missing RAPL) |

> Honest status: tests and the simulation were executed and pass. The real-hardware, stress and overhead runs
> must be executed by you on your Ubuntu machine (this repo contains the tools and procedure, not fabricated numbers).

## Running the tests

```bash
python3 -m pytest tests/ -v      # 30 tests
```
`test_integration.py` exercises the real-mode code path with a fake sysfs RAPL directory and a scripted probe.
The C eBPF program itself can only be validated on a Linux kernel (manual check in `docs/VALIDATION.md`).

## Design deviations from Review 1

- **Daemon language:** Review 1 specified a C++ daemon; we implemented
  Modules 2–4 in Python (using BCC's Python bindings to load the C eBPF
  program for Module 1) to maximize iteration speed within the review
  timeline. The kernel-space probe remains C as planned — this is where
  overhead actually matters. Justification and full detail in the progress
  document.
