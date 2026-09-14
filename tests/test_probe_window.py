"""
Unit tests for Module 1's windowing logic (ProbeWindow). This is the part
of the kernel-probe loader that has no eBPF/kernel dependency, so it is
tested directly here; the eBPF C program itself (sched_probe.bpf.c) is
validated on-target via the live demo (real-hardware/VM run) per the
Review 1 Stage 2 plan, since it cannot be unit-tested off a Linux kernel.
"""
from src.module1_ebpf_probe.sched_probe import ProbeWindow


def test_first_snapshot_returns_full_cumulative_as_delta():
    window = ProbeWindow()
    deltas = window.delta({100: 5_000, 200: 3_000})
    assert deltas == {100: 5_000, 200: 3_000}


def test_second_snapshot_returns_only_the_increase():
    window = ProbeWindow()
    window.delta({100: 5_000})
    deltas = window.delta({100: 8_000})
    assert deltas == {100: 3_000}


def test_pid_with_no_change_is_dropped_from_result():
    window = ProbeWindow()
    window.delta({100: 5_000, 200: 1_000})
    deltas = window.delta({100: 5_000, 200: 1_500})  # pid 100 unchanged
    assert deltas == {200: 500}


def test_pid_that_exits_stops_appearing_and_does_not_error():
    window = ProbeWindow()
    window.delta({100: 5_000, 200: 1_000})
    deltas = window.delta({100: 6_000})  # pid 200 exited, absent now
    assert deltas == {100: 1_000}
    assert 200 not in deltas


def test_new_pid_appearing_mid_run_gets_full_value_as_first_delta():
    window = ProbeWindow()
    window.delta({100: 5_000})
    deltas = window.delta({100: 6_000, 300: 2_000})
    assert deltas == {100: 1_000, 300: 2_000}
