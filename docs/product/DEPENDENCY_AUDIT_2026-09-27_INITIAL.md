# Post-P1 dependency inventory — initial repository snapshot
**2026-09-27 | Source:** `feature/forward-instrumentation@23dea904a852` GitHub manifests and Dockerfiles. **Status:** REPOSITORY INVENTORY ONLY; upstream latest stable versions, production-installed package versions and ARM64 build compatibility are **NOT YET VERIFIED**. This document is not approval to upgrade.

| Package/runtime | Current declared version / locations | Review |
|---|---|---|
| Python base | `python:3.12-slim` pinned by digest `d764629...` in four P1 services | Check digest provenance, supported Python patch and arm64 image |
| python-binance | `1.0.19`: analyzer/scanner/signal_engine/trade_tracker | Upstream latest stable; API changes and precision/klines parity |
| asyncpg | `0.29.0`: all seven services | Latest stable; PG driver and transactions parity |
| aiohttp | `3.13.5`: all seven services | Latest stable, CVE claims and transitive dependencies; comment claiming all CVEs fixed requires evidence |
| pandas | `3.0.3`: analyzer/scanner/signal_engine | Python 3.12/ARM64 and numerical parity |
| numpy | `2.2.6`: analyzer/scanner | ABI and indicator numerical parity |
| ta | `0.11.0`: analyzer | Indicator parity; check maintenance |
| websockets | `12.0`: analyzer | Compatibility with python-binance and streaming behavior |
| asyncio-throttle | `1.0.2`: scanner | Maintenance and compatibility |
| anthropic | `0.25.0`: signal_engine; `0.49.0`: optimizer (retired) | Version divergence; API compatibility; don't restart optimizer |
| python-telegram-bot | `21.11.1`: telegram | Latest stable; authorization and B3 command parity |
| pip/wheel | `pip==26.1.*`, `wheel==0.46.*` in four reviewed Dockerfiles | Verify stable compatibility and reproducibility |
| Docker/OS/PostgreSQL | Actual deployed versions not established by this repository snapshot | Read-only host/image inventory, support/EOL and security review |

## Required Claude follow-up after P1
1. Confirm the P1 commit, actual deployed image/package versions and whether source manifests match deployed images; read-only.
2. Fetch **official** PyPI/project release metadata, official release notes, security advisories and compatibility matrices at the actual audit date. Record source URL, date and target for every direct package and critical transitive package; don't label a package latest based on an old code comment.
3. Check Python 3.12, linux/aarch64, wheel availability, Docker image digests and PostgreSQL compatibility.
4. Generate reproducible dependency locks and a separate proposed dependency upgrade PR only **after** owner authorizes the implementation scope.
5. Run isolated build/import, 999+ P1 tests, 24 Telegram image tests, B3, decision parity, DB lifecycle, indicator drift, performance and failure-mode tests. A failure or changed decision is a STOP gate.
6. Never change the existing P1 feature branch, production or halted paper state as part of inventory.
