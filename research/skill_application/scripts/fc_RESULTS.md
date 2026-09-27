# FC — Delta-Neutral Funding-Carry Backtest: GO/NO-GO Audit

**Date:** 2026-07-29 · **Stance:** falsify-first (default NO-GO) · **Mode:** read-only research, paper-only shop.
**Verdict:** ## NO-GO ##

Mechanism tested: long $N spot + short $N USD-M perp (delta≈0), collect funding when perp premium is positive.
Per-period P&L = funding_collected + basis mark-to-market (spot_ret − perp_ret) − amortized round-trip fees,
with isolated short-leg margin at leverage L and intra-period liquidation from perp highs.

---

## Universe & coverage (stated explicitly — no silent truncation)

- **20 liquid USD-M perps** (the pre-specified cap): BTC ETH BNB SOL XRP ADA DOGE AVAX LINK DOT LTC ATOM NEAR MATIC ARB OP APT INJ SUI FIL (USDT).
- **Period:** 2021-01-01 → 2026-05-31. **106,341 8h symbol-periods = 97.1 symbol-years.**
- Full 2021→2026 history for 14 symbols. Shorter (listed later): OP 2022-06, INJ 2022-08, APT 2022-10, ARB 2023-03, SUI 2023-05.
- **MATIC perp truncates 2024-09-10** (Binance MATIC→POL rename; perp klines stop). Kept the 4,044 periods that exist.
- Data: Binance data.binance.vision — funding (`fundingRate` monthly), perp 1h klines, spot 1h from local `bt_data`. Download coverage: funding 1209 ok/111 404, perp 1188 ok/132 404 (404s are pre-listing months only). Funding intervals 99.9% at 8h (only 101 sub-8h SOL rows; immaterial, summed onto their 8h bucket).

