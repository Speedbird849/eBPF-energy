#!/usr/bin/env python3
# mod1_tracker.py

from bcc import BPF
import time

# 1. eBPF C program 
bpf_program = r"""
#include <uapi/linux/ptrace.h>

// Stores the timestamp (ns) at which each PID was last scheduled ON a CPU
BPF_HASH(start_time, u32, u64);

// Accumulates total time (ns) each PID has spent running on a CPU
BPF_HASH(exec_time, u32, u64);

TRACEPOINT_PROBE(sched, sched_switch) {
    u32 prev_pid = args->prev_pid;
    u32 next_pid = args->next_pid;
    u64 ts = bpf_ktime_get_ns();

    // The outgoing process (prev) is being scheduled OFF the CPU
    u64 *start_ts = start_time.lookup(&prev_pid);
    if (start_ts != 0) {
        // How long did it just run for?
        u64 delta = ts - *start_ts;
        
        // Add that delta onto its running total
        u64 *total = exec_time.lookup(&prev_pid);
        if (total != 0) {
            *total += delta;
        } else {
            exec_time.update(&prev_pid, &delta);
        }
        start_time.delete(&prev_pid);
    }

    // The incoming process (next) is being scheduled ON the CPU
    if (next_pid != 0) { // Skip idle task
        start_time.update(&next_pid, &ts);
    }
    return 0;
}
"""

# 2. Load the BPF program into the kernel
b = BPF(text=bpf_program)
print("Tracking per-process CPU time... Press Ctrl-C to stop.\n")

# 3. Every second: read the exec_time map, print a table, clear it
try:
    while True:
        time.sleep(1)
        exec_time_map = b["exec_time"]

        if len(exec_time_map) == 0:
            continue

        print(f"{'PID':<8} {'COMMAND':<20} {'CPU TIME (ms)':>15}")
        print("-" * 45)

        # Sort by CPU time descending 
        entries = sorted(exec_time_map.items(), key=lambda kv: kv[1].value, reverse=True)

        for pid, total_ns in entries:
            pid_val = pid.value
            ms = total_ns.value / 1_000_000 # ns to ms
            
            try:
                with open(f"/proc/{pid_val}/comm", "r") as f:
                    comm = f.read().strip()
            except FileNotFoundError:
                comm = "<exited>"

            print(f"{pid_val:<8} {comm:<20} {ms:>15.3f}")

        print() 
        exec_time_map.clear()

except KeyboardInterrupt:
    print("\nStopping tracker.")