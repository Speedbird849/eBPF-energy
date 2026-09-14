# Architecture — Review 2 Update

## Data flow

```
                    KERNEL SPACE                          USER SPACE
              ┌───────────────────────┐
              │  tracepoint:           │
              │  sched/sched_switch    │
              │                        │
              │  ┌──────────────────┐  │
              │  │ start_ns map      │  │   sched_probe.bpf.c
              │  │ (pid -> ts)       │  │   Module 1 — Pranjal Sharma
              │  │                   │  │
              │  │ cpu_ns map        │  │
              │  │ (pid -> ns)       │  │
              │  └────────┬──────────┘  │
              └───────────┼─────────────┘
                           │ poll (BCC table read)
                           ▼
              ┌────────────────────────┐        ┌───────────────────────────┐
              │  sched_probe.py         │        │  rapl_reader.py            │
              │  ProbeWindow            │        │  RaplReader                │
              │  cumulative -> delta    │        │  /sys/.../energy_uj        │
              │  ns per PID per window  │        │  -> Joules per window      │
              │  (Module 1 loader)      │        │  (Module 2 — K. Sarkar)    │
              └────────────┬────────────┘        └──────────────┬─────────────┘
                            │  cpu_ns_by_pid                      │ total_joules
                            └───────────────┬──────────────────────┘
                                             ▼
                              ┌────────────────────────────┐
                              │  attribution.py              │
                              │  attribute_energy()          │
                              │  proportional split by        │
                              │  CPU-time share               │
                              │  (Module 3 — Aryan Gupta)     │
                              └───────────────┬───────────────┘
                                               │ AttributionResult per PID
                                               ▼
                              ┌────────────────────────────┐
                              │  energy_profiler.py CLI       │
                              │  live table + run totals +    │
                              │  JSON report                  │
                              │  (Integration — Chirag Goyal) │
                              └────────────────────────────┘
```

## Module interfaces (as implemented)

| From | To | Data | Format |
|---|---|---|---|
| Kernel BPF maps | `sched_probe.py` | cumulative on-CPU ns per PID | BCC table (`pid -> u64`) |
| `sched_probe.py` | CLI | per-window ns delta per PID | `dict[int, int]` |
| `/sys/class/powercap/intel-rapl:0/energy_uj` | `rapl_reader.py` | cumulative microjoules | sysfs text file |
| `rapl_reader.py` | CLI | Joules consumed this window | `float` |
| CLI | `attribution.py` | `cpu_ns_by_pid`, `total_joules` | function args |
| `attribution.py` | CLI | per-PID `AttributionResult` (share, joules) | `dict[int, AttributionResult]` |

## Why proportional CPU-time attribution

RAPL only exposes a single, socket-wide energy counter — there is no
hardware per-process energy signal to attribute against. We assume, per the
Review 1 problem statement, that a process's share of node-wide dynamic
energy draw in a short window is approximately proportional to its share of
on-CPU time in that window (the same assumption used by comparable tools
such as PowerAPI and Scaphandre, though those use coarser, user-space-polled
CPU-time data instead of eBPF's kernel-precise `sched_switch` timings — this
is the differentiator identified in the Review 1 literature survey).

## Known limitations carried from Review 1

- Idle/system power draw (the wattage consumed with zero processes actively
  scheduled) is not separately modeled; it is implicitly excluded because
  Joules are only attributed to PIDs with non-zero CPU-time delta in the
  window.
- GPU, DRAM and NIC power are out of scope (Review 1 §2).
- Windows without any scheduled activity (all deltas zero) attribute no
  Joules to any PID — that window's energy is currently unaccounted for
  rather than assigned to "idle"; flagged as a defect to address before
  Review 3 (see progress document, Risks section).
