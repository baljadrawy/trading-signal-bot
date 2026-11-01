# External Review Evidence Access & Distribution Policy

Status: Owner-approved default process (2026-11-01)
Scope: All external reviews for this project. Intended as a reusable default for the owner's other software projects, subject to each project's stricter governance.
Authority: Owner approval of this process does NOT authorize release, production changes, access to protected research, or sharing with unapproved recipients.

## 1. Evidence-first prerequisite
Before asking an external reviewer for a verdict, prepare a reproducible, minimum-necessary source/evidence package for the exact baseline and candidate commit IDs. Include the relevant diff, source and dependency context, tests and synthetic fixtures, operational context, navigation index, explicit omissions/redactions, and reproduction instructions. Avoid developer conclusions or prior review verdicts in the initial independent review package.

## 2. Secure distribution
Run and document a secret, identity, host-detail, and protected-data scan **before** distribution. Exclude credentials, production evidence, protected holdouts, trade outcomes, P&L, and other data not expressly authorized for the review. Where redaction is necessary, label it and explain what cannot be verified. Do not claim a scan guarantees absence of all secrets.

Use restricted Google Drive sharing with named, owner-approved reviewers when a suitable authorized connection is available. Use private GitHub for canonical source, tests, and release artifacts and, when appropriate, repository access for approved reviewers. Do not make repositories or Drive links public; do not alter access permissions without owner approval. Uploads and grants must be explicitly authorized, not assumed from the existence of a package. If the preferred channel is unavailable, stop and request a secure alternative rather than sending an inaccessible path.

## 3. Integrity and access confirmation
Record package name, exact commit SHAs, file manifest, SHA-256, archive size, distribution location, redactions, and recipients. Independently verify that the uploaded bytes match the local checksum and that **each reviewer can actually access and inspect the contents** before starting the review. A server-local pathname, checksum alone, or inaccessible Drive reference is not evidence delivery.

## 4. Independent review
Use distinct reviewer sessions; prefer different providers when available. Do not describe same-provider or developer-coordinated agents as genuinely external. Each reviewer must inspect the actual evidence and distinguish verified results, unverified claims, and access limits. Missing source access yields INSUFFICIENT EVIDENCE, not GO. Keep individual first-round reports separate and unchanged.

## 5. Rounds and closure
Run one independent round, consolidate findings, and run a targeted closure round only for safety-critical disagreements, material missing evidence, or necessary corrections. Code changes require a new immutable candidate identity and revalidation of affected findings. Do not use majority vote to override a substantiated blocker.

## 6. Separation of approvals
Evidence sharing, code review, merge, image build, deployment, restart, database changes, protected evidence access, and production activation are separate approval boundaries. Review completion is not deployment permission. Honor PAPER_ONLY, B3/PAPER_HALTED, A29 D1/D2 HOLD, and applicable Class B operations gates.

## 7. Evidence record
Retain a review register with reviewer identity/provider, evidence package digest, confirmed access, source commits, verdict, findings, closure status, and remaining limitations. Never record a review as completed if the reviewer could not access the evidence.
