# External Review Evidence Access & Distribution Policy

Status: Owner-approved, revised 2026-11-01
Scope: Trading Signal Bot external reviews; recommended default for other projects, subject to their stricter policies.
Authority: Permission to prepare and share appropriate review evidence does not authorize release, merge, host changes, deployment, restart, protected holdout access, or live trading.

## 1. Transparency is the default
This is a development and Paper-testing project. Do **not** automatically classify test results, Paper trade counts, historical profit factors, research conclusions, previous audit verdicts, loss-streak halt status, dirty Git checkouts, deployment defects, Docker/Compose details, backup procedures, or operational observations as secrets. Share facts and weaknesses needed for an accurate review, including unfavorable results. The reviewer must be able to audit real issues; do not sanitize away relevant failures.

For an initial blind scientific review, prior verdicts or outcomes may be temporarily separated to limit anchoring, with disclosure in a subsequent contextual/closure phase. This is methodological staging, not secrecy.

## 2. What must remain protected
Never distribute credentials, API keys, tokens, private keys, passwords, unredacted authentication URLs, personal data, or third-party confidential material. Do not expose actionable access credentials or unnecessarily precise attack-enabling host information. Keep protected A29/holdout data, protected experiment evidence, and separately governed research materials sealed unless specifically authorized under their own controls. If uncertain about a genuinely sensitive item, ask the owner; do not invent blanket restrictions.

## 3. Evidence-first packaging
Prepare a reproducible package bound to exact baseline and candidate commit IDs: source, diff, relevant dependencies, tests, synthetic fixtures, deployment/operational evidence, manifest, SHA-256, navigation index, reproduction instructions, and explicit limitations. Include enough operating context for R2 to evaluate real risks. Redact only what section 2 requires; label redactions and resulting review limitations.

## 4. Pre-distribution checks
Verify archive integrity, manifest, extraction safety, code/diff parity, and absence of actual secrets. Use automated scanning plus independent semantic/manual inspection; repeating the same regex does not count as independent verification. A failed check blocks distribution until resolved. Review the exact final archive, not only its source directory.

## 5. Secure access
Prefer restricted Google Drive sharing with named, owner-approved reviewers for review archives and private GitHub for canonical source, tests, and release artifacts. No public/anyone-with-link access or permission changes without explicit owner approval. Record location, checksum, recipients, and access scope. Confirm each reviewer can actually retrieve and inspect the package before requesting a verdict. A server-local path or checksum alone is insufficient.

## 6. Independent reviews and closure
Use distinct reviewer sessions, preferably distinct providers. Internal developer agents are not external reviewers. Each reviewer reports verified findings, unverified claims, and access limits. Lack of source access means INSUFFICIENT EVIDENCE, not GO. Preserve first-round reports; run focused closure reviews for substantive blockers, missing evidence, and conflicts. Do not vote away substantiated findings.

## 7. Approval separation and audit register
Sharing evidence does not authorize code merges, builds, deployments, restarts, production DB changes, protected-data access, or live trading. Preserve PAPER_ONLY, B3/PAPER_HALTED, A29 D1/D2 HOLD, and Class B gates. Record reviewer identity/provider, package hash, confirmed access, commit identities, findings, verdict, closure, and limitations.
