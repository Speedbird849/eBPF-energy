/*
 * sched_probe.bpf.c — Module 1: Kernel Probe (Owner: Pranjal Sharma)
 *
 * Attaches to the tracepoint:sched:sched_switch tracepoint and maintains
 * two BPF hash maps keyed by PID:
 *
 *   start_ns  : timestamp (ns) at which a PID was last scheduled ONTO the CPU
 *   cpu_ns    : cumulative nanoseconds a PID has spent ON-CPU since the probe
 *               was loaded (or since the last snapshot reset by user-space)
 *
 * Design notes (Stage 1 — Instrumentation Design, Review 1):
 *  - We charge time to the OUTGOING task at each context switch, using the
 *    delta between "now" and the timestamp recorded the last time that task
 *    was scheduled IN. This keeps the hot path O(1) with two hash lookups
 *    and no locking beyond BPF's own per-CPU map safety.
 *  - Keying by raw PID (not TGID) is intentional: attribution downstream can
 *    aggregate PIDs into a TGID/container/cgroup as needed, but the kernel
 *    probe itself stays minimal to keep per-event overhead low (<1% target
 *    from Review 1 objectives).
 *  - This file is written against the BCC (BPF Compiler Collection) helper
 *    macros (TRACEPOINT_PROBE, BPF_HASH) so it is compiled and loaded by the
 *    Python loader in sched_probe.py using BCC's on-the-fly clang/LLVM JIT.
 *    Requires Linux kernel >= 5.8, BCC installed, CAP_BPF/root.
 */

#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

/* pid -> ns timestamp at which this pid was scheduled onto the CPU */
BPF_HASH(start_ns, u32, u64);

/* pid -> cumulative on-CPU nanoseconds observed by this probe */
BPF_HASH(cpu_ns, u32, u64);

TRACEPOINT_PROBE(sched, sched_switch) {
    u64 ts = bpf_ktime_get_ns();
    u32 prev_pid = args->prev_pid;
    u32 next_pid = args->next_pid;

    /* Charge the outgoing task for the slice that just ended. */
    u64 *tsp = start_ns.lookup(&prev_pid);
    if (tsp != 0) {
        u64 delta = ts - *tsp;
        u64 zero = 0;
        u64 *val = cpu_ns.lookup_or_init(&prev_pid, &zero);
        (*val) += delta;
        start_ns.delete(&prev_pid);
    }

    /* Mark the incoming task as scheduled-in now. */
    start_ns.update(&next_pid, &ts);

    return 0;
}
