"""Synthetic fixtures and registered suites of the WP-A04 golden replay harness.

Everything here is synthetic: invented symbols (``SYNTH*``), a synthetic venue, integer price
ticks and a toy rule with no market meaning. Every number is a fixture value picked only to reach
a code path. None is a proposal for a production parameter: freshness bounds (OF-OD-12), entry
thresholds, risk and capacity values stay owner decisions.

Registered suites (``SUITES``), one golden file each under ``tests/fixtures/golden_replay/``:

* ``wp2_synthetic_decision_replay``: the WP2 composite path bound to ``synthetic_rule``,
  strategy ``synthetic_golden 1.0.0``. Every F4 code the path can emit is reached at least once.
* ``wp2_synthetic_decision_replay_patch``: the same observations under the behaviour-identical
  rewrite ``synthetic_rule_refactored`` as ``1.0.1``. This is the SE-38 PATCH case: the identity
  moves and the decisions stay byte-identical.
* ``a44_enforce_integrity_step``: an existing, wired code path. The adapter calls
  ``shared.signal_identity`` exactly as the A44 enforce mode of ``SignalEngine.find_best_signal_live``
  does (``signal_engine/signal_logic.py:L375-392, L804-819 @ a03efdd``).

Adding a suite for another service path: put the adapter and its cases in a new module, then
pin it with ``python tests/golden_replay.py regenerate --suite <module>:<ATTR>`` from the
unchanged code. Do not add it to this module's ``SUITES`` from a parallel task.
"""
from __future__ import annotations

import copy
import inspect

import golden_replay as gr
from shared import decision_metadata as dm
from shared import funnel_records as fr
from shared import signal_identity as sid

MINUTE = 60_000
HOUR = 3_600_000
DAY = 86_400_000
T0 = 20_000 * DAY                          # a synthetic UTC day boundary
ACTIVATION = T0 + 2 * HOUR                 # whole UTC minute
VENUE = "synthetic_venue"
STRATEGY_ID = "synthetic_golden"
BAR_MS = {"15m": 15 * MINUTE, "1h": HOUR, "4h": 4 * HOUR}


def bar_close(open_ms: int, timeframe: str) -> int:
    """Venue close time: the last millisecond inside the bar (open + duration - 1)."""
    return open_ms + BAR_MS[timeframe] - 1


# ── the synthetic strategy (its source text is its closure) ────────────────────────────────

def synthetic_rule(closes, params):
    """SYNTHETIC toy rule with no market meaning: a setup when the last value is strictly above
    each of the WINDOW values before it. The payload comes from synthetic_bracket."""
    window = params["WINDOW"]
    prior = closes[-1 - window:-1]
    if closes[-1] <= max(prior):
        return None
    return synthetic_bracket(closes[-1], min(prior))


def synthetic_bracket(reference, lower):
    """SYNTHETIC payload in integer ticks, exact on every machine."""
    return {"reference": reference, "lower": lower, "upper": 2 * reference - lower}


def synthetic_rule_refactored(closes, params):
    """Behaviour-identical rewrite of synthetic_rule (the SE-38 PATCH fixture)."""
    window = params["WINDOW"]
    last = closes[len(closes) - 1]
    prior = list(closes[len(closes) - 1 - window:len(closes) - 1])
    highest = lowest = prior[0]
    for value in prior[1:]:
        highest = value if value > highest else highest
        lowest = value if value < lowest else lowest
    if not last > highest:
        return None
    return synthetic_bracket(last, lowest)


def synthetic_rule_changed(closes, params):
    """Behaviour-changing variant (a tie now counts as a setup): never a MINOR or PATCH step."""
    window = params["WINDOW"]
    prior = closes[-1 - window:-1]
    if closes[-1] < max(prior):
        return None
    return synthetic_bracket(closes[-1], min(prior))


ENTRY_PATH = "synthetic/entry.py"
GEOMETRY_PATH = "synthetic/geometry.py"


def code_for(entry) -> gr.ExecutedCode:
    return gr.bind_code(entry, {ENTRY_PATH: entry, GEOMETRY_PATH: synthetic_bracket})


WP2_CODE = code_for(synthetic_rule)
WP2_PATCH_CODE = code_for(synthetic_rule_refactored)
WP2_CHANGED_CODE = code_for(synthetic_rule_changed)

