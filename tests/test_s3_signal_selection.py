"""S3: deterministic, explainable signal selection (s3-sel-v1, disabled, no production caller).

Synthetic candidates only. These tests prove engineering properties: gates, ranking, ties,
dedupe, NO_TRADE, audit records, isolation, and that the operational selector is unchanged.
They say nothing about which selection would be more profitable."""
import asyncio
import json
import pathlib
import random
import re
import sys; sys.path.insert(0, '.')

import pytest

from shared.candidate_selection import normalize
from shared.signal_selection import (ENABLED, NO_TRADE_REASONS, REASON_CODES, VERSION, S3Policy,
                                     compare_with_production, data_quality_reasons, rank_key,
                                     select_s3, select_s3_rows)

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAN, INF = float('nan'), float('inf')


def cand(symbol, tf="4h", spread=0.02, risk=2.0, tt="momentum", **kw):
    d = {"symbol": symbol, "timeframe": tf, "trade_type": tt, "stop_valid": True,
         "order_book": {"valid": True, "spread_pct": spread},
         "entry_price": 100.0, "stop_loss": 100.0 - risk, "target_1": 100.0 + risk,
         "target_2": 100.0 + 1.8 * risk, "target_3": 100.0 + 2.2 * risk, "atr": risk / 1.5}
    d.update(kw)
    return d


def C(symbol, liq=1e6, **kw):
    return normalize(cand(symbol, **kw), liq)


def pick(decision):
    s = decision.selected
    return (s.symbol, s.timeframe) if s else None


def rec_of(decision, symbol, tf="4h"):
    return next(r for r in decision.records if (r.symbol, r.timeframe) == (symbol, tf))


# ── ranking and ties ───────────────────────────────────────────────────────

def test_lower_cost_per_risk_wins_regardless_of_spread_or_liquidity_order():
    d = select_s3([C("AUSDT", liq=9e6, spread=0.01, risk=1.0), C("BUSDT", liq=1e5, spread=0.05, risk=3.0)])
    assert pick(d) == ("BUSDT", "4h")                     # 0.25/3.0 R < 0.21/1.0 R
    assert rec_of(d, "AUSDT").reasons == ("not_selected_capacity",)
    assert [r.rank for r in d.records] == [2, 1]


def test_spread_then_liquidity_break_equal_cost_per_risk():
    # identical cost/R needs identical cost and risk: same spread -> liquidity decides
    d = select_s3([C("AUSDT", liq=1e6), C("BUSDT", liq=5e6)])
    assert pick(d) == ("BUSDT", "4h")
    k_a = rank_key(C("AUSDT"), {"cost_over_risk": 0.1})
    k_b = rank_key(C("BUSDT", spread=0.01), {"cost_over_risk": 0.1})
    assert k_b < k_a                                       # same cost/R: tighter spread first


def test_full_ties_are_broken_by_hash_not_by_alphabet_and_are_order_invariant():
    cs = [C(f"{x}USDT") for x in "ZYXWVA"]
    picks = set()
    for seed in range(8):
        sh = cs[:]
        random.Random(seed).shuffle(sh)
        picks.add(pick(select_s3(sh)))
    assert len(picks) == 1
    order = sorted(cs, key=lambda c: rank_key(c, {"cost_over_risk": 0.1}))
    assert picks == {(order[0].symbol, "4h")}             # the hash decides, not the name
    assert [c.symbol for c in order] != sorted(c.symbol for c in cs)


def test_timeframes_compare_through_cost_per_risk_not_string_order():
    """Production breaks a symbol's multi-timeframe tie by the string ('15m' < '1d' < '4h')."""
    d = select_s3([C("AUSDT", tf="15m", risk=1.0), C("AUSDT", tf="1d", risk=3.0), C("AUSDT", tf="4h", risk=2.0)])
    assert pick(d) == ("AUSDT", "1d")
    assert rec_of(d, "AUSDT", "15m").reasons == ("duplicate_symbol_lower_rank",)
    assert rec_of(d, "AUSDT", "4h").reasons == ("duplicate_symbol_lower_rank",)


# ── missing data and invalid values ────────────────────────────────────────

