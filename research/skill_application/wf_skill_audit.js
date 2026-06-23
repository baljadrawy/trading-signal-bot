export const meta = {
  name: 'signal-bot-skill-audit',
  description: 'Apply agiprolabs trading-skills methodologies (walk-forward/MR/exits/regime/ML) to audit & search for edge in the live signal-bot data; adversarially verified; Arabic report + Telegram summary',
  phases: [
    { title: 'Diagnose' },
    { title: 'EdgeSearch' },
    { title: 'ExitRegime' },
    { title: 'Verify' },
    { title: 'Synthesize' },
  ],
}

const VENV = '/home/tradmin/trading-signal-bot/research/skill_application/.venv/bin/python'
const SC   = '/home/tradmin/trading-signal-bot/research/skill_application/scripts'
const OUT  = '/home/tradmin/trading-signal-bot/research/skill_application/out'
const SKILLS = '/home/tradmin/trading-signal-bot/research/external_skills/skills'

const PRE = `
# ENVIRONMENT (read carefully — you are a quantitative research AUDITOR, falsification-first)
You run on the signal-bot server. Goal: rigorously test whether the agiprolabs trading-skill
methodologies reveal ANY real, fee-surviving edge in this Binance-spot paper-trading signal bot,
and quantify overfitting in prior "edge" claims. Be skeptical. A negative result is a valid, valuable result.

## How to run code
- Python (isolated venv, full stack: numpy/pandas/scipy/statsmodels/scikit-learn/xgboost/lightgbm):
    ${VENV}
- ALWAYS write your script INTO THE SCRIPTS DIR so 'import lib' resolves, then run it:
    write file ${SC}/run_<name>.py   (NOT in out/ — Python adds the script's own dir to sys.path)
    then:  ${VENV} ${SC}/run_<name>.py
- 'import lib' works because run_<name>.py sits next to lib.py. Write tables/plots/JSON to ${OUT}/.

## Shared toolkit  (cd ${SC}; import lib)
- lib.load_trades() -> DataFrame of 2518 closed trades. Key cols:
    symbol, signal_time, exit_time (UTC), timeframe, market_condition, result, win (0/1),
    profit_percent, profit_usdt (GROSS, $ on $50 pos, NO fees), net_usdt (= gross - fee),
    stop_hit, target_reached, duration_hours, entry_price, exit_price, target_1/2/3, stop_loss,
    score, and st_<indicator> contributions: st_rsi, st_macd, st_stoch_rsi, st_rsi_divergence,
    st_obv, st_bollinger, st_volume, st_ema_cross, st_order_book, st_fibonacci, st_btc_trend, st_tf_conf.
- lib.FEE_USD = 0.15 (round-trip 0.3% on $50). lib.POS_USDT=50. lib.pf(net_array)->profit factor.
- lib.load_close(sym) -> close Series (UTC), ~180d hourly when available (else 1h/1d/4h), or None.
- lib.load_ohlc(sym) -> DataFrame[o,h,l,c] (UTC), ~90d (~Feb19->May20, covers April bulk), or None.
- lib.hurst(series), lib.half_life(series). For ADF use statsmodels.tsa.stattools.adfuller.
- lib.ohlcv_index() -> {symbol:{tf:path}}. 116 symbols have OHLCV; 161/310 traded symbols covered.

## Ground truth already established (do NOT re-derive; build ON it)
- Overall n=2518, WR=37.4%, gross_exp=-0.2147$/trade, net_exp=-0.3647$, PF_gross=0.735, PF_net=0.598.
- LOSING BEFORE fees. Every month/condition/timeframe losing. 2348/2518 trades are April.
- Prior "edge" claims to stress-test: (a) stoch>0 gate, (b) COMBO = stoch>0 & rsi_divergence>0
  (n=7, WR=71%, but 5/7 in May, June OOS=2 breakeven). Treat these as hypotheses to FALSIFY.

## Reference methodology (read the actual skill scripts you need)
- ${SKILLS}/walk-forward-validation/scripts/overfit_detector.py  (PBO, DSR, CSCV)
- ${SKILLS}/mean-reversion/scripts/mean_reversion_test.py
- ${SKILLS}/exit-strategies/scripts/exit_simulator.py
- ${SKILLS}/regime-detection/scripts/detect_regime.py
- ${SKILLS}/signal-classification/scripts/train_classifier.py , walk_forward_backtest.py
- ${SKILLS}/kelly-criterion/scripts/kelly_from_trades.py

## Output contract
Return ONLY the structured object. headline = one-line verdict with the key number.
metrics = dict of the concrete numbers you computed. promising=true ONLY if a fee-surviving,
multiple-testing-aware, out-of-sample-positive effect appears (rare; default false).
claim = the single falsifiable statement a verifier should attack. caveats = sample/coverage/bias limits.
`

