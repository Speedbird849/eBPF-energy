#!/usr/bin/env bash
# run_real_demo.sh — Task 1: full real-mode run (eBPF + RAPL) with evidence capture.
# Run:  sudo bash scripts/run_real_demo.sh [duration_s]
set -euo pipefail
cd "$(dirname "$0")/.."
D=${1:-30}
mkdir -p evidence
PY=/usr/bin/python3
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo"; exit 1; }
echo "Generating some background load so PIDs are visible..."
( for i in 1 2; do ( timeout "$D" sh -c 'while :; do :; done' & ) ; done ) 2>/dev/null
$PY -m src.cli.energy_profiler --duration "$D" --interval 1 --out evidence/real_run_report.json \
    --handoff-file evidence/handoff.json | tee evidence/real_run_terminal.txt
echo; echo "Evidence saved: evidence/real_run_terminal.txt, evidence/real_run_report.json"
