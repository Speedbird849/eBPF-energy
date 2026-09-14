"""
attribution.py — Module 3: Attribution Engine (Owner: Aryan Gupta)

Pure, hardware-independent logic that merges Module 1's per-PID CPU-time
deltas with Module 2's per-window RAPL Joule reading and distributes the
Joules across PIDs proportionally to each PID's share of total on-CPU time
in that window (Stage 4, Review 1 methodology).

This module has zero I/O — it is a set of pure functions over plain dicts —
so it can be fully unit-tested (see tests/test_attribution.py) without eBPF
or RAPL hardware, and without touching Modules 1/2 at all.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AttributionResult:
    pid: int
    cpu_ns: int
    cpu_share: float   # fraction of total on-CPU time this window, 0..1
    joules: float       # attributed energy this window


def attribute_energy(
    cpu_ns_by_pid: dict[int, int],
    total_joules: float,
) -> dict[int, AttributionResult]:
    """Proportionally distribute `total_joules` across PIDs based on each
    PID's share of the summed on-CPU nanoseconds in `cpu_ns_by_pid`.

    Edge cases handled explicitly:
      - No PIDs scheduled this window (empty dict) -> empty result, the
        window's Joules are attributed to nobody (idle/system draw).
      - Total on-CPU time is zero (all-zero deltas) -> same as above.
      - Negative Joules or negative cpu_ns are rejected: they indicate a
        bug upstream (e.g. an unhandled RAPL wraparound or a PID accounted
        twice) rather than a valid physical reading, so we fail loudly
        instead of silently producing nonsense attribution.
    """
    if total_joules < 0:
        raise ValueError(f"total_joules must be >= 0, got {total_joules}")
    for pid, ns in cpu_ns_by_pid.items():
        if ns < 0:
            raise ValueError(f"cpu_ns for pid {pid} must be >= 0, got {ns}")

    total_ns = sum(cpu_ns_by_pid.values())
    if total_ns == 0 or not cpu_ns_by_pid:
        return {}

    results: dict[int, AttributionResult] = {}
    for pid, ns in cpu_ns_by_pid.items():
        share = ns / total_ns
        results[pid] = AttributionResult(
            pid=pid,
            cpu_ns=ns,
            cpu_share=share,
            joules=total_joules * share,
        )
    return results


def merge_windows(history: list[dict[int, AttributionResult]]) -> dict[int, float]:
    """Sum attributed Joules for each PID across a sequence of windows —
    used by the CLI to print a running total over the whole profiling run."""
    totals: dict[int, float] = {}
    for window in history:
        for pid, result in window.items():
            totals[pid] = totals.get(pid, 0.0) + result.joules
    return totals