const FINDING = {
  type: 'object', additionalProperties: false,
  required: ['module','headline','metrics','promising','claim','caveats'],
  properties: {
    module:   { type: 'string' },
    headline: { type: 'string' },
    metrics:  { type: 'object', additionalProperties: true },
    promising:{ type: 'boolean' },
    claim:    { type: 'string' },
    caveats:  { type: 'string' },
  },
}
const VERDICT = {
  type: 'object', additionalProperties: false,
  required: ['claim','refuted','confidence','reasoning'],
  properties: {
    claim:      { type: 'string' },
    refuted:    { type: 'boolean' },
    confidence: { type: 'number' },
    reasoning:  { type: 'string' },
  },
}

// ───────────────────────────────────────────────────────── Phase 1: Diagnose
phase('Diagnose')
const diagnoseTasks = [
  { label: 'D1:PBO+multitest', prompt: `${PRE}
TASK D1 — Multiple-testing & PBO audit of prior "edge" selection.
Enumerate the FAMILY of cohort filters that were ever tried as candidate edges, e.g.: st_stoch_rsi>0;
st_rsi_divergence>0; COMBO(st_stoch_rsi>0 & st_rsi_divergence>0); st_stoch_rsi>=0.6; st_rsi>=1.2;
score in {3,4,5+}; each market_condition; each timeframe; st_macd>0; st_obv>0; st_bollinger>0; etc.
For EACH: compute n, WR, net_exp, PF_net, and a bootstrap (>=5000) two-sided p-value of net_exp>0.
Apply Bonferroni and Benjamini-Hochberg (FDR 0.10) across the whole family. Report which (if any)
survive correction. Then compute Probability of Backtest Overfitting (PBO) via CSCV over the
in-sample/out-of-sample rank flips of these candidate filters (you may adapt overfit_detector.py).
Deliver concrete numbers. promising=true only if >=1 filter survives FDR AND has positive net_exp.` },

  { label: 'D2:DeflatedSharpe', prompt: `${PRE}
TASK D2 — Deflated Sharpe Ratio & trial-adjusted significance.
Treat each trade's net_usdt as a return stream (ordered by exit_time). Compute per-trade Sharpe,
annualized Sharpe (state your bars/year assumption from avg trade duration), skew & kurtosis.
Compute the Deflated Sharpe Ratio (Bailey & López de Prado) for the BEST cohort (COMBO) given
N independent trials = number of candidate filters from the family (assume N≈20–40; report sensitivity
to N). Report DSR, its p-value, and Minimum Track Record Length needed for significance at the
observed Sharpe. Conclude whether the headline strategy or COMBO Sharpe is statistically distinguishable
from zero after deflation. promising=true only if DSR p<0.05 for a positive-Sharpe cohort.` },

  { label: 'D3:PurgedML', prompt: `${PRE}
TASK D3 — Purged/embargoed walk-forward ML (is there LEARNABLE edge in existing features?).
Features = all st_* columns + score + st_tf_conf + one-hot(market_condition,timeframe). Label = win.
Order by exit_time. Use a purged, embargoed expanding-window walk-forward (>=5 folds; embargo a few
days to avoid overlap leakage). Models: XGBoost AND LogisticRegression (compare). Report mean OOS AUC
per fold + overall, Brier score, and — crucially — the NET expectancy of a strategy that only takes
trades the model scores above a threshold tuned on TRAIN folds (report net_exp & PF_net OOS, and the
fraction of trades taken). Also report top feature importances (gain) / SHAP if available.
Reference signal-classification scripts. promising=true only if OOS AUC>0.55 AND OOS net_exp>0.` },

  { label: 'D4:COMBOforensic', prompt: `${PRE}
TASK D4 — Forensic dissection of the COMBO claim (stoch>0 & rsi_divergence>0).
List ALL COMBO trades (date, symbol, market_condition, timeframe, profit_usdt, result). Split strictly
by month (in-sample vs later months as OOS). Bootstrap CI (10000) on COMBO net_exp. Binomial test of
its win count vs base rate 0.374. Leave-one-out: recompute net_exp removing the single best trade.
Quantify temporal concentration (Herfindahl over months). Also test the "stoch>0 gate": stoch>0 vs
stoch=0 net_exp with bootstrap CI, AND check it replicates within April alone (largest window).
Verdict: is COMBO a real signal or a small-sample/one-month artifact? promising=true only if COMBO
survives the OOS split AND leave-one-out AND binomial at p<0.05.` },
]
const diagnose = await parallel(diagnoseTasks.map(t => () =>
  agent(t.prompt, { label: t.label, phase: 'Diagnose', schema: FINDING })))

