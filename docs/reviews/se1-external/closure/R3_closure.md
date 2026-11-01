REVIEWER 3 CLOSURE CHECK

Read-only; I did not touch production evidence files. All lines are in deploy/se1-funnel-ea8ae4f/README.md @ 78ba705, and the candidate code is still 7ff582f.

- B1 (cap resets on restart): ACCEPTED-AS-RESIDUAL. Line 104 discloses that the cap is per process per UTC day. Lines 133-134 require RestartCount to stay 0. The code still resets on restart, so the "bounded by the cap" storage claim is only true with zero restarts.
- B2 (a dropped emit is never retried): ACCEPTED-AS-RESIDUAL. Line 143 makes not_recorded a hard 0, and the rollback list covers a non-zero value. A drop is detected, but the loss is not repaired.
- B3 (valid true on incomplete cycles): CLOSED for the observation window. Lines 138-141 require valid, observation_complete, empty integration_failures, and no notes.gate_block. The code is unchanged.
- B4 (a backward clock step resets the cap), B6 (F4.unattributed hard to diagnose) and B8 (test gaps): ACCEPTED-AS-RESIDUAL. There is no code change. B6 is partly mitigated, because line 145 gates on unattributed and line 147 reconciles against the cycle.outcome decision histogram. B8 is the test gaps, including the uncovered cap-on-close-events case.
- B5 (funnel stage order) and B7 (macro-veto flap burns the cap): ACCEPTED-AS-RESIDUAL. The README does not address either. Both affect interpretation or the cap, not safety.
- B9 (idle cycles leave no trace): CLOSED. Line 152 treats an idle window as insufficient runtime evidence.
- Window limits (D): CLOSED. Line 156 states what 24 hours cannot establish.

My verdict does not change: CONDITIONAL GO. The conditions are now met procedurally. Only code hardening of B2, B4 and B6 remains optional.
