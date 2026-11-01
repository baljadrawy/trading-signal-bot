"""WP-B05 / R1: SELECTION_POLICY flag, legacy byte-identity and the rank-then-limit policy.

R1 tests 1-6 of REMEDIATION_REGISTER.md, on synthetic rows only.
"""
import ast
import copy
import hashlib
import json
import os
import random
import subprocess
import sys

import pytest

from funnel_service_harness import ROOT, events
from shared import selection_policy as sp
from test_funnel_records import engine_scenario, legacy_order, run_engine

LEGACY_LITERAL_SHA256 = "4d3cf4b525cb5459104e33a3eb5cac2b82228c059d5d19cfb46d6492748e2853"   # @ af319bb
DECLARED = {"SELECTION_POLICY": "rank_then_limit_v1", "SELECTION_VERSION": "sel-test.1",
            "SELECTION_SCORE_KEY": "total_score:higher_first"}


def _rows(n, rng, score_pool=None, symbol=lambda i: f"S{i:04d}USDT"):
    rows = []
    for i in range(n):
        tf = ("15m", "4h", "1d")[i % 3]
        score = rng.choice(score_pool) if score_pool else round(rng.uniform(0, 10), 6)
        rows.append({"symbol": symbol(i // 3), "timeframe": tf,
                     "analysis_data": {"symbol": symbol(i // 3), "timeframe": tf, "total_score": score,
                                       "trade_type": "momentum", "feature": i}})
    return rows


def _policy(version="sel-test.1", key="total_score:higher_first"):
    return sp.selection_policy_from_env({"SELECTION_POLICY": "rank_then_limit_v1",
                                         "SELECTION_VERSION": version, "SELECTION_SCORE_KEY": key})


# ── flag ────────────────────────────────────────────────────────────────────────────────────

def test_default_is_legacy_and_unknown_or_undeclared_refuses():
    assert sp.selection_policy_from_env({}).is_legacy
    assert sp.selection_policy_from_env({"SELECTION_POLICY": " Legacy "}).is_legacy
    assert sp.selection_policy_from_env({"SELECTION_POLICY": "legacy", "SELECTION_SCORE_KEY": "x"}).score_key is None
    for env, match in (({"SELECTION_POLICY": "ranked"}, "unknown SELECTION_POLICY"),
                       ({"SELECTION_POLICY": "rank_then_limit_v1"}, "owner-declared"),
                       ({**DECLARED, "SELECTION_VERSION": ""}, "owner-declared"),
                       ({**DECLARED, "SELECTION_SCORE_KEY": ""}, "owner-declared"),
                       ({**DECLARED, "SELECTION_VERSION": "Bad Version"}, "malformed SELECTION_VERSION"),
                       ({**DECLARED, "SELECTION_SCORE_KEY": "total_score"}, "malformed SELECTION_SCORE_KEY"),
                       ({**DECLARED, "SELECTION_SCORE_KEY": "total_score:best"}, "malformed SELECTION_SCORE_KEY"),
                       ({**DECLARED, "SELECTION_SCORE_KEY": "Total:higher_first"}, "malformed")):
        with pytest.raises(RuntimeError, match=match):
            sp.selection_policy_from_env(env)
    p = sp.selection_policy_from_env(DECLARED)
    assert (p.name, p.selection_version, p.score_field, p.score_direction) == (
        "rank_then_limit_v1", "sel-test.1", "total_score", "higher_first")
    with pytest.raises(ValueError):
        sp.rank_then_limit([], sp.SelectionPolicy("legacy"), 200)


def test_service_refuses_an_undeclared_policy_before_any_io(monkeypatch):
    from funnel_service_harness import FakeDB, load_service, run_main
    mod = load_service("signal_engine")
    db = FakeDB(lambda *a: [])
    db.install(monkeypatch)
    monkeypatch.setenv("FUNNEL_RECORDING", "off")
    monkeypatch.setenv("SELECTION_POLICY", "rank_then_limit_v1")
    with pytest.raises(RuntimeError, match="SELECTION_POLICY"):
        run_main(mod)
    assert db.calls == []


# ── R1 test 3: default byte-identity ────────────────────────────────────────────────────────

def test_legacy_query_literal_and_limit_are_unchanged():
    src = (ROOT / "signal_engine" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    lits = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "LIMIT 200" in n.value]
    assert len(lits) == 1 and hashlib.sha256(lits[0].encode()).hexdigest() == LEGACY_LITERAL_SHA256
    limits = [n for n in tree.body if isinstance(n, ast.Assign)
              and any(getattr(t, "id", None) == "SELECTION_LIMIT" for t in n.targets)]
    assert len(limits) == 1 and ast.literal_eval(limits[0].value) == 200


@pytest.mark.parametrize("seed", [5, 9, 17])
def test_legacy_default_issues_exactly_the_legacy_query(seed, monkeypatch):
    sc = engine_scenario(seed)
    off = run_engine(monkeypatch, sc, on=False)
    sqls = [c[1] for c in off["db"].calls if c[0] == "fetch"]
    assert hashlib.sha256(sqls[0].encode()).hexdigest() == LEGACY_LITERAL_SHA256
    assert off["mod"]._RANKED_CANDIDATES_SQL not in sqls


# ── R1 tests 1, 2, 4, 5, 6 on the pure function ─────────────────────────────────────────────

@pytest.mark.parametrize("n", [0, 1, 199, 200, 201, 1000])
def test_name_order_invariance_and_no_silent_drop(n):
    rng = random.Random(n)
    rows = _rows(n, rng)
    picked = sp.rank_then_limit(rows, _policy(), 200)
    assert len(picked.rows) + len(picked.cut) == n                           # R1 test 2
    assert len(picked.rows) == min(n, 200)
    features = lambda sel: sorted(sp.row_data(r)["feature"] for r in sel.rows)
    renamed = copy.deepcopy(rows)
    names = sorted({r["symbol"] for r in rows})
    shuffled = names[:]
    random.Random(n + 1).shuffle(shuffled)
    mapping = dict(zip(names, (f"Z{s[::-1]}" for s in shuffled)))
    for r in renamed:
        r["symbol"] = r["analysis_data"]["symbol"] = mapping[r["symbol"]]
    assert features(sp.rank_then_limit(renamed, _policy(), 200)) == features(picked)   # R1 test 1


def test_exact_ties_follow_the_declared_tie_break_key_and_timeframe_is_not_string_order():
    rows = _rows(3, random.Random(0), score_pool=[5.0])                      # one symbol, 15m/4h/1d tie
    orders = set()
    for version in ("v-a", "v-b", "v-c", "v-d", "v-e"):
        picked = sp.rank_then_limit(rows, _policy(version), 1)
        keys = [r.tie_break_key for r in picked.ranked]
        assert keys == sorted(keys)                                           # R1 test 5
        orders.add(tuple(r.timeframe for r in picked.ranked))
    assert len(orders) > 1                                                    # never lexical '15m'<'1d'<'4h'


def test_collation_and_input_order_independence_and_determinism():
    rows = _rows(600, random.Random(3), score_pool=[1.0, 2.0, 3.0])
    base = [(r.symbol, r.timeframe, r.rank) for r in sp.rank_then_limit(rows, _policy(), 200).ranked]
    for seed in range(5):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        assert [(r.symbol, r.timeframe, r.rank)
                for r in sp.rank_then_limit(shuffled, _policy(), 200).ranked] == base   # R1 test 6
    code = ("import json, random, sys; sys.path[:0] = ['.', 'tests']; from shared import selection_policy as sp;"
            "from test_selection_rank_then_limit import _rows, _policy;"
            "rows = _rows(600, random.Random(3), score_pool=[1.0, 2.0, 3.0]);"
            "print(json.dumps([[r.symbol, r.timeframe, r.rank] for r in sp.rank_then_limit(rows, _policy(), 200).ranked]))")
    outs = {subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True,
                           env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": seed, "HOME": "/tmp",
                                "PYTHONDONTWRITEBYTECODE": "1"}).stdout for seed in ("1", "2")}
    assert len(outs) == 1 and json.loads(outs.pop()) == [list(x) for x in base]        # R1 test 4


