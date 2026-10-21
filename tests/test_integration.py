"""
Integration tests for the REAL-mode code path of the CLI, using a fake sysfs
RAPL directory and a scripted stand-in for the eBPF probe (BCC/eBPF cannot
run in CI). These check the combined behaviour the final review asks about:
a PID disappearing, an idle window, and RAPL being unreadable for a window.
"""
import json
import os

import pytest

from src.cli import energy_profiler as cli
from src.module1_ebpf_probe.sched_probe import ProbeWindow
from src.module2_rapl_reader.rapl_reader import RaplUnavailable, check_rapl


class ScriptedProbe:
    """call 0 = baseline; then one scripted action per window."""

    def __init__(self, rapl_dir, script):
        self.dir, self.script, self.calls = rapl_dir, script, 0
        self.energy = 0
        (rapl_dir / "energy_uj").write_text("0")

    def sample(self):
        i = self.calls
        self.calls += 1
        if i == 0:
            return {}
        if i - 1 >= len(self.script):
            self.energy += 1_000_000
            (self.dir / "energy_uj").write_text(str(self.energy))
            return {999: 1_000_000}
        cpu, add_uj, rapl_ok = self.script[i - 1]
        self.energy += add_uj
        f = self.dir / "energy_uj"
        if rapl_ok:
            f.write_text(str(self.energy))
        elif f.exists():
            f.unlink()                       # RAPL unreadable this window
        return cpu

    def close(self):
        pass


@pytest.fixture
def rapl_dir(tmp_path):
    d = tmp_path / "intel-rapl-0"
    d.mkdir()
    (d / "max_energy_range_uj").write_text("1000000000")
    (d / "energy_uj").write_text("0")
    return d


def _run(monkeypatch, rapl_dir, script, tmp_path):
    monkeypatch.setattr(cli, "EbpfProbe", lambda: ScriptedProbe(rapl_dir, script))
    return cli.run(0.4, 0.02, False, None, tmp_path / "r.json", group_by="tid",
                   rapl_dir=str(rapl_dir), quiet=True)


def test_pid_disappears_idle_window_and_rapl_gap(monkeypatch, rapl_dir, tmp_path):
    script = [
        ({111: 1_000_000, 222: 3_000_000}, 4_000_000, True),   # w1 normal, 4 J
        ({}, 500_000, True),                                    # w2 idle: PIDs gone, 0.5 J to nobody
        ({333: 2_000_000}, 0, False),                           # w3 RAPL unreadable
        ({333: 2_000_000, 444: 2_000_000}, 6_000_000, True),    # w4 recovers, covers w3+w4
    ]
    rep = _run(monkeypatch, rapl_dir, script, tmp_path)
    w = {r["window"]: r for r in rep["per_window"]}
    assert rep["skipped_rapl_windows"] == 1
    assert set(w[1]["per_pid"]) == {"111", "222"}
    assert w[1]["per_pid"]["222"]["joules"] == pytest.approx(3.0)
    assert 2 not in w or w[2]["per_pid"] == {}                  # idle window attributes nothing
    last = next(r for r in rep["per_window"] if "444" in r["per_pid"])
    # w3's CPU time was carried into w4: pid 333 has 4 ms, 444 has 2 ms of the 6 J
    assert last["per_pid"]["333"]["joules"] == pytest.approx(4.0)
    assert last["per_pid"]["444"]["joules"] == pytest.approx(2.0)
    v = rep["validation"]
    assert v["attributed_joules"] == pytest.approx(v["raw_rapl_joules_active_windows"])
    assert v["conservation_error_percent"] < 1e-9


def test_handoff_file_path_end_to_end(monkeypatch, rapl_dir, tmp_path):
    monkeypatch.setattr(cli, "EbpfProbe", lambda: ScriptedProbe(rapl_dir, []))
    rep = cli.run(0.3, 0.02, False, None, tmp_path / "r.json", group_by="tid",
                  rapl_dir=str(rapl_dir), handoff_file=str(tmp_path / "h.json"), quiet=True)
    assert rep["skipped_handoff_windows"] == 0
    assert rep["windows"] >= 3
    assert json.loads((tmp_path / "r.json").read_text())["windows"] == rep["windows"]


def test_rapl_missing_gives_clear_error(tmp_path):
    ok, msg = check_rapl(str(tmp_path / "does-not-exist"))
    assert not ok and "not found" in msg
    with pytest.raises(RaplUnavailable):
        cli.run(0.1, 0.05, False, None, tmp_path / "r.json", rapl_dir=str(tmp_path / "nope"), quiet=True)


def test_probe_counter_going_backwards_does_not_double_count():
    w = ProbeWindow()
    assert w.delta({1: 1000}) == {1: 1000}
    assert w.delta({1: 900}) == {}            # benign read race: no negative delta
    assert w.delta({1: 1200}) == {1: 200}     # and the baseline was not lowered
