"""
rapl_reader.py — Module 2: Hardware Reader (Owner: Kalparun Sarkar)

Reads Intel RAPL energy counters from the Linux powercap sysfs interface
(/sys/class/powercap/intel-rapl:0/energy_uj) and converts successive
readings into Joules consumed over a window.

RAPL exposes a monotonically increasing microjoule counter that wraps
around at `max_energy_range_uj`. This module handles that wraparound and
is calibrated to poll no faster than the counter's own update interval
(Stage 3, Review 1 methodology) to avoid aliasing.

Two modes, mirroring Module 1:
  --simulate   Synthetic power draw (Gaussian jitter around a base wattage)
               for machines without RAPL/powercap (e.g. this Windows dev
               environment, or non-Intel/AMD-RAPL CPUs, or containers/VMs
               without passthrough access to the counter).
  (default)    Reads the real sysfs path. Requires Linux with RAPL exposed
               (readable without root for the energy_uj file on most distros;
               raise via `sudo chmod` or run as root if permission denied).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass

RAPL_BASE = "/sys/class/powercap/intel-rapl:0"


@dataclass
class RaplReading:
    energy_uj: int
    timestamp: float


class RaplReader:
    """Wraps the wraparound-aware Joule-delta logic so it is unit-testable
    against a fake sysfs directory (see tests/test_rapl_reader.py) without
    real RAPL hardware."""

    def __init__(self, rapl_dir: str = RAPL_BASE):
        self.rapl_dir = rapl_dir
        self._max_range_uj = self._read_max_range()
        self._last: RaplReading | None = None

    def _read_max_range(self) -> int:
        try:
            with open(f"{self.rapl_dir}/max_energy_range_uj") as f:
                return int(f.read().strip())
        except OSError:
            # Fallback used when max_energy_range_uj is unavailable; large
            # enough that wraparound within a short polling window is
            # detected as "went backwards" rather than silently miscounted.
            return 2**32

    def _read_energy_uj(self) -> int:
        with open(f"{self.rapl_dir}/energy_uj") as f:
            return int(f.read().strip())

    def poll(self) -> float | None:
        """Read the counter now and return Joules consumed since the
        previous poll(), or None on the first call (no baseline yet)."""
        now = time.time()
        energy = self._read_energy_uj()
        reading = RaplReading(energy_uj=energy, timestamp=now)

        joules = None
        if self._last is not None:
            delta_uj = reading.energy_uj - self._last.energy_uj
            if delta_uj < 0:
                # Counter wrapped around during this window.
                delta_uj += self._max_range_uj
            joules = delta_uj / 1_000_000.0

        self._last = reading
        return joules


def run_real(interval: float, duration: float):
    reader = RaplReader()
    reader.poll()  # establish baseline
    elapsed = 0.0
    while elapsed < duration:
        time.sleep(interval)
        elapsed += interval
        joules = reader.poll()
        yield joules


def run_simulated(interval: float, duration: float, base_watts: float = 45.0, seed: int | None = None):
    rng = random.Random(seed)
    elapsed = 0.0
    while elapsed < duration:
        time.sleep(min(interval, 0.05))
        elapsed += interval
        watts = max(5.0, rng.gauss(base_watts, base_watts * 0.1))
        yield watts * interval  # Joules = Watts * seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=1.0, help="Poll interval (s)")
    parser.add_argument("--duration", type=float, default=5.0, help="Total run time (s)")
    parser.add_argument("--simulate", action="store_true", help="Run without RAPL hardware")
    parser.add_argument("--seed", type=int, default=None, help="Simulation RNG seed")
    args = parser.parse_args()

    gen = (
        run_simulated(args.interval, args.duration, seed=args.seed)
        if args.simulate
        else run_real(args.interval, args.duration)
    )

    for joules in gen:
        print(json.dumps({"type": "rapl_window", "joules": joules}))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
