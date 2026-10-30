# LCE-2 independent review (reviewer entry point)

**AUTHOR-PRODUCED.** Prepared by the session that wrote the runner; this is not independent evidence. Verify it
against the sources below. Pushing this material authorizes **review only**: no merge, deployment, production change
or LCE substitution follows from it.

| What | Where (this branch) |
|---|---|
| Claims, each with line references and the test that covers it | [`REVIEW_EVIDENCE.md`](REVIEW_EVIDENCE.md) |
| Runner (`lce-2`) | `ops/ci/lce.py` (sha256 `780f98d983dbae95b02948becdfdf3d69877ffecce7c20468df3976afa36f20d`) |
| Runner tests (22 functions, 46 cases) | `tests/test_lce_runner.py`; the author's run is in [`test_lce_runner_synthetic.txt`](test_lce_runner_synthetic.txt) |
| Workflow it emulates | `.github/workflows/tests.yml` (sha256 `f30ffb0c…` = `REVIEWED_WORKFLOW_SHA256`) |
| Policy | `docs/governance/OWNER_OPERATING_CONTRACT.md` §8–§9, `docs/ops/CI_EFFICIENCY.md` §10–§11 |
| Evidence of the 12 local runs (sanitized) | [`evidence_runs.json`](evidence_runs.json) |

Re-run the synthetic tests with `python -m pytest -q tests/test_lce_runner.py` (needs pytest and pyyaml; no Docker).
