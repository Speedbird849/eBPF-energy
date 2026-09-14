"""
Unit tests for Module 2 (RAPL reader). Uses a fake sysfs directory (tmp_path)
so the wraparound-aware Joule-delta logic can be validated without real
RAPL hardware — this is the intended "independently unit-tested" evidence
from the Review 1 Stage 3 plan, now delivered for Review 2.
"""
from src.module2_rapl_reader.rapl_reader import RaplReader


def _make_fake_rapl_dir(tmp_path, energy_uj: int, max_range_uj: int = 1_000_000):
    # Real sysfs uses "intel-rapl:0" (colon is valid on Linux, where this
    # code actually runs); Windows forbids ':' in path segments, so the test
    # fixture uses an equivalent name. RaplReader takes the directory as a
    # plain string, so the ':' has no behavioral significance here.
    d = tmp_path / "intel-rapl-0"
    d.mkdir()
    (d / "energy_uj").write_text(str(energy_uj))
    (d / "max_energy_range_uj").write_text(str(max_range_uj))
    return d


def _set_energy(fake_dir, energy_uj: int):
    (fake_dir / "energy_uj").write_text(str(energy_uj))


def test_first_poll_returns_none_no_baseline(tmp_path):
    fake_dir = _make_fake_rapl_dir(tmp_path, energy_uj=100_000)
    reader = RaplReader(rapl_dir=str(fake_dir))
    assert reader.poll() is None


def test_normal_increment_computes_joules(tmp_path):
    fake_dir = _make_fake_rapl_dir(tmp_path, energy_uj=100_000)
    reader = RaplReader(rapl_dir=str(fake_dir))
    reader.poll()  # baseline
    _set_energy(fake_dir, 350_000)  # +250,000 uJ = 0.25 J
    assert reader.poll() == 0.25


def test_wraparound_is_handled(tmp_path):
    max_range = 1_000_000
    fake_dir = _make_fake_rapl_dir(tmp_path, energy_uj=900_000, max_range_uj=max_range)
    reader = RaplReader(rapl_dir=str(fake_dir))
    reader.poll()  # baseline = 900,000
    # Counter wraps: goes to 50,000 after passing max_range.
    _set_energy(fake_dir, 50_000)
    joules = reader.poll()
    # Expected consumed: (max_range - 900_000) + 50_000 = 150,000 uJ = 0.15 J
    assert joules == 0.15


def test_missing_max_energy_range_falls_back_gracefully(tmp_path):
    d = tmp_path / "intel-rapl-0"
    d.mkdir()
    (d / "energy_uj").write_text("100000")
    # No max_energy_range_uj file written -> falls back to 2**32 internally.
    reader = RaplReader(rapl_dir=str(d))
    reader.poll()
    _set_energy(d, 200_000)
    assert reader.poll() == 0.1


def test_repeated_polls_accumulate_independently(tmp_path):
    fake_dir = _make_fake_rapl_dir(tmp_path, energy_uj=0)
    reader = RaplReader(rapl_dir=str(fake_dir))
    reader.poll()
    _set_energy(fake_dir, 10_000)
    j1 = reader.poll()
    _set_energy(fake_dir, 25_000)
    j2 = reader.poll()
    assert j1 == 0.01
    assert j2 == 0.015
