# Research runner: source recovery provenance (E1, 2026-10-20)

- Source commit: `7d4c9c2` (`feature/mi-cpu-guard-20261008`); files imported unchanged with `git checkout 7d4c9c2 -- ops/research docs/ops/RESEARCH_EXECUTION_LAYER.md docs/ops/BACKGROUND_EXECUTION.md`.
- Installed copy: `~/ops/research-runner` (read-only comparison, nothing installed or changed). **All 19 installed files have the same git blob hash as this tree** (VERIFIED). The tree adds tests, the MI CPU guard design and its evidence records, which are not installed.
- Not changed here: runner config (R2 is still 6 workers / 600 %; lowering it to the owner's 5 vCPU is a separate change), systemd units, slices, the installed copy.
- Tests: `cd ops/research/tests && python3 -m unittest test_detpool test_admission_and_logic test_launcher_swap test_mi_cpuguard test_mi_ledger_integrity test_mi_integration test_integration_systemd test_mi_cpuguard_integration` → 105 run, OK, 9 skipped (real-systemd integration tests are opt-in by environment variable and were not run). Not part of `tests.yml` CI.

| Installed file | git blob |
|---|---|
| `bin/research-run` | `aad8ef4a3ede` |
| `examples/synthetic_cpu.py` | `10e2463a8ea6` |
| `mi_cpuguard/guard_main.py` | `b46fbcf6af23` |
| `mi_cpuguard/guard.py` | `3de43762b380` |
| `mi_cpuguard/__init__.py` | `4f491fe37bc1` |
| `mi_cpuguard/ledger.py` | `bdfcf1ed2811` |
| `mi_cpuguard/units.py` | `7a296dee4d0c` |
| `README.md` | `78434af261f5` |
| `research_exec/admission.py` | `4393cae1830d` |
| `research_exec/config.py` | `cc97e722bab8` |
| `research_exec/detpool.py` | `e318bb61a1f0` |
| `research_exec/hostsignals.py` | `8fbe1c0f9c5c` |
| `research_exec/__init__.py` | `32976d0ba513` |
| `research_exec/jobwrap.py` | `7c8df0f4993e` |
| `research_exec/launcher.py` | `6b547eb73f6a` |
| `research_exec/__main__.py` | `6239cf791f39` |
| `research_exec/mi_campaign.py` | `a705ae566508` |
| `research_exec/record.py` | `1467f6dcd996` |
| `research_exec/watchdog.py` | `db56ba09d7f1` |