## No-look-ahead model
- Periods = 8h buckets aligned to funding settlement (00/08/16 UTC). Funding settled at T is attributed to the bucket it was **earned over** `[T−8h, T)` (index = T//8h − 1).
- **Gate (pre-registered, strictly conservative):** hold period k iff **prior** settled funding f_{k−1} > 0 (known at period start; never peeks at f_k). Verified: when gate=HOLD, this-period funding>0 in 88.4% of cases; mean funding while idle = −0.0103% (gate does skip backwardation).
- Prices = 1h close at bucket boundary; intra-period perp HIGH = max of 1h highs in the bucket (for liquidation). Fees charged once per holding spell (both legs open+close) + once per liquidation re-hedge, amortized. Returns reported **on deployed capital = N(1 + 1/L)** (spot + short margin), which the rough +8.8% figure ignored.
- Liquidation: short isolated margin, thr(L)=1/L − 0.005. **Model R** (rebalanced, reference reset each 8h) and **Model P** (passive, reference = spell entry — the honest no-rebalance tail).

---

## Headline numbers

### Gross funding reproduces the rough probe
Mean 8h funding = 0.0081%, median 0.0097%, **73.8% of periods > 0**, min −6.94% / max +0.56%.
**Always-on gross carry on NOTIONAL = +8.83%/yr** — matches the +8.8% rough estimate. On **capital** (÷1.5 at L=2) this is only **+5.9%/yr** before fees/basis/tails. Basis mark-to-market over full holds ≈ 0 (mean-reverts), so basis is *not* the killer.

### Two gate implementations give opposite results — for a decisive reason
| Variant | gross/yr (cap, L=2) | **NET/yr @0.6% (cap, committed)** | why |
|---|---|---|---|
| **Pre-registered strict gate** (hold iff f_{k−1}>0) | +11.4% (deployed) | **−29.2% (L=2) / −33.1% (L=3)** | funding sign flips 10–23% of 8h periods → **9,129 spells, avg hold 2.9 days** → 0.6%×round-trips = **~76%/yr in fees**. Fatal churn. |
| **Always-on** (no gate — steel-man of the mechanism) | +5.9% (deployed) | **+5.67% (L=2) / +6.05% (L=3)** | ~45–81 spells total, fees negligible; but eats backwardation funding and carries the full liquidation tail. |
| **Smoothed gate** (trailing-9 mean f>0) | +10.2% (deployed) | **+0.59% (L=2) / +0.44% (L=3)** | 1,729 spells — the extra yield it captures is ~exactly eaten by churn fees. |

### NET annual on CAPITAL (committed), by cost — always-on steel-man (the only variant with positive net)
| L | gross(cap,dep) | net@0.3% | net@0.4% | net@0.6% |
|---|---|---|---|---|
| 2 | +5.92% | +5.79% | +5.75% | +5.67% |
| 3 | +6.66% | +6.36% | +6.26% | +6.05% |

**But this "edge" is regime-beta concentrated in 2021**, and it fails the tail test — see robustness.

### Liquidation frequency & worst tail (real events, not data wicks)
The liquidation events are genuine 2021 parabolas: DOGE Reddit squeeze Jan-2021 (+50–150% single 8h candles), NEAR/MATIC/FIL/SOL/XRP verticals.
| L | Model R rebalanced | worst event (R) | Model P passive | worst event (P) |
|---|---|---|---|---|
| 2 | 15 events, 0.15/sym-yr | **−33.97% notional = −22.65% of capital** | 117 events, 1.20/sym-yr | **−27.1% of capital** |
| 3 | 51 events, 0.53/sym-yr | **−24.55% notional = −18.41% of capital** | 175 events, 1.80/sym-yr | **−29.1% of capital** |

Worst single event = NEARUSDT 2021-12-15: **perp wicked +88% in 8h while spot rose only +15.5%** at the same bar → short margin wiped, spot offsets only partially → **−34% notional**. Delta-neutral does **not** contain this: perp squeezes decouple from spot (basis blowout) exactly when the short liquidates. One such event = 3–6 years of carry.

### Regime concentration (the real story) — always-on, net@0.6%, cap, committed
Per-year net (L=2): **2021 +25.4% · 2022 −1.9% · 2023 +3.3% · 2024 +8.1% · 2025 +0.8% · 2026 −1.6%.**
- **Leave-2021-out → +2.63%/yr** (below the +5% threshold). Every other LOYO fold stays >5% only because 2021 dominates.
- **Symbol-clustered 95% CI = [+4.08, +6.88]** (L=2) — looks positive, but symbols are cross-sectionally correlated within a regime, so this **understates uncertainty**.
- **Year-clustered 95% CI = [−0.09, +13.04]** (L=2) / **[−0.26, +14.51]** (L=3) — **straddles 0.** Honest regime-aware inference cannot reject zero.
- Funding has structurally decayed since 2021 (peak-alt-mania funding of +50–100%/yr on alts is gone). This is the same regime-beta / decay pattern flagged in the ML-daily-edge shelving (2026-06-25).

---

## A) Findings that appear real
1. The gross funding-carry mechanism exists and is measured correctly: +8.83%/yr on notional, 73.8% of periods positive — reproduces the rough probe.
2. Basis mark-to-market averages ≈ 0 over full holds (mean-reverts); it adds variance, not a systematic drag. The naive probe's omission of basis is *not* what breaks it.
3. On a proper **capital** base (spot + short margin), the notional +8.8% shrinks to ~+5.9–6.7%/yr before costs — a ~1.5× haircut the probe ignored.
4. Liquidation events are real, rare, and violent (2021 alt parabolas); the delta-neutral hedge is imperfect because perp can spike far above spot during squeezes.
5. The pre-registered single-lag funding-sign gate is a **fee-churn machine** (2.9-day average hold, ~38–76%/yr fee drag) — it destroys the carry regardless of the mechanism.

## B) Findings that appear suspicious
1. The always-on "+5.7%/yr net" survives 0.6% fees *only because it never trades* (45 spells in 97 symbol-years) — an idealization that ignores rebalancing/roll/hedge-maintenance costs a live book incurs.
2. The symbol-clustered CI (>0) is **too tight**: it treats 20 correlated crypto legs as independent draws. The uncertainty that matters (year-to-year funding regime) makes the CI straddle 0.
3. Nearly all profit is 2021 (+25%) with a smaller 2024 (+8%) echo; 3 of the last 4.5 years are ~flat-to-negative. This is exposure to the funding-rate regime, not a repeatable edge.
4. Winsorizing at 1/99 (as pre-registered) *hides* the very liquidation losses that threshold 3 exists to catch — so the "+5.7% winsorized" central number and the "−23% tail" must be read together, not the mean alone.

## C) Largest methodological risk
**Liquidation/basis modeling of the short leg is the crux and is under-determined by 8h data.** I detect liquidation from 8h-bucket perp highs and offset with spot at the perp-high bar; true intra-hour perp-vs-spot decoupling during a squeeze could be worse (thin-book wicks) or the position could be actively de-risked before liquidation. Model R (rebalanced) assumes free continuous margin top-up; Model P (passive) assumes none — reality is in between, and **both fail threshold 3 by 6–10×.** Secondary risk: the choice of capital base (N(1+1/L)) and whether idle capital earns a cash yield (assumed 0) — a T-bill sleeve would add a flat ~4–5%/yr to *every* variant equally but does not create funding-carry alpha.

## D) Is there enough evidence to BUILD the live paper shadow test? — **NO-GO**

Threshold-by-threshold (base = pessimistic 0.6% cost, NET on capital, both L=2 and L=3):

| # | Threshold | Pre-registered gate | Always-on steel-man | Pass? |
|---|---|---|---|---|
| **1** | Net annual (winsor) ≥ +5%/yr @0.6% | **−29.2% / −33.1%** | +5.67% / +6.05% full-sample, **but +2.63% leave-2021-out** | **FAIL** (gate); **FRAGILE/FAIL** (steel-man, regime-dependent) |
| **2** | Lower bound of clustered 95% CI > 0 | CI = [−31.9, −26.0] | symbol-cluster [+4.08,+6.88] **but year-cluster [−0.09,+13.04]** | **FAIL** (gate); **FAIL** (steel-man on honest year-clustering) |
| **3** | No single liq event > −3% of capital (L=2 & L=3) | tails −17% to −30% | **−22.65% (L=2 R), −18.41% (L=3 R); passive −27% to −34%** | **FAIL** (6–10× over budget) |
| **4** | ≥4/6 monthly windows pos (majority) & majority years pos | 0% windows, 0/6 years | 68% windows, 4/6 years | FAIL (gate); PASS (steel-man) |

The pre-registered strategy fails all four. The steel-man passes only T4 outright; T1/T2 collapse under regime-aware inference (leave-2021-out and year-clustered CI), and **T3 fails outright under every variant and both leverages**. A single 2021-class liquidation erases years of carry, and the "return" is long-the-2021-funding-regime, which has decayed. **Not enough evidence to build the shadow test.**

## E) Lowest-risk next step
Do **not** deploy carry as specified. If the mechanism is pursued at all, the lowest-risk probe is a **paper-only, tail-first** study that (a) uses **cross-margin or a large explicit maintenance buffer** so short-leg liquidation is structurally impossible at realistic moves, (b) **caps exposure to majors (BTC/ETH)** where 8h perp-vs-spot decoupling is smallest, (c) models **realistic recurring rebalancing/roll costs**, and (d) is judged on **post-2022 data only** (the decayed-funding regime). If that restricted version cannot clear +5%/yr net with a year-clustered CI>0 and contained tails, abandon. Cheaper still: monitor live funding for a fixed window and re-decide — no capital, no code changes.

## F) Confidence: **High** (that it is NO-GO)
Gross reproduces the prior probe; the failures are large and multiply-sourced (fee churn, capital-base haircut, uncontained liquidation tails, and 2021 regime concentration confirmed by LOYO + year-clustered bootstrap). The only path to a "pass" required an idealized zero-churn, free-rebalancing, symbol-clustered-CI framing that does not survive honest inference or the tail threshold.

---

### Scripts & artifacts (all under `research/skill_application/`)
- `scripts/fc_download.py` — persistent download of funding + perp 1h klines → `data/funding/`, `data/perp/`.
- `scripts/fc_backtest.py` — no-look-ahead 8h-period engine → `scripts/fc_periods.csv` (106,341 rows).
- `scripts/fc_robust.py` — pre-registered strict-gate robustness + 4-threshold table → `scripts/fc_robust_out.txt`.
- `scripts/fc_alwayson.py` — always-on & smoothed-gate steel-man variants.
- `scripts/fc_RESULTS.md` — this file.