CONFIG_SCHEMA = {
    "schema_id": "synthetic/golden-replay-1",
    "keys": [
        {"name": "WINDOW", "kind": "int", "source": "code_constant", "choices": []},
        {"name": "SIGNAL_FRESHNESS_MAX_AGE_MS", "kind": "str", "source": "env", "choices": []},
    ],
}
CONFIG_VALUES = {"WINDOW": 3, "SIGNAL_FRESHNESS_MAX_AGE_MS": "15m=600000,1h=1800000"}
CONTRACT = {
    "input_spec": {"min_closed_bars": 4},
    "output_schema_versions": {"decision": dm.SCHEMA,
                               "rejection": f"{fr.SCHEMA}/{fr.SCHEMA_VERSION}"},
    "regime_providers": [],
    "cost_model_id": "synthetic_no_cost_v1",
    "fill_model_id": "synthetic_no_fill_v1",
    "holding_policy": "synthetic_not_applicable",
    "failure_criteria": "synthetic_not_applicable",
}


def closure_for(entry) -> list:
    return [
        {"path": ENTRY_PATH, "role": "synthetic entry rule",
         "regions": [["entry_rule", f"def:{entry.__name__}"]], "text": inspect.getsource(entry)},
        {"path": GEOMETRY_PATH, "role": "synthetic payload",
         "regions": [["geometry_bracket", "def:synthetic_bracket"]],
         "text": inspect.getsource(synthetic_bracket)},
    ]


def strategy(version="1.0.0", entry=synthetic_rule, lineage=(), **config) -> dict:
    return {"strategy_id": STRATEGY_ID, "version": version, "lineage": list(lineage),
            "closure": closure_for(entry), "config_schema": copy.deepcopy(CONFIG_SCHEMA),
            "config_values": {**CONFIG_VALUES, **config}, "contract": copy.deepcopy(CONTRACT)}


# ── the synthetic observations ─────────────────────────────────────────────────────────────

def obs(symbol, timeframe, close_ms, closes, completeness="complete") -> dict:
    return {"symbol": symbol, "timeframe": timeframe, "bar_close_ms": close_ms,
            "closes": list(closes), "completeness": completeness}


A_1H = (97, 100, 102, 101, 103, 106)
A_1H_REVISED = (97, 100, 102, 101, 103, 107)
B_1H_TIE = (100, 104, 102, 101, 103, 103)
FLAT = (100, 101, 102, 103)
H5 = bar_close(T0 + 4 * HOUR, "1h")        # the 1h bar [4h, 5h) of day T0


def cycles() -> list:
    return [
        {"cycle_id": "c1", "decision_time_ms": T0 + 5 * HOUR + 5 * MINUTE, "observations": [
            obs("SYNTHA", "1h", H5, A_1H),                                   # candidate
            obs("SYNTHA", "15m", H5, (50, 51, 52, 53)),                      # candidate, other timeframe
            obs("SYNTHB", "1h", H5, B_1H_TIE),                               # tie: F4.no_setup
            obs("SYNTHC", "1h", H5, FLAT, "gap"),                            # F4.data_quality (strategy.input)
            obs("SYNTHD", "1h", H5, (100, 101, 102)),                        # F4.history_insufficient (bars)
            obs("SYNTHE", "1h", H5, FLAT, "insufficient_history"),           # F4.history_insufficient (flag)
            obs("SYNTHF", "1h", ACTIVATION - 1, FLAT),                       # F4.bar_before_version_activation
            obs("SYNTHG", "1h", H5 - 1, FLAT),                               # F4.data_quality: not aligned
            obs("SYNTHH", "1h", bar_close(T0 + 5 * HOUR, "1h"), FLAT),       # F4.bar_not_closed
            obs("SYNTHI", "1h", bar_close(T0 + 3 * HOUR, "1h"), FLAT),       # F4.bar_stale (65 min)
            obs("SYNTH-J", "1h", H5, FLAT),                                  # F4.data_quality: symbol
            obs("SYNTHK", "2h", H5, FLAT),                                   # F4.data_quality: timeframe
        ]},
        {"cycle_id": "c2", "decision_time_ms": T0 + 5 * HOUR + 20 * MINUTE, "observations": [
            obs("SYNTHA", "1h", H5, A_1H),                                   # F4.duplicate_setup
            obs("SYNTHA", "15m", H5, (50, 51, 52, 53)),                      # F4.bar_stale before the claim
            obs("SYNTHA", "15m", bar_close(T0 + 5 * HOUR, "15m"), (51, 52, 53, 55)),   # candidate
        ]},
        {"cycle_id": "c3", "decision_time_ms": T0 + 5 * HOUR + 25 * MINUTE, "observations": [
            obs("SYNTHA", "1h", H5, A_1H_REVISED),                           # F4.setup_conflict
        ]},
        {"cycle_id": "c4", "decision_time_ms": T0 + 5 * HOUR + 28 * MINUTE, "observations": [
            obs("SYNTHA", "1h", H5, A_1H),          # F4.duplicate_setup: the first payload was kept
            obs("SYNTHB", "1h", H5, B_1H_TIE),                               # F4.no_setup again
        ]},
    ]