// ───────────────────────────────────────────────────────── Phase 2: EdgeSearch
phase('EdgeSearch')
const edge = await parallel([
  () => agent(`${PRE}
TASK E_MR — Mean-reversion filter study (does trading only mean-reverting symbols flip expectancy?).
For every traded symbol that has OHLCV (lib.load_close), compute Hurst (lib.hurst), OU half-life
(lib.half_life), and ADF p-value (statsmodels adfuller on the close, and on log-close). Build a table
symbol -> {hurst, half_life, adf_p, n_trades}. Classify "mean-reverting" = Hurst<0.45 OR adf_p<0.05.
Join to actual trades by symbol. Compare WR / net_exp / PF_net / n for trades on mean-reverting symbols
vs trending vs uncovered. Do it overall AND April-only. Bootstrap CI on the net_exp difference.
Is the mean-reverting subset's net_exp positive and significant after fees? Report concrete numbers and
the coverage (how many trades are on covered symbols). promising=true only if MR-subset net_exp>0 with
bootstrap CI excluding 0.`, { label: 'E_MR:mean-reversion', phase: 'EdgeSearch', schema: FINDING }),

  () => agent(`${PRE}
TASK E_KELLY — Risk/position-sizing reality check using kelly-criterion methodology.
Using the realized trade distribution (net_usdt), compute the empirical edge, payoff ratio (avg_win/avg_loss),
and the Kelly fraction implied by the data — overall and for the COMBO and stoch>0 cohorts. Reference
kelly_from_trades.py. Interpret: what does Kelly say the optimal bet size is for each (expect <=0 for
negative-edge sets)? Also compute max drawdown of the equity curve (cumsum net_usdt) and the longest
losing streak. Frame for a non-technical trader: at the measured edge, what size is "survival-safe"?
promising=true only if any cohort yields a positive Kelly fraction after fees.`,
    { label: 'E_KELLY:sizing', phase: 'EdgeSearch', schema: FINDING }),
])

// ───────────────────────────────────────────────────────── Phase 3: ExitRegime
phase('ExitRegime')
const exitRegime = await parallel([
  () => agent(`${PRE}
TASK X_ATR — Exit-strategy re-simulation: ATR-based stop vs the fixed stop (addresses the #1 loss
driver: SL hit before T1). Use lib.load_ohlc(sym) (full OHLC, covers April bulk). For each trade with
available intrabar OHLC over [signal_time, exit_time] (or up to 48h cap), re-simulate the exit path under
alternative exit rules while HOLDING THE ENTRY FIXED: (a) actual fixed stop_loss + targets (sanity-replay,
compare to recorded result), (b) ATR(14)-based stop at 2.0x / 2.5x / 3.0x ATR below entry with the same
targets, (c) ATR stop + activation delay (no stop in first 4h). Compute net_exp / WR / PF_net / SL-before-T1%
for each rule on the SAME trade set. Report coverage (how many trades had usable OHLC). Reference
exit_simulator.py. promising=true only if an ATR variant yields net_exp>0 (or clearly closer to 0 with
PF_net>1) on a non-trivial sample.`, { label: 'X_ATR:exits', phase: 'ExitRegime', schema: FINDING }),

  () => agent(`${PRE}
TASK R_REGIME — Regime overlay (is there a regime where expectancy is positive?). Build a 4-quadrant
regime per trade at signal_time using the symbol's own series and BTC: volatility axis = ATR% percentile
(or realized-vol percentile from close) ; trend axis = sign/strength of a trend measure (e.g. EMA slope or
ADX-like). Reference detect_regime.py. Bucket every trade into Q1..Q4 (+ a BTC-regime cross: BTC up/down/flat
from BTCUSDT close). Compare net_exp / WR / PF_net / n per regime bucket. Identify any bucket with
positive net_exp and bootstrap CI. Report coverage. promising=true only if a regime bucket has net_exp>0
with bootstrap CI excluding 0 and n>=30.`, { label: 'R_REGIME:regime', phase: 'ExitRegime', schema: FINDING }),
])

// collect
const findings = [...diagnose, ...edge, ...exitRegime].filter(Boolean)
const promising = findings.filter(f => f && f.promising)
log(`findings=${findings.length}  promising=${promising.length}`)

