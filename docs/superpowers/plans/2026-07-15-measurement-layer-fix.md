# Measurement-Layer Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the signal-bot recording pipeline from (1) counting a re-fired setup as many independent trades and (2) booking stop-loss exits at the overshot poll price instead of the stop level.

**Architecture:** Two localized edits in `trade_tracker/main.py` backed by pure, unit-tested helpers (`shared/candle.py`, a new function in `shared/triple_barrier.py`), plus a non-destructive offline oracle that re-prices existing trades to quantify impact. Running containers are unaffected until an explicit `docker compose build/up` (out of scope here).

**Tech Stack:** Python 3.12, asyncpg (live path), pandas (oracle), pytest via `research/skill_application/.venv`. Postgres 16.

## Global Constraints

- PAPER_TRADING stays `true` — never change it.
- No container rebuild/deploy in this plan. All work on branch `fix/measurement-layer-2026-07-15`.
- `git add <explicit paths>` only — never `git add -A` (repo has large untracked research outputs).
- Run tests with: `research/skill_application/.venv/bin/python -m pytest tests/ -q`.
- STOP_SLIPPAGE default = `0.001` (0.1%). Duplicate guard lives in `trade_tracker` only.
- Follow existing patterns: tests are pure-Python (`sys.path.insert(0, '.')`, direct imports, no DB); `register_new_signals` already uses `NOT EXISTS` guard clauses — extend that pattern.
- Candle periods: `15m`=900s, `4h`=14400s, `1d`=86400s, unknown→86400s.

---

### Task 1: Candle-period helpers

**Files:**
- Create: `shared/candle.py`
- Test: `tests/test_candle.py`

**Interfaces:**
- Produces: `candle_seconds(timeframe: str) -> int`; `is_within_candle(now_ts: float, opened_ts: float, timeframe: str) -> bool`; `candle_interval_case_sql(column: str) -> str`; module constant `CANDLE_SECONDS: dict[str,int]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_candle.py
import sys; sys.path.insert(0, '.')
from shared.candle import (
    candle_seconds, is_within_candle, candle_interval_case_sql, CANDLE_SECONDS,
)


def test_candle_seconds_known():
    assert candle_seconds('15m') == 900
    assert candle_seconds('4h') == 14400
    assert candle_seconds('1d') == 86400


def test_candle_seconds_unknown_defaults_daily():
    assert candle_seconds('7d') == 86400


def test_is_within_candle_true_when_recent():
    # opened 100s ago on 15m (900s window) → still same candle period
    assert is_within_candle(1000.0, 900.0, '15m') is True


def test_is_within_candle_false_after_window():
    # opened 1000s ago on 15m (900s window) → past the candle period
    assert is_within_candle(2000.0, 1000.0, '15m') is False


def test_interval_case_sql_contains_all_seconds():
    sql = candle_interval_case_sql('s.timeframe')
    for tf, secs in CANDLE_SECONDS.items():
        assert f"WHEN '{tf}' THEN INTERVAL '{secs} seconds'" in sql
    assert sql.strip().startswith('CASE s.timeframe')
    assert sql.strip().endswith('END')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `research/skill_application/.venv/bin/python -m pytest tests/test_candle.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'shared.candle'`

- [ ] **Step 3: Write the implementation**

```python
# shared/candle.py
"""Candle-period helpers — single source of truth for timeframe→seconds.
Used by the duplicate guard (trade_tracker), the validation oracle, and tests,
so the SQL cooldown and the Python re-analysis can never drift apart.
"""

CANDLE_SECONDS = {
    '15m': 900,
    '4h': 14400,
    '1d': 86400,
}
DEFAULT_CANDLE_SECONDS = 86400  # unknown timeframe → treat as daily (most conservative)


def candle_seconds(timeframe: str) -> int:
    """Seconds in one candle for the given timeframe."""
    return CANDLE_SECONDS.get(timeframe, DEFAULT_CANDLE_SECONDS)


def is_within_candle(now_ts: float, opened_ts: float, timeframe: str) -> bool:
    """True if opened_ts falls within the last candle period relative to now_ts
    (a rolling cooldown). Used to collapse re-fired identical setups to one position."""
    return (now_ts - opened_ts) < candle_seconds(timeframe)