def scenario(scenario_id="baseline", **strategy_kw) -> dict:
    """A fresh, mutable copy of the baseline scenario (tests change it freely)."""
    return {"scenario_id": scenario_id, "venue": VENUE, "activation_ms": ACTIVATION,
            "strategy": strategy(**strategy_kw), "cycles": cycles()}


def patch_scenario() -> dict:
    return scenario("baseline_patch_1_0_1", version="1.0.1", entry=synthetic_rule_refactored,
                    lineage=(f"{STRATEGY_ID}/1.0.0",))


# ── an existing service code path: the A44 enforce-mode integrity step ─────────────────────

def a44_enforce_integrity_step(case: dict) -> dict:
    """Adapter around the wired A44 integrity step of ``SignalEngine.find_best_signal_live``.

    It calls the production functions of ``shared.signal_identity`` with the production arguments
    (``allow_pit_fallback=False``) and the production composition: the first reason decides
    (``signal_engine/signal_logic.py:L804-812 @ a03efdd``) and an admissible candidate carries the
    ``setup_identity`` block of L814-819. Only the database lookup of already-emitted keys
    (L375-392) is replaced by the case's synthetic ``emitted`` candidates; an emitted candidate
    that cannot be identified is skipped, as there. Candidate order is the case order (rows in
    query order), so this path is order-dependent by design and is not normalized."""
    version = case["strategy_version"]
    emitted = set()
    for data in case["emitted"]:
        try:
            emitted.add(sid.identity_from_candidate(data, strategy_version=version,
                                                    allow_pit_fallback=False).key)
        except sid.IdentityError:
            pass
    emitted = frozenset(emitted)
    rows = []
    for data in case["candidates"]:
        verdict = sid.integrity_check(data, decision_ms=case["decision_ms"], strategy_version=version,
                                      emitted_keys=emitted, allow_pit_fallback=False)
        row = {"symbol": data.get("symbol"), "eligible": verdict.eligible,
               "reasons": list(verdict.reasons), "key": verdict.key, "freshness": verdict.freshness,
               "setup_identity": None}
        if verdict.eligible:
            ident = sid.identity_from_candidate(data, strategy_version=version, allow_pit_fallback=False)
            row["setup_identity"] = {"version": sid.IDENTITY_VERSION, "key": ident.key,
                                     "bracket_hash": sid.bracket_hash(data),
                                     "candle_open_time_ms": ident.candle_open_ms,
                                     "candle_close_time_ms": ident.candle_close_ms}
            row["decision"] = "admissible"
        else:
            row["decision"] = f"rejected_{verdict.reasons[0]}"
        rows.append(row)
    return {"emitted_keys": sorted(emitted), "rows": rows}


def a44_candidate(symbol, timeframe, open_ms, *, trade_type="momentum", block="identity", **over) -> dict:
    """A synthetic analyzer candidate: candle block as the analyzer writes it, bracket in halves."""
    step = BAR_MS.get(timeframe, HOUR)
    data = {"symbol": symbol, "timeframe": timeframe, "trade_type": trade_type,
            "entry_price": 101.5, "stop_loss": 100.0, "target_1": 103.0, "target_2": 104.5,
            "target_3": 106.0, "stop_policy": "synthetic_stop_v1"}
    candle = {"version": 1, "candle_open_time_ms": open_ms, "candle_close_time_ms": open_ms + step - 1}
    if block == "identity":
        data["candle_identity"] = candle
    elif block == "pit":
        data["pit"] = candle
    data.update(over)
    return data


