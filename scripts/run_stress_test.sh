#!/usr/bin/env bash
# run_stress_test.sh — Real-hardware validation helper (Review 1 Testing Strategy)
#
# Runs stress-ng to generate a known, controllable CPU load while the
# profiler is running, so the attributed Joules for the stress-ng PID can be
# checked against the RAPL delta for that window and (where available) an
# external power-meter baseline.
#
# Requires: Linux, stress-ng, root (for the profiler's real eBPF/RAPL mode).
set -euo pipefail

DURATION=${1:-20}
CORES=${2:-2}

command -v stress-ng >/dev/null 2>&1 || {
  echo "stress-ng not found. Install with: sudo apt install stress-ng" >&2
  exit 1
}

echo "Starting stress-ng (${CORES} cores, ${DURATION}s) in background..."
stress-ng --cpu "${CORES}" --timeout "${DURATION}s" &
STRESS_PID=$!

echo "Starting profiler for ${DURATION}s (real mode)..."
sudo python3 -m src.cli.energy_profiler --duration "${DURATION}" --interval 1 --out stress_test_report.json

wait "${STRESS_PID}" || true
echo "Done. Compare stress-ng's PID's attributed Joules in stress_test_report.json"
echo "against expected: (stress-ng RAPL share) ~ proportional to its wall-clock CPU busy time."
