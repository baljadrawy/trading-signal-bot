"""MI Phase 1S CPU guard (design + isolated tests only; NOT wired into research_exec, NOT installed).

Two independent limits:
  * rate   - kernel-enforced: every MI unit runs inside research-mi.slice with CPUQuota=600% (cgroup cpu.max
             600000 100000), which bounds the aggregate of all descendants, children included;
  * volume - fail-closed guard: cumulative cgroup CPU (cpu.stat usage_usec of the slice) is bounded by a reservation
             taken from an append-only, hash-chained budget ledger capped at 28 800 CPU-s. Wall-clock limits are an
             additional safeguard only.
"""
QUOTA_PCT = 600
QUOTA_CORES = QUOTA_PCT / 100
CAP_CPU_S = 28_800
POLL_S = 1.0
MAX_POLL_GAP_S = 3.0
MARGIN_CPU_S = QUOTA_CORES * POLL_S * 2          # max CPU consumable between two polls, doubled (= 12 CPU-s)
SLICE = "research-mi.slice"                       # child of research.slice (800 %, CPUWeight=idle)