A44_VERSION = "synthetic-release-1"
H4 = T0 + 4 * HOUR


def a44_cases() -> tuple:
    fresh_ms = T0 + 5 * HOUR + 10 * MINUTE
    return (
        gr.GoldenCase("fresh_cycle", {
            "decision_ms": fresh_ms, "strategy_version": A44_VERSION,
            "emitted": [a44_candidate("SYNTHA", "1h", H4)],
            "candidates": [
                a44_candidate("SYNTHA", "1h", H4),                               # duplicate_setup
                a44_candidate("SYNTHB", "1h", H4),                               # admissible
                a44_candidate("SYNTHB", "1h", H4, selection_policy="synthetic_policy_v1"),  # other key
                a44_candidate("SYNTHC", "15m", T0 + 4 * HOUR + 45 * MINUTE),     # admissible, 10 min
                a44_candidate("SYNTHD", "4h", H4),                               # bar still forming
                a44_candidate("SYNTHE", "1h", T0 + 3 * HOUR),                    # superseded (70 min)
                a44_candidate("SYNTHF", "1h", H4, trade_type="reversion"),       # admissible
            ]}),
        gr.GoldenCase("identity_failures", {
            "decision_ms": fresh_ms, "strategy_version": A44_VERSION, "emitted": [],
            "candidates": [
                a44_candidate("SYNTHA", "1h", H4, block="pit"),                  # candle_identity_missing
                a44_candidate("SYNTHB", "1h", H4, block=None,
                              candle_identity_error="candle_bounds_unavailable"),
                a44_candidate("SYNTHC", "1h", H4 + MINUTE),                      # open not aligned
                a44_candidate("SYNTHD", "1h", H4, candle_identity={
                    "version": 1, "candle_open_time_ms": H4, "candle_close_time_ms": H4 + HOUR}),
                a44_candidate("SYNTHE", "2h", H4),                               # timeframe_unknown
                a44_candidate("SYNTHF", "1h", H4, trade_type=None),              # trade_type_missing
                a44_candidate("", "1h", H4),                                     # symbol_missing
                a44_candidate("SYNTHG", "1h", H4, candle_identity={              # digit strings: accepted
                    "version": 1, "candle_open_time_ms": str(H4),
                    "candle_close_time_ms": str(H4 + HOUR - 1)}),
                a44_candidate("SYNTHH", "1h", H4, candle_identity={              # integral floats: accepted
                    "version": 1, "candle_open_time_ms": float(H4),
                    "candle_close_time_ms": float(H4 + HOUR - 1)}),
            ]}),
        gr.GoldenCase("late_cycle", {
            "decision_ms": T0 + 6 * HOUR + MINUTE, "strategy_version": A44_VERSION,
            "emitted": [a44_candidate("SYNTHA", "1h", H4), a44_candidate("SYNTHZ", "1h", H4, block="pit")],
            "candidates": [
                a44_candidate("SYNTHA", "1h", H4),             # stale and duplicate: freshness decides
                a44_candidate("SYNTHA", "1h", T0 + 5 * HOUR),  # the next bar: admissible
            ]}),
    )


A44_PATH = gr.GoldenPath(
    path_id="a44_enforce_integrity_step", run=a44_enforce_integrity_step,
    code_refs=("shared/signal_identity.py", "signal_engine/signal_logic.py"),
    description="A44 enforce-mode integrity step (identity, freshness, duplicate) on synthetic candidates")

# ── registered suites ──────────────────────────────────────────────────────────────────────

WP2_SUITE = gr.GoldenSuite(
    gr.wp2_decision_path("wp2_synthetic_decision_replay", WP2_CODE,
                         description="WP2 composite decision replay, synthetic_golden 1.0.0"),
    (gr.GoldenCase("baseline", scenario()),))
WP2_PATCH_SUITE = gr.GoldenSuite(
    gr.wp2_decision_path("wp2_synthetic_decision_replay_patch", WP2_PATCH_CODE,
                         description="WP2 composite decision replay, behaviour-identical refactor 1.0.1"),
    (gr.GoldenCase("baseline_patch_1_0_1", patch_scenario()),))
A44_SUITE = gr.GoldenSuite(A44_PATH, a44_cases())
SUITES = (WP2_SUITE, WP2_PATCH_SUITE, A44_SUITE)