@pytest.mark.parametrize("kw,reason", [
    ({"tt": None}, "no_trade_setup"),
    ({"tt": "scalp"}, "unknown_trade_type"),
    ({"stop_valid": None}, "stop_not_validated"),
    ({"stop_valid": False, "stop_reject_reason": "too_wide"}, "stop_rejected:too_wide"),
    ({"order_book": {"valid": False, "spread_pct": 0.02}}, "order_book_unavailable"),
    ({"order_book": {"valid": True}}, "order_book_unavailable"),
    ({"spread": NAN}, "spread_invalid"), ({"spread": INF}, "spread_invalid"),
    ({"spread": -0.01}, "spread_invalid"), ({"spread": 0.2}, "spread_exceeds_limit"),
    ({"target_2": None}, "bracket_missing"), ({"entry_price": NAN}, "bracket_non_finite"),
    ({"stop_loss": -1.0}, "bracket_non_finite"), ({"target_1": 99.0}, "bracket_not_ordered"),
    ({"target_2": 102.0}, "bracket_not_ordered"),          # t1 == t2: the tracker would refuse it
])
def test_mandatory_data_quality_gates(kw, reason):
    d = select_s3([C("AUSDT", **kw)])
    r = d.records[0]
    assert r.stage == "data" and reason in r.reasons and d.outcome == "NO_TRADE"


def test_unknown_liquidity_is_rejected_and_reported_all_reasons_at_once():
    c = C("AUSDT", liq=None, spread=NAN, stop_valid=None)
    assert data_quality_reasons(c, S3Policy()) == ("stop_not_validated", "spread_invalid", "liquidity_unknown")
    assert data_quality_reasons(C("AUSDT", liq=None), S3Policy(require_liquidity=False)) == ()


def test_invalid_values_never_raise_and_never_rank():
    for bad in (NAN, INF, -INF, "x", None, -5):
        d = select_s3([C("AUSDT", entry_price=bad), C("BUSDT")])
        assert pick(d) == ("BUSDT", "4h")


# ── rejected candidates: state and economics ───────────────────────────────

def test_state_gates():
    cs = [C("AUSDT"), C("BUSDT"), C("CUSDT", tt="reversion", tf="15m")]
    d = select_s3(cs, open_symbols={"AUSDT"}, cooldown={"BUSDT"}, throttled={("reversion", "15m")})
    assert d.outcome == "NO_TRADE" and d.no_trade_reason == "no_eligible_candidate"
    assert [r.reasons for r in d.records] == [("open_trade_exists",), ("symbol_cooldown",),
                                              ("learned_gate_throttled",)]


def test_economic_gates_reject_net_negative_t1_and_cost_burden():
    tight = select_s3([C("AUSDT", risk=0.15)])            # cost 0.22 % > the whole 0.15 % stop
    r = tight.records[0]
    assert r.stage == "economics" and "t1_path_net_non_positive" in r.reasons
    assert "cost_over_risk_exceeds_cap" in r.reasons and r.metrics["net_t1_path_pct"] <= 0
    burden = select_s3([C("AUSDT", risk=0.5)])             # 0.22/0.5 = 0.44 R > 0.25 R cap
    assert burden.records[0].reasons == ("cost_over_risk_exceeds_cap",)
    assert select_s3([C("AUSDT", risk=0.5)], policy=S3Policy(max_cost_over_risk=0.5)).outcome == "SELECTED"


def test_slippage_assumption_is_a_separate_declared_cost():
    base = select_s3([C("AUSDT", risk=1.0)]).records[0].metrics["cost_pct"]
    slip = select_s3([C("AUSDT", risk=1.0)], policy=S3Policy(slippage_roundtrip_pct=0.1)).records[0].metrics["cost_pct"]
    assert base == pytest.approx(0.22) and slip == pytest.approx(0.32)   # 20 bps fee + spread (+ slip)


# ── duplicates and NO_TRADE ────────────────────────────────────────────────

def test_duplicate_setup_keys_and_already_emitted_setups():
    k = {"setup_identity": {"key": "K1"}}
    d = select_s3([C("AUSDT", **k), C("BUSDT", risk=3.0, **k)])
    assert pick(d) == ("BUSDT", "4h") and rec_of(d, "AUSDT").reasons == ("duplicate_setup_key",)
    e = select_s3([C("AUSDT", **k)], emitted_keys={"K1"})
    assert e.records[0].reasons == ("setup_already_emitted",) and e.outcome == "NO_TRADE"


def test_explicit_no_trade_outcomes():
    empty = select_s3([])
    assert (empty.outcome, empty.no_trade_reason, empty.selected) == ("NO_TRADE", "empty_universe", None)
    none = select_s3([C("AUSDT", tt=None), C("BUSDT", spread=0.5)])
    assert none.no_trade_reason == "no_eligible_candidate"
    assert none.reason_counts == {"no_trade_setup": 1, "spread_exceeds_limit": 1}
    assert set(NO_TRADE_REASONS) == {"empty_universe", "no_eligible_candidate"}