// ───────────────────────────────────────────────────────── Phase 4: Verify (adversarial)
phase('Verify')
// Always hard-verify the two headline prior claims even if agents marked them not-promising,
// plus every promising finding. Each claim attacked by 2 independent skeptics.
const toVerify = []
for (const f of findings) {
  if (f.promising) toVerify.push({ claim: f.claim, ctx: `${f.module}: ${f.headline} | metrics=${JSON.stringify(f.metrics)}` })
}
// guaranteed adversarial checks on the legacy claims
toVerify.push({ claim: 'The stoch>0 gate provides a real, replicable improvement (not just noise reduction within an overall losing system).', ctx: 'legacy gate claim' })
toVerify.push({ claim: 'COMBO (stoch>0 & rsi_divergence>0) is a deployable edge.', ctx: 'legacy COMBO claim' })

const verdicts = await parallel(toVerify.map((v, i) => () =>
  parallel([0,1].map(k => () =>
    agent(`${PRE}
TASK VERIFY — You are an adversarial skeptic (reviewer #${k+1}). Attempt to REFUTE this claim using the
same data/tools. Default to refuted=true unless the evidence is strong, fee-aware, out-of-sample, and
robust to multiple testing. Re-run whatever check you need.
CLAIM: "${v.claim}"
CONTEXT: ${v.ctx}
Set refuted=true if the claim fails any of: insufficient/concentrated sample, look-ahead, multiple-testing
not corrected, effect vanishes OOS or after fees, driven by a few trades. confidence in [0,1].`,
      { label: `verify#${i}.${k}`, phase: 'Verify', schema: VERDICT })))
    .then(vs => {
      const ok = vs.filter(Boolean)
      const refuted = ok.filter(x => x.refuted).length >= 1  // either skeptic refutes -> treat as refuted (strict)
      return { claim: v.claim, ctx: v.ctx, skeptics: ok, refuted, survived: ok.length>0 && !refuted }
    })))

const survivors = verdicts.filter(Boolean).filter(v => v.survived)
log(`claims_verified=${verdicts.length}  survivors=${survivors.length}`)

// ───────────────────────────────────────────────────────── Phase 5: Synthesize
phase('Synthesize')
const pack = {
  findings: findings.map(f => ({ module: f.module, headline: f.headline, promising: f.promising, metrics: f.metrics, caveats: f.caveats })),
  verdicts: verdicts.filter(Boolean).map(v => ({ claim: v.claim, refuted: v.refuted, survived: v.survived,
                       skeptics: v.skeptics.map(s => ({ refuted: s.refuted, confidence: s.confidence, reasoning: s.reasoning })) })),
  survivors: survivors.map(s => s.claim),
}

const synth = await agent(`${PRE}
TASK SYNTHESIZE — Write the final deliverable from the structured results below. You are the auditor;
maintain falsification-first tone; never declare an edge that did not survive Phase-4 verification.

RESULTS (JSON):
${JSON.stringify(pack)}

Produce TWO files (use your file-writing tool), then RETURN the Telegram text as your final message:

1) ${OUT}/REPORT.md  — full Arabic report. Sections:
   - ملخص تنفيذي (هل وُجدت حافة؟ نعم/لا + الرقم الحاسم)
   - لكل مرحلة (تشخيص/بحث الحافة/المخارج/الأنظمة): ماذا طُبّق من سكِلّات المستودع، الأرقام، الحكم
   - الادعاءات التي خضعت للتحقق العدائي ونتيجتها (نجت/دُحضت ولماذا)
   - الخلاصة بصيغة المدقّق (A..F: حقيقي/مريب/أكبر خطر منهجي/كفاية الأدلة للنشر/أقل خطوة خطراً/مستوى الثقة)
   - أي مكسب عملي قابل للتطبيق (مثل ستوب ATR إن خفّض النزيف) مع شرط الاعتماد (PF_net>1 OOS عبر 3 أشهر)

2) ${OUT}/telegram.md — ملخص عربي مكثّف <=3200 حرفاً للإرسال على تيليغرام: عنوان، 5-8 نقاط بالأرقام،
   الحكم النهائي (حافة/لا حافة)، والتوصية. استخدم رموزاً (✅⚠️🔴📊) وبدون Markdown معقّد.

Your FINAL MESSAGE must be EXACTLY the content you wrote to telegram.md (so the orchestrator can send it).`,
  { label: 'synthesize', phase: 'Synthesize' })

return { telegram: synth, findings: pack.findings.length, survivors: pack.survivors }
