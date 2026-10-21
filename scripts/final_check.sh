#!/usr/bin/env bash
# final_check.sh — checklist item 8: rerun all automated tests + the simulation, save evidence.
# Run (no root needed):  bash scripts/final_check.sh
cd "$(dirname "$0")/.."
mkdir -p evidence
{
  echo "== automated tests =="; python3 -m pytest tests -v
  echo; echo "== simulated end-to-end run (3 windows) =="
  python3 -m src.cli.energy_profiler --duration 3 --interval 1 --simulate --seed 42 --out evidence/simulation_report.json
} 2>&1 | tee evidence/final_check_output.txt
