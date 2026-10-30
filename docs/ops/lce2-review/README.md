# LCE-2 independent review (reviewer entry point)

**AUTHOR-PRODUCED.** Prepared by the session that wrote the runner; this is not independent evidence. Verify it
against the sources below. Pushing this material authorizes **review only**: no merge, deployment, production change
or LCE substitution follows from it.

| What | Where (this branch) |
|---|---|
| **Remediation R1 (`lce-2.1`): answer to the REQUEST_CHANGES review, finding by finding** | [`REMEDIATION_R1.md`](REMEDIATION_R1.md) |
| Claims for `lce-2` at `b078767`, each with line references and the test that covers it (line numbers predate R1) | [`REVIEW_EVIDENCE.md`](REVIEW_EVIDENCE.md) |
| Runner | `ops/ci/lce.py`: `lce-2.1` on this branch head; `lce-2` (sha256 `780f98d9…`) at `b078767` |
| Runner tests | `tests/test_lce_runner.py`; the author's run is in [`test_lce_runner_synthetic.txt`](test_lce_runner_synthetic.txt) |
| Workflow it emulates | `.github/workflows/tests.yml` (sha256 `f30ffb0c…` = `REVIEWED_WORKFLOW_SHA256`) |
| Policy | `docs/governance/OWNER_OPERATING_CONTRACT.md` §8–§9, `docs/ops/CI_EFFICIENCY.md` §10–§11 |
| Evidence of the 12 local runs (sanitized) | [`evidence_runs.json`](evidence_runs.json) |

Re-run the synthetic tests with `python -m pytest -q tests/test_lce_runner.py` (needs pytest and pyyaml; no Docker).
