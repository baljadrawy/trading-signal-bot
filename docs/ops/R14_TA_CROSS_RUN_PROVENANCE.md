# R1.4-H — independent-run ta wheel provenance

**Status: review-only investigation, NOT hash-locked reproducible-build certification.**

R1.4-G run [39164281793](https://github.com/baljadrawy/trading-signal-bot/actions/runs/39164281793) produced two byte-identical ta wheels in a single runner with fixed SOURCE_DATE_EPOCH, SHA256 `2f19c26db458201b0f018a2d88d3a5b18297f525afa430d6f7753fa1e6b57352`. Earlier R1.4-E/F builds differed, so independent-run evidence is required.

This manual-only workflow runs two separate ephemeral GitHub Actions jobs. Each downloads the exact `ta==0.11.0` sdist independently, records source SHA256, Python/pip/platform and source commit, builds with the same fixed epoch and records wheel SHA256. A third job compares both source and wheel hashes and fails closed on differences. Artifacts persist for 14 days.

**Critical limits:** The source SHA256 is *measured*, not checked against a separately approved trusted expected value. The runner image, pip, build isolation dependencies, build backend and transitive toolchain are **not pinned**. Independent runners on one workflow execution are not independent external supply chains or a time-separated cross-run verification. Equal hashes do not prove supply-chain integrity. Wheel-building executes untrusted third-party build code in disposable runners. No locks are certified and no production, scientific experiments, collector or trading systems are touched.

**Required next gate:** review both source and wheel evidence; independently verify source checksum against trusted package index provenance; identify and pin build backend and tools with immutable hashes; rerun across distinct workflow executions and check exact output hashes; then address transitive hash locks, isolated clean install, full inventory equality and canonical OCI/runtime attestation. Stop if any source or wheel hash differs. Do not automatically adjust direct pins.