# ── audit record, universe, policy ─────────────────────────────────────────

def test_audit_record_is_machine_readable_deterministic_and_uses_declared_codes():
    cs = [C("AUSDT", risk=0.5), C("BUSDT"), C("CUSDT", spread=NAN), C("BUSDT", tf="1d", risk=3.0)]
    a = select_s3(cs).to_dict()
    b = select_s3(list(reversed(cs))).to_dict()
    assert json.loads(json.dumps(a)) == a and a["input_digest"] == b["input_digest"]
    assert a["selected"] == b["selected"] == {"symbol": "BUSDT", "timeframe": "1d", "trade_type": "momentum"}
    used = {r.split(":", 1)[0] for c in a["candidates"] for r in c["reasons"]}
    assert used <= set(REASON_CODES)
    assert a["policy"]["enabled"] is False and a["version"] == VERSION == "s3-sel-v1"


def test_universe_is_bounded_without_alphabetical_truncation_and_reports_drops():
    rows = [{"symbol": f"S{i:03d}USDT", "timeframe": "4h",
             "analysis_data": json.dumps(cand(f"S{i:03d}USDT"))} for i in range(30)]
    liq = {r["symbol"]: 1e6 for r in rows}
    d = select_s3_rows(rows, liq, policy=S3Policy(max_universe_rows=10))
    assert d.universe["total"] == 30 and d.universe["considered"] == 10 and d.universe["capped"]
    assert len(d.universe["dropped"]) == 20
    kept = {r.symbol for r in d.records}
    assert kept != {f"S{i:03d}USDT" for i in range(10)}    # not the first 10 by name


def test_policy_validation_and_disabled_defaults():
    assert ENABLED is False and S3Policy().enabled is False
    with pytest.raises(ValueError, match="max_cost_over_risk_out_of_range"):
        select_s3([], policy=S3Policy(max_cost_over_risk=0))
    with pytest.raises(ValueError, match="strategy_version_required_for_integrity"):
        select_s3([], policy=S3Policy(enforce_integrity=True))
    with pytest.raises(ValueError, match="fee_roundtrip_pct_out_of_range"):
        select_s3([], policy=S3Policy(fee_roundtrip_pct=NAN))


def test_integrity_stage_uses_a44_freshness_when_enabled():
    pol = S3Policy(enforce_integrity=True, strategy_version="sb-test")
    d = select_s3([C("AUSDT")], policy=pol)
    assert d.records[0].reasons == ("integrity_inputs_missing",)
    d = select_s3([C("AUSDT")], policy=pol, decision_ms=1_800_000_000_000)
    assert d.records[0].stage == "integrity" and d.records[0].reasons[0].startswith("integrity:identity:")


# ── properties against the production selector ─────────────────────────────

def random_sets(n, seed):
    rng = random.Random(seed)
    for _ in range(n):
        cs = []
        for _ in range(rng.randint(0, 7)):
            c = cand(f"R{rng.randint(0, 9)}USDT", tf=rng.choice(["15m", "4h", "1d"]),
                     spread=rng.choice([0.01, 0.02, 0.05, 0.2, NAN]), risk=rng.choice([0.15, 0.3, 1.0, 2.5]),
                     tt=rng.choice(["momentum", "reversion", None]),
                     stop_valid=rng.choice([True, True, False, None]))
            if any(x.symbol == c["symbol"] and x.timeframe == c["timeframe"] for x in cs):
                continue
            cs.append(normalize(c, rng.choice([1e6, 3e6, None])))
        syms = {x.symbol for x in cs}
        yield cs, {"open_symbols": frozenset(s for s in syms if rng.random() < 0.15),
                   "cooldown": frozenset(s for s in syms if rng.random() < 0.15)}


def test_s3_eligible_set_is_a_subset_of_production_and_never_trades_when_production_cannot():
    """S3 only adds gates, so whenever S3 trades, production would have traded too."""
    from shared.candidate_selection import EligibilityPolicy, select
    for cs, state in random_sets(600, 7):
        prod = select(cs, policy=EligibilityPolicy(), ranker="production_parity", **state)
        s3 = select_s3(cs, **state)
        prod_ok = {id(c) for c, _, _ in prod.ranked}
        s3_ok = {id(c) for c, r in zip(cs, s3.records) if r.stage == "selection"}
        assert s3_ok <= prod_ok
        if s3.selected is not None:
            assert prod.selected is not None
            assert data_quality_reasons(s3.selected, S3Policy()) == ()


