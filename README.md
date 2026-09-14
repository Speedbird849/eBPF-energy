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
tests/                      pytest unit tests (20 tests, all passing — see below)
docs/                       architecture notes + Review 2 progress document
scripts/                    stress-test helper for real-hardware validation
```

## Running the prototype

### Simulated mode (works on any OS — Windows, macOS, Linux; no root, no RAPL, no eBPF)

This mode exercises the *entire* pipeline (windowing, wraparound handling,
proportional attribution, CLI reporting) with synthetic scheduler/power data
so the integration can be demonstrated and tested without special hardware.

```bash
python -m src.cli.energy_profiler --duration 10 --interval 1 --simulate --seed 42
```

Prints a live per-window per-PID table plus run totals, and writes
`energy_report.json`.

### Real mode (Linux >= 5.8, BCC installed, root, Intel/AMD RAPL-capable CPU)

```bash
sudo python3 -m src.cli.energy_profiler --duration 30 --interval 1
```

Requires:
```bash
sudo apt install bpfcc-tools python3-bpfcc   # Debian/Ubuntu
```
Runs the actual `sched_probe.bpf.c` eBPF program (via `bcc`) against the live
kernel scheduler and reads `/sys/class/powercap/intel-rapl:0/energy_uj`.

### Stress-test validation (real hardware)

```bash
bash scripts/run_stress_test.sh
```
Drives `stress-ng` while the profiler runs, so attributed Joules for the
stress workload's PID can be sanity-checked against the RAPL delta and
external power-meter baseline (Review 1 testing strategy).

## Running the tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Current status: **20/20 tests passing.** Coverage:
- `test_attribution.py` (10 tests) — proportional split correctness, zero/negative
  edge cases, multi-window aggregation.
- `test_rapl_reader.py` (5 tests) — Joule delta calc, RAPL counter wraparound,
  missing-metadata fallback, against a fake sysfs fixture.
- `test_probe_window.py` (5 tests) — cumulative-to-delta windowing, PID
  appear/exit handling.

Module 1's C eBPF program (`sched_probe.bpf.c`) cannot be unit-tested off a
Linux kernel; it is validated via live demonstration on the target VM
(see Review 1 Stage 2 plan and the Review 2 progress document's testing
section for current status).

## Design deviations from Review 1

- **Daemon language:** Review 1 specified a C++ daemon; we implemented
  Modules 2–4 in Python (using BCC's Python bindings to load the C eBPF
  program for Module 1) to maximize iteration speed within the review
  timeline. The kernel-space probe remains C as planned — this is where
  overhead actually matters. Justification and full detail in the progress
  document.
