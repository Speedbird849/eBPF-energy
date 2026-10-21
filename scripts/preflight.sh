#!/usr/bin/env bash
# preflight.sh — Task 1 step 1: can THIS machine run the real eBPF + RAPL profiler?
# Run:  sudo bash scripts/preflight.sh      (saves evidence/preflight.txt)
cd "$(dirname "$0")/.."
mkdir -p evidence
OUT=evidence/preflight.txt
{
echo "== preflight $(date -Is) =="
echo "-- kernel";            uname -r
echo "-- cpu";               lscpu | grep -E "Model name|Vendor|^CPU\(s\)|Hypervisor" || true
echo "-- virtualization";    systemd-detect-virt 2>/dev/null || echo "unknown"
echo "-- uid (need 0)";      id -u
echo "-- powercap";          ls -l /sys/class/powercap/ 2>&1
echo "-- RAPL package domain"
for f in name energy_uj max_energy_range_uj; do
  printf "  %s: " "$f"; cat /sys/class/powercap/intel-rapl:0/$f 2>&1
done
echo "-- tracefs sched_switch"
ls /sys/kernel/tracing/events/sched/sched_switch 2>&1 || ls /sys/kernel/debug/tracing/events/sched/sched_switch 2>&1
echo "-- kernel headers";    ls -d /lib/modules/$(uname -r)/build 2>&1
echo "-- python bcc";        /usr/bin/python3 -c "import bcc; print('BCC OK', bcc.__file__)" 2>&1
echo "-- stress-ng";         command -v stress-ng || echo "MISSING (sudo apt install stress-ng)"
} 2>&1 | tee "$OUT"
echo
echo "Saved to $OUT"
echo "If RAPL is missing you are probably in a VM/WSL: run on a bare-metal Linux install or a"
echo "VM with RAPL passthrough. If BCC is missing:"
echo "  sudo apt install bpfcc-tools python3-bpfcc linux-headers-\$(uname -r) stress-ng"
