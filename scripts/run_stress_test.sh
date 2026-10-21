#!/usr/bin/env bash
# run_stress_test.sh — Task 2: stress-ng validation with idle baseline + automatic checks.
# Run:  sudo bash scripts/run_stress_test.sh [duration_s=30] [cores=2]
set -euo pipefail
cd "$(dirname "$0")/.."
DURATION=${1:-30}
CORES=${2:-2}
PY=/usr/bin/python3
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo: sudo bash scripts/run_stress_test.sh"; exit 1; }
command -v stress-ng >/dev/null 2>&1 || { echo "Install: sudo apt install stress-ng" >&2; exit 1; }
mkdir -p evidence

echo "[1/3] Idle baseline (10 s, machine should be quiet)..."
$PY -m src.cli.energy_profiler --duration 10 --interval 1 --quiet --out evidence/idle_report.json

echo "[2/3] Loaded run: stress-ng --cpu ${CORES} for ${DURATION}s + profiler..."
stress-ng --cpu "${CORES}" --timeout "$((DURATION + 3))s" >/dev/null 2>&1 &
STRESS_PID=$!
sleep 1
$PY -m src.cli.energy_profiler --duration "${DURATION}" --interval 1 \
    --out evidence/stress_report.json | tee evidence/stress_terminal.txt
wait "${STRESS_PID}" || true

echo "[3/3] Analysis"
$PY scripts/analyze_stress_report.py evidence/stress_report.json \
    --idle evidence/idle_report.json --cores "${CORES}" --process-prefix stress-ng \
    | tee evidence/stress_analysis.txt
