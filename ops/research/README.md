# ops/research: research execution layer

This tool runs research, simulation and calibration batches as bounded, attributable and freezable `systemd --user` jobs. It uses only the standard library (Python 3.12, `/usr/bin/python3`).
- Design and thresholds: [docs/ops/RESEARCH_EXECUTION_LAYER.md](../../docs/ops/RESEARCH_EXECUTION_LAYER.md)
- Rules: [docs/ops/BACKGROUND_EXECUTION.md](../../docs/ops/BACKGROUND_EXECUTION.md)

## Deployed copy
`~/ops/research-runner/` holds `bin/`, `research_exec/` and `examples/`. The file hashes are recorded in the G1/G2 evidence.

To redeploy from a reviewed checkout:
```
cp -r ops/research/{bin,research_exec,examples} ~/ops/research-runner/
```
The job state lives in `~/.local/state/research-runner/jobs/<job-id>/`. The locks live in `~/.local/state/research-runner/*.lock`.

## Run a job
```bash
R=~/ops/research-runner/bin/research-run
$R admit --profile R1                       # dry admission check, prints every input (exit 0 admit / 3 refuse)
$R run --job-id p2f-calib-v3-a1 --owner agent:p2f-calib --profile R1 --cwd /path/to/workdir --wait \
   -- /usr/bin/python3 /abs/path/my_study.py --checkpoint out/ckpt --out out/merged.json
$R status --job-id p2f-calib-v3-a1          # unit states (job + watchdog)
$R freeze|thaw|kill --job-id p2f-calib-v3-a1
$R record --job-id p2f-calib-v3-a1          # job_record.json (wall/cpu/peak mem/freeze periods/admission)
$R profiles                                 # effective profiles, thresholds, windows
```
- **Job ids are single-use.** For a retry, use a new id; the checkpoint directory gives you resume.
- **`--wait` is optional.** Without it, the job keeps running under its watchdog after the caller exits.
- **Use absolute paths.** The job runs under the user manager's environment. Use `--setenv K=V` for extra environment variables; `PYTHONPATH` values are appended.
- **Your code reads `RESEARCH_WORKERS`.** `detpool.run_units(workers=None)` does this for you.
- **Higher profiles need explicit opt-in.** R2 needs `--allow-elevated` and R3 needs `--attended`.

## Write parallel research code
```python
from research_exec.detpool import make_units, run_units
units = make_units([f"rep-{i:04d}" for i in range(400)], base_seed=20261006, params={"study": "F1"})
def one_rep(unit):                 # top-level, pure: use unit.rng() / unit.seed only
    rng = unit.rng(); ...; return {"stat": ...}
res = run_units(one_rep, units, checkpoint_dir="out/ckpt", fn_id="f1.one_rep", meta={"version": 3})
open("out/merged.json", "wb").write(res.merged_bytes)   # byte-identical at any worker count
```

## Tests
```bash
cd ops/research/tests
python3 -m unittest test_detpool test_admission_and_logic            # no systemd, seconds
RESEARCH_EXEC_INTEGRATION=1 python3 -m unittest test_integration_systemd   # starts small rj-/rw-g1g2t-* units
```
The integration tests use fake Collector health and monitor files in a temporary directory. They never read or modify the real Collector files. Run them outside the protected windows.
