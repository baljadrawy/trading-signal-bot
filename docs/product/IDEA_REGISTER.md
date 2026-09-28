# Idea Register / سجل الأفكار
All future ideas, including new ideas from chat or research, must be entered here (or a linked GitHub Issue) **before implementation**. Proposed ideas are not permission to change production. Promote approved ideas into the Decision Log with an ADR and link an implementation issue/PR.

## Intake template
- ID, date, originator and source discussion/issue
- Problem/opportunity and hypothesis
- Data availability and point-in-time constraints
- Proposed behavior and whether it changes strategy/risk
- Baseline, measurable success criteria, prospective validation plan
- Risks, failure modes, rollback, security/privacy implications
- Phase, dependencies, effort estimate and status: PROPOSED / RESEARCH / APPROVED_DIRECTION / APPROVED_IMPLEMENTATION / DEFERRED / REJECTED / DONE
- Owner decision/date and linked ADR, Issue, PR and experiment IDs

## Current backlog
| ID | Idea | Phase | Status | Guardrail |
|---|---|---|---|---|
| IDEA-001 | Historical pattern similarity search with forward outcomes and independent episode counting | P2/P5 | APPROVED_DIRECTION | No look-ahead or sealed-holdout discovery. |
| IDEA-002 | Probabilistic downside/drawdown warnings across multiple horizons | P2/P5 | APPROVED_DIRECTION | Predeclared events; calibrated prospective forecasts. |
| IDEA-003 | Upside/rally and false-breakout prediction | P2/P5 | APPROVED_DIRECTION | Compare against simple baselines and costs. |
| IDEA-004 | Market-regime and transition detection | P2/P5 | APPROVED_DIRECTION | Stability/drift testing. |
| IDEA-005 | Risk throttle for new entries and portfolio exposure, with favorable-regime restoration | Post-P5 | APPROVED_DIRECTION | Shadow first; B3 never bypassed; no above-baseline expansion without new owner approval. |
| IDEA-006 | Execution-price slippage model using historical orderbook and realized fills | Future | PROPOSED | Separate from price drawdown model; require real point-in-time liquidity data. |
| IDEA-007 | ML Lab and web command center; Telegram alerts/limited controls | P4/P5 | APPROVED_DIRECTION | Audit sensitive approvals; reuse Grafana first. |
| IDEA-008 | Separate execution gateway and future trading-bot integration | Future | DEFERRED | No live execution or credentials. |
| IDEA-009 | Model-driven early exit of existing positions | Future | PROPOSED | Not authorized; requires independent testing and separate owner approval. |
| IDEA-010 | Above-baseline position/exposure expansion in strong upside regimes | Future | PROPOSED | Not authorized; must prove net utility and pass risk gates. |

## Research discipline
Never choose labels, horizons or model thresholds after inspecting the same evaluation outcomes. Store negative results and failed experiments, not just winning runs. Keep an immutable experiment manifest: dataset/source coverage, feature availability timestamps, code SHA, config hash, train/validation/test periods, metrics, warnings and owner approval status.
