"""research_exec - bounded, attributable, freezable execution layer for research batch work.

Stdlib only (Python >= 3.10). Components:
  config     - profiles (R1/R2/R3) and thresholds; JSON override for tests/operators
  hostsignals- read-only probes: collector health, /proc/stat steal, PSI, MemAvailable, windows
  admission  - go/no-go decision before a job starts
  launcher   - builds the systemd --user transient job + watchdog units
  jobwrap    - main process of the job unit: holds the heavy lock, runs the command, measures
  watchdog   - bounded supervisor bound to the job unit: freeze / thaw / group-kill
  detpool    - deterministic parallel map with per-unit seeds, canonical merge, checkpoint/resume
See ops/research/README.md and docs/ops/RESEARCH_EXECUTION_LAYER.md.
"""

__version__ = "1.0.0"
