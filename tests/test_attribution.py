"""
Unit tests for Module 3 (attribution engine). Pure logic, no hardware
dependency — this is the "boundary and representative project-specific
inputs" testing evidence required for Review 2, Component 4.
"""
import pytest

from src.module3_attribution_engine.attribution import attribute_energy, merge_windows


def test_proportional_split_two_pids():
    result = attribute_energy({100: 6_000_000, 200: 4_000_000}, total_joules=10.0)
    assert result[100].cpu_share == pytest.approx(0.6)
    assert result[200].cpu_share == pytest.approx(0.4)
    assert result[100].joules == pytest.approx(6.0)
    assert result[200].joules == pytest.approx(4.0)
    # Attributed Joules must sum back to the input total (no leakage).
    assert result[100].joules + result[200].joules == pytest.approx(10.0)


def test_single_pid_gets_all_energy():
    result = attribute_energy({42: 1_000}, total_joules=3.3)
    assert result[42].cpu_share == 1.0
    assert result[42].joules == pytest.approx(3.3)


def test_empty_window_returns_empty_result():
    assert attribute_energy({}, total_joules=5.0) == {}


def test_all_zero_cpu_time_returns_empty_result():
    # Boundary case: PIDs present in the map but with zero delta (e.g. a
    # process that was scheduled in and immediately back out within the
    # measurement resolution).
    assert attribute_energy({1: 0, 2: 0}, total_joules=5.0) == {}


def test_zero_total_joules_yields_zero_joules_but_valid_shares():
    result = attribute_energy({1: 500, 2: 500}, total_joules=0.0)
    assert result[1].joules == 0.0
    assert result[2].cpu_share == pytest.approx(0.5)


def test_invalid_negative_joules_raises():
    with pytest.raises(ValueError):
        attribute_energy({1: 100}, total_joules=-1.0)


def test_invalid_negative_cpu_ns_raises():
    with pytest.raises(ValueError):
        attribute_energy({1: -100}, total_joules=1.0)


def test_merge_windows_sums_across_history():
    w1 = attribute_energy({1: 500, 2: 500}, total_joules=10.0)
    w2 = attribute_energy({1: 800, 2: 200}, total_joules=10.0)
    totals = merge_windows([w1, w2])
    assert totals[1] == pytest.approx(5.0 + 8.0)
    assert totals[2] == pytest.approx(5.0 + 2.0)


def test_merge_windows_handles_pid_absent_in_some_windows():
    w1 = attribute_energy({1: 500, 2: 500}, total_joules=10.0)
    w2 = attribute_energy({1: 1000}, total_joules=10.0)  # pid 2 exited
    totals = merge_windows([w1, w2])
    assert totals[1] == pytest.approx(5.0 + 10.0)
    assert totals[2] == pytest.approx(5.0)


def test_many_pids_realistic_distribution():
    cpu_ns = {i: (i + 1) * 1_000_000 for i in range(10)}
    result = attribute_energy(cpu_ns, total_joules=50.0)
    assert sum(r.joules for r in result.values()) == pytest.approx(50.0)
    assert sum(r.cpu_share for r in result.values()) == pytest.approx(1.0)