def test_offline_comparison_harness_is_consistent():
    sets = list(random_sets(400, 9))
    s = compare_with_production(sets)
    assert s.sets == 400 and s.s3_selected <= s.production_selected
    assert s.same_pick <= s.s3_selected
    assert s.s3_no_trade_where_production_traded == s.production_selected - s.s3_selected
    assert set(s.production_pick_rejected_by_s3) <= set(REASON_CODES)
    assert s.production_pick_rejected_by_s3            # the production pick is sometimes refused
    assert json.loads(json.dumps(s.to_dict())) == s.to_dict()


def test_selection_is_input_order_invariant():
    for cs, state in random_sets(150, 11):
        picks = set()
        for seed in range(4):
            sh = cs[:]
            random.Random(seed).shuffle(sh)
            picks.add(pick(select_s3(sh, **state)))
        assert len(picks) == 1


# ── compatibility: the operational selector is untouched ──────────────────

def test_production_paths_do_not_reference_s3():
    src = (ROOT / "signal_engine" / "signal_logic.py").read_text()
    assert "best = min(eligible, key=self._fixed_candidate_key)" in src
    for path in ROOT.glob("*/*.py"):
        if path.parts[-2] in ("tests", "research", "docs", "colab") or path.name == "signal_selection.py":
            continue
        assert not re.search(r"\bsignal_selection\b", path.read_text(encoding="utf-8", errors="ignore")), path
    from experimental_modules import EXPERIMENTAL_SHARED
    assert "signal_selection" in EXPERIMENTAL_SHARED


def test_pure_module_has_no_io_clock_or_learning():
    src = (ROOT / "shared" / "signal_selection.py").read_text()
    imports = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", src, re.M))
    assert not imports & {"time", "datetime", "random", "asyncio", "asyncpg", "aiohttp",
                          "shared.database", "shared.config"}


def test_harness_production_column_equals_the_real_live_selector(monkeypatch):
    """The comparison harness' production pick must be what the REAL find_best_signal_live
    selects (off mode, fake DB), so S3 is compared against the true operational baseline."""
    sys.path.insert(0, 'signal_engine')
    import signal_logic
    from shared.candidate_selection import EligibilityPolicy, select
    from shared.config import config
    from shared.database import Database

    class Macro:
        async def should_block_now(self): return False
        def macro_state_key(self): return 'usdtd_flat'
        def snapshot(self): return {}
        def state(self): return {}

    async def fetch(sql, *a):
        return []
    monkeypatch.setattr(Database, 'fetch', fetch)
    monkeypatch.setattr(config, 'ENABLE_EVIDENCE_RECORDER', False)
    monkeypatch.setattr(config, 'LEARNING_GATES_ENABLED', False)
    monkeypatch.setattr(config, 'SIGNAL_INTEGRITY_MODE', 'off', raising=False)
    rng = random.Random(53)
    compared = 0
    for _ in range(200):
        rows, vols = [], {}
        for _ in range(rng.randint(1, 6)):
            sym, tf = f"E{rng.randint(0, 4)}USDT", rng.choice(['15m', '4h', '1d'])
            if any(r['symbol'] == sym and r['timeframe'] == tf for r in rows):
                continue
            c = cand(sym, tf=tf, spread=rng.choice([0.01, 0.02, 0.2]), risk=rng.choice([0.3, 1.0, 2.5]),
                     tt=rng.choice(['momentum', 'reversion', None]))
            rows.append({'symbol': sym, 'timeframe': tf, 'analysis_data': json.dumps(c)})
            vols.setdefault(sym, rng.choice([1e6, 2e6, None]))
        eng = signal_logic.SignalEngine()

        async def vol(s):
            return vols.get(s)

        async def no_cd():
            return set()
        monkeypatch.setattr(eng, '_get_volume_usdt', vol)
        monkeypatch.setattr(eng, '_get_symbol_cooldown_set', no_cd)
        live = asyncio.run(eng.find_best_signal_live(rows, Macro()))
        cands = [normalize(r, vols.get(r['symbol'])) for r in rows]
        prod = select(cands, policy=EligibilityPolicy(), ranker="production_parity").selected
        live_pick = (live['symbol'], live['timeframe']) if live else None
        prod_pick = (prod.symbol, prod.timeframe) if prod else None
        assert live_pick == prod_pick
        compared += live is not None
    assert compared > 100