def candle_interval_case_sql(column: str) -> str:
    """Postgres CASE expression mapping `column` (a timeframe) to an INTERVAL,
    generated from CANDLE_SECONDS so SQL and Python never drift."""
    whens = "\n".join(
        f"            WHEN '{tf}' THEN INTERVAL '{secs} seconds'"
        for tf, secs in CANDLE_SECONDS.items()
    )
    return (
        "CASE " + column + "\n" + whens + "\n"
        f"            ELSE INTERVAL '{DEFAULT_CANDLE_SECONDS} seconds'\n"
        "        END"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `research/skill_application/.venv/bin/python -m pytest tests/test_candle.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add shared/candle.py tests/test_candle.py
git commit -m "feat(candle): candle-period helpers for dedup guard + oracle"
```

---

### Task 2: Modeled stop-fill helper + config knob

**Files:**
- Modify: `shared/config.py` (add `STOP_SLIPPAGE`, near `TRADE_AMOUNT_USDT` line ~76)
- Modify: `shared/triple_barrier.py` (add `modeled_stop_exit`)
- Test: `tests/test_stop_fill.py`

**Interfaces:**
- Produces: `modeled_stop_exit(entry: float, eff_stop: float, slippage: float) -> tuple` returning `(fill_price: float, profit_pct: float)`; `config.STOP_SLIPPAGE: float`.
- Consumes: nothing from earlier tasks.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_stop_fill.py
import sys; sys.path.insert(0, '.')
from shared.triple_barrier import modeled_stop_exit


def test_stop_fill_at_stop_with_slippage():
    # entry 100, stop 97 (-3%), 0.1% slippage → fill 96.903, ≈ -3.097%
    fill, pct = modeled_stop_exit(100.0, 97.0, 0.001)
    assert abs(fill - 96.903) < 1e-6
    assert abs(pct - (-3.097)) < 1e-3


def test_stop_fill_zero_slippage_is_stop():
    fill, pct = modeled_stop_exit(100.0, 97.0, 0.0)
    assert fill == 97.0
    assert abs(pct - (-3.0)) < 1e-9


def test_stop_fill_bounds_overshoot():
    # The real ALLO case: entry .4731, stop .458907 (-3%). Recorded loss was -23.8%
    # (overshoot). Modeled fill must be bounded near the -3% stop, not -23.8%.
    fill, pct = modeled_stop_exit(0.4731, 0.458907, 0.001)
    assert -3.5 < pct < -2.9


def test_stop_fill_preserves_profit_when_stop_above_entry():
    # trailing stop locked in above entry → still a WIN
    fill, pct = modeled_stop_exit(100.0, 105.0, 0.001)
    assert fill > 100.0 and pct > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `research/skill_application/.venv/bin/python -m pytest tests/test_stop_fill.py -q`
Expected: FAIL with `ImportError: cannot import name 'modeled_stop_exit'`

- [ ] **Step 3: Add the config knob**

In `shared/config.py`, immediately after the `TRADE_AMOUNT_USDT` line (~76):

```python
    STOP_SLIPPAGE: float = float(os.getenv('STOP_SLIPPAGE', '0.001'))  # 0.1% modeled stop-fill slippage
```

- [ ] **Step 4: Add the helper**

Append to `shared/triple_barrier.py` (stop logic lives here):

```python
def modeled_stop_exit(entry: float, eff_stop: float, slippage: float) -> tuple:
    """Model a stop fill AT the stop level, not at an overshot poll price.

    Returns (fill_price, profit_pct). Slippage is subtracted so the fill is
    slightly worse than the stop, never better. When eff_stop is above entry
    (a trailing stop in profit), the result is still a win — the sign is
    carried by fill_price vs entry, computed by the caller.
    """
    fill_price = eff_stop * (1 - slippage)
    profit_pct = ((fill_price - entry) / entry) * 100
    return fill_price, profit_pct
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `research/skill_application/.venv/bin/python -m pytest tests/test_stop_fill.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add shared/config.py shared/triple_barrier.py tests/test_stop_fill.py
git commit -m "feat(triple_barrier): modeled_stop_exit + STOP_SLIPPAGE config"
```

---

### Task 3: Wire modeled stop-fill into the live tracker

**Files:**
- Modify: `trade_tracker/main.py` (import block ~line 17-24; `evaluate_trade` stop branch lines 302-317)

**Interfaces:**
- Consumes: `modeled_stop_exit` (Task 2), `config.STOP_SLIPPAGE` (Task 2).

- [ ] **Step 1: Add the import**

In `trade_tracker/main.py`, add `modeled_stop_exit` to the existing `shared.triple_barrier` import block:

```python
from shared.triple_barrier import (
    create_config_from_trade,
    create_state_from_trade,
    step_barrier,
    barrier_status_summary,
    modeled_stop_exit,
    TripleBarrierConfig,
    TripleBarrierState,
)
```

- [ ] **Step 2: Replace the dynamic-stop branch**

Replace lines 302–317 (the `if current_price <= eff_stop:` block) with:

```python
    # فحص ضرب الستوب الديناميكي — نمذجة التعبئة عند مستوى الستوب لا عند سعر الاستطلاع المتجاوز
    if current_price <= eff_stop:
        fill_price, profit_pct = modeled_stop_exit(entry, eff_stop, config.STOP_SLIPPAGE)
        profit_usdt = (profit_pct / 100) * config.TRADE_AMOUNT_USDT
        is_win      = fill_price > entry
        if state.highest_target >= 2:
            reason = 'trailing_stop'
        elif state.highest_target == 1:
            reason = 'break_even'
        else:
            reason = 'stop_loss'
        original_stop_hit = (not is_win) and (fill_price <= cfg.stop_loss)
        await close_trade_barrier(
            trade, 'WIN' if is_win else 'LOSS',
            profit_pct, profit_usdt, fill_price,
            f"{reason} ({stop_label})", state.highest_target, original_stop_hit
        )
        return
```

Note: the only behavioral change vs the original is the exit is priced at `fill_price = eff_stop*(1-slippage)` instead of the overshot `current_price`. Time-based (24h / expiry) exits and the `MAX_OPEN_TRADES` forced close remain unchanged (they exit at market `current_price`, which is correct).

- [ ] **Step 3: Byte-compile check + full suite stays green**

Run: `research/skill_application/.venv/bin/python -m py_compile trade_tracker/main.py && research/skill_application/.venv/bin/python -m pytest tests/ -q`
Expected: compile OK; existing suite passes (no test regressions).

- [ ] **Step 4: Commit**

```bash
git add trade_tracker/main.py
git commit -m "fix(tracker): book stop exits at the stop level, not the overshot poll price"
```

---

### Task 4: Duplicate-guard clause in register_new_signals

**Files:**
- Modify: `trade_tracker/main.py` (import block; `register_new_signals` SELECT lines 173-195)

**Interfaces:**
- Consumes: `candle_interval_case_sql` (Task 1).

- [ ] **Step 1: Add the import**

Near the other `shared` imports in `trade_tracker/main.py`:

```python
from shared.candle import candle_interval_case_sql
```

- [ ] **Step 2: Add the cooldown clause to the SELECT**

Convert the `register_new_signals` query to an f-string and insert one more `NOT EXISTS` clause (mirrors the existing open-trade guard) immediately after the existing `NOT EXISTS (... at2 ... status='open')` block, before the blacklist clause:

```python
    candle_case = candle_interval_case_sql('s.timeframe')
    new_signals = await Database.fetch(f"""
        SELECT DISTINCT ON (s.symbol)
               s.id, s.symbol, s.entry_price, s.target_1, s.target_2, s.target_3,
               s.stop_loss, s.timeframe, s.is_paper_trade
        FROM signals s
        LEFT JOIN active_trades at ON s.id = at.signal_id
        WHERE s.telegram_sent = true
        AND s.claude_approved = true
        AND at.id IS NULL
        AND s.signal_time > NOW() - INTERVAL '2 hours'
        AND NOT EXISTS (
            SELECT 1 FROM active_trades at2
            WHERE at2.symbol = s.symbol AND at2.status = 'open'
        )
        AND NOT EXISTS (
            -- صفقة واحدة لكل (رمز، إطار) خلال فترة الشمعة — يمنع عدّ نفس الإعداد المُعاد إطلاقه مراراً
            SELECT 1 FROM active_trades at3
            WHERE at3.symbol = s.symbol
              AND at3.timeframe = s.timeframe
              AND at3.opened_at > NOW() - ({candle_case})
        )
        AND NOT EXISTS (
            SELECT 1 FROM approval_requests ar
            WHERE ar.signal_id = s.id AND ar.status = 'rejected'
        )
        AND s.symbol NOT IN (
            SELECT symbol FROM symbol_blacklist
        )
        ORDER BY s.symbol, s.signal_time DESC
    """)
```

Safety note: `candle_case` is generated from constant `CANDLE_SECONDS` only (no external input), so the f-string carries no injection risk. asyncpg positional params ($1…) appear only in the INSERT below, which is untouched.

- [ ] **Step 3: Byte-compile + full suite stays green**

Run: `research/skill_application/.venv/bin/python -m py_compile trade_tracker/main.py && research/skill_application/.venv/bin/python -m pytest tests/ -q`
Expected: compile OK; suite passes. (Live SQL behavior is validated on real data by the oracle in Task 5.)

- [ ] **Step 4: Commit**

```bash
git add trade_tracker/main.py
git commit -m "fix(tracker): one trade per (symbol,timeframe) per candle — kill pseudo-replication"
```

---

### Task 5: Validation oracle (offline, non-destructive)

**Files:**
- Create: `research/measurement_reanalysis.py`

**Interfaces:**
- Consumes: `candle_seconds`, `is_within_candle` (Task 1), `modeled_stop_exit` (Task 2).
- Produces: a printed before/after report; writes nothing to the DB.

- [ ] **Step 1: Write the oracle**

```python
# research/measurement_reanalysis.py
"""Non-destructive re-analysis of the recorded live-learning cohort: applies the
two recording fixes (dedup + modeled stop-fill) to EXISTING trades and prints the
before/after impact. Read-only — never writes to the DB. Run in the venv:

    research/skill_application/.venv/bin/python research/measurement_reanalysis.py
"""
import subprocess, io, sys
sys.path.insert(0, '.')
import pandas as pd
from shared.candle import candle_seconds, is_within_candle
from shared.triple_barrier import modeled_stop_exit

FEE_PCT = 0.6          # round-trip fee for net@fee
NOTIONAL = 50.0        # $ per trade
SLIPPAGE = 0.001       # match STOP_SLIPPAGE default

QUERY = """
COPY (
  SELECT tr.id, s.symbol, s.trade_type, s.timeframe,
         EXTRACT(EPOCH FROM s.signal_time) AS signal_ts,
         s.entry_price::float AS entry, s.stop_loss::float AS stop_loss,
         tr.profit_percent::float AS profit_percent, tr.stop_hit, tr.target_reached
  FROM trade_results tr JOIN signals s ON s.id = tr.signal_id
  WHERE s.trade_type IS NOT NULL
  ORDER BY s.signal_time
) TO STDOUT WITH CSV HEADER
"""


def load():
    out = subprocess.run(
        ["docker", "exec", "-i", "postgres", "psql", "-U", "trading_signal_bot",
         "-d", "trading_signals", "-A", "-c", QUERY],
        capture_output=True, text=True, check=True).stdout
    return pd.read_csv(io.StringIO(out))


def metrics(df, label):
    n = len(df)
    wr = 100.0 * (df.profit_percent > 0).mean() if n else 0.0
    gross = (df.profit_percent / 100 * NOTIONAL).sum()
    net = ((df.profit_percent - FEE_PCT) / 100 * NOTIONAL).sum()
    print(f"{label:22s} n={n:4d}  WR={wr:5.1f}%  gross=${gross:8.2f}  net@{FEE_PCT}%=${net:8.2f}")


def reprice_stops(df):
    df = df.copy()
    for i, r in df.iterrows():
        if not r.stop_hit:
            continue
        eff_stop = r.entry if r.target_reached >= 1 else r.stop_loss  # approx dynamic stop
        _, pct = modeled_stop_exit(r.entry, eff_stop, SLIPPAGE)
        df.at[i, 'profit_percent'] = pct
    return df


def dedup(df):
    keep, last = [], {}   # (symbol,timeframe) -> last kept signal_ts
    for r in df.itertuples():
        k = (r.symbol, r.timeframe)
        if k in last and is_within_candle(r.signal_ts, last[k], r.timeframe):
            continue
        keep.append(r.Index); last[k] = r.signal_ts
    return df.loc[keep]


def main():
    df = load()
    print("=== BEFORE (as recorded) ===")
    metrics(df, "overall")
    for t in sorted(df.trade_type.dropna().unique()):
        metrics(df[df.trade_type == t], f"  {t}")

    fixed = dedup(reprice_stops(df))
    print("\n=== AFTER (dedup + modeled stops) ===")
    metrics(fixed, "overall")
    for t in sorted(fixed.trade_type.dropna().unique()):
        metrics(fixed[fixed.trade_type == t], f"  {t}")

    print(f"\nrows: {len(df)} -> {len(fixed)}  (removed {len(df)-len(fixed)} pseudo-replicated)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the oracle and capture the true numbers**

Run: `research/skill_application/.venv/bin/python research/measurement_reanalysis.py`
Expected: a BEFORE block reproducing the audit (overall ≈ n=479, gross ≈ −$200) and an AFTER block with rows dropping ~479→~369 and gross rising toward ≈ −$42. Record the AFTER overall/momentum/reversion net numbers — these are the corrected picture.

- [ ] **Step 3: Commit**

```bash
git add research/measurement_reanalysis.py
git commit -m "feat(oracle): non-destructive re-analysis quantifying dedup + stop-fill impact"
```

---

## Done criteria
- `research/skill_application/.venv/bin/python -m pytest tests/ -q` — all green (new + existing).
- Oracle runs and shows rows ~479→~369 and the corrected gross/net per trade_type.
- Diff limited to: `shared/candle.py`, `shared/config.py`, `shared/triple_barrier.py`, `trade_tracker/main.py`, `tests/test_candle.py`, `tests/test_stop_fill.py`, `research/measurement_reanalysis.py`.
- No deploy performed; freeze + paused cron untouched. Deploy is a separate, user-authorized step.