def test_direction_missing_scores_and_identical_set_under_the_limit():
    rows = _rows(9, random.Random(1))
    rows[0]["analysis_data"]["total_score"] = None
    rows[1]["analysis_data"]["total_score"] = "nan"
    hi = sp.rank_then_limit(rows, _policy(), 100)
    lo = sp.rank_then_limit(rows, _policy(key="total_score:lower_first"), 100)
    scored = lambda sel: [r.score for r in sel.ranked if r.score is not None]
    assert scored(hi) == sorted(scored(hi), reverse=True) and scored(lo) == sorted(scored(lo))
    assert [r.score_missing for r in hi.ranked][-2:] == [True, True]
    assert {id(r) for r in hi.rows} == {id(r) for r in rows}                  # <= limit: same rows as legacy
    assert hi.truncation_info()["score_missing"] == 2


def test_tie_break_basis_equals_the_reviewed_a43_rule():
    from shared.candidate_selection import SELECTION_VERSION, _tie_hash, normalize
    rng = random.Random(4)
    for row in _rows(30, rng):
        if rng.random() < 0.5:
            row["analysis_data"]["pit"] = {"candidate_id": f"cid-{rng.random()}"}
        if rng.random() < 0.2:
            row["analysis_data"]["trade_type"] = None
        c = normalize(row)
        assert sp.tie_break_key(SELECTION_VERSION, row["analysis_data"], c.symbol, c.timeframe) == _tie_hash(c)


# ── integration: the declared policy in the real signal_engine loop ─────────────────────────

@pytest.mark.parametrize("seed", [2, 5, 11, 17, 23])
def test_declared_policy_ranks_all_rows_keeps_the_limit_and_records_the_cut(seed, monkeypatch):
    sc = engine_scenario(seed)
    off = run_engine(monkeypatch, sc, on=False, extra_env=DECLARED)
    on = run_engine(monkeypatch, sc, on=True, extra_env=DECLARED)
    assert on["trace"] == off["trace"] and on["saved"] == off["saved"]        # recording stays observe-only
    sqls = [c[1] for c in off["db"].calls if c[0] == "fetch"]
    assert sqls[0] == off["mod"]._RANKED_CANDIDATES_SQL
    assert not any("LIMIT 200" in q for q in sqls)
    picked = sp.rank_then_limit(sc["rows"], _policy("sel-test.1"), 200)
    recs = [e["payload"] for e in events(on["rec"], "funnel.rejection")
            if e["payload"]["reason_code"] == "F6.rank_below_cap" and e["payload"]["detail"].get("cap")]
    assert sorted(r["rank"] for r in recs) == [r.rank for r in picked.cut]
    assert all(r["detail"]["offer_cap"] == 200 and r["detail"]["selection_version"] == "sel-test.1"
               for r in recs)
    if not sc["rows"]:
        return
    env = events(on["rec"], "funnel.cycle")[0]["payload"]
    assert env["notes"]["selection"]["returned"] == min(200, len(sc["rows"]))
    if len(sc["rows"]) <= 200 and sc["macro"] == "ok":
        legacy = run_engine(monkeypatch, sc, on=False)
        assert legacy["saved"] == off["saved"]                                # same set => same pick
