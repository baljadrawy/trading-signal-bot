"""SE-84 / DG-35 (HOLD): synthetic conflict cases for the candidate ``setup_key`` compositions.

PROPOSAL EVIDENCE ONLY. Nothing here is activated or integrated, and no service imports this
file. The proposal itself is ``docs/design/SETUP_KEY_PROPOSAL_SE84.md``.

Compositions under review:

* **A: strategy version in the key.** The iteration-1 key
  ``shared.signal_integrity_v2.setup_key_v2``, used exactly as it is: (venue, symbol,
  strategy_id, strategy_version, rule_hash, timeframe, bar close, direction). The bracket is
  the payload. Cross-version re-fire is stopped by the
  SE-36 activation-minute rule (``version_boundary_reason``), not by the key.
* **B: strategy version excluded from the key, with the same boundary rule.** No such key
  function exists, so ``key_b`` / ``payload_b`` below are PROPOSAL HELPERS, defined only in this
  test file. The key drops strategy_version and rule_hash; both move into the payload, so the
  same bar under another version is a conflict by construction.

Every input is synthetic; datetimes are built with ``datetime(...)`` and arithmetic. These tests
show identity properties only. They say nothing about market behaviour or profitability.
"""
import sys; sys.path.insert(0, '.')
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest

from shared import signal_identity as a44
from shared import signal_integrity_v2 as v2
from shared.strategy_identity import StrategyVersion

UTC = timezone.utc
TF = dict(a44.TIMEFRAME_MS)
T0 = datetime(2026, 10, 1, tzinfo=UTC)
EMIT = "emit"

SV1 = StrategyVersion("momentum_breakout", "1.0.0", "11" * 32, "22" * 32, "33" * 32,
                      lineage=("legacy_research_contract", "synthetic"))
SV2 = StrategyVersion("momentum_breakout", "2.0.0", "44" * 32, "22" * 32, "33" * 32,
                      lineage=("momentum_breakout/1.0.0",))
BRACKET = {"entry_price": 100.0, "stop_loss": 98.0, "target_1": 103.0, "target_2": 105.0,
           "target_3": 108.0, "stop_policy": "synthetic_v1"}
KEY_FIELDS = ("venue", "symbol", "strategy_id", "strategy_version", "rule_hash", "timeframe",
              "bar_close_ms", "direction")


def ms(moment):
    return v2.epoch_ms(moment)


def close_ms(open_dt, tf):
    """Venue close ms (last ms inside the bar) of the bar opening at ``open_dt``."""
    return ms(open_dt) + TF[tf] - 1


def rule_of(sv):
    """What a key needs from a StrategyVersion: semver and identity hash (lineage excluded)."""
    return {"strategy_id": sv.strategy_id, "strategy_version": sv.version,
            "rule_hash": sv.identity_hash}


def cand(sv=SV1, **over):
    c = dict(venue="binance", symbol="BTCUSDT", timeframe="4h", bar_close_ms=close_ms(T0, "4h"),
             direction="long", bracket=dict(BRACKET), **rule_of(sv))
    c.update(over)
    return c


# ── composition A: the existing key, unchanged ──────────────────────────────

def key_a(c):
    return v2.setup_key_v2(**{f: c[f] for f in KEY_FIELDS})


def payload_a(c):
    return v2.payload_hash({"bracket": c["bracket"]})


# ── composition B: PROPOSAL HELPERS (SE-84 review only; not a production API) ──

B_KEY_VERSION = "se84-sid-b1"       # proposal namespace; never written anywhere
B_PREFIX = "skb_"


def key_b(c):
    """PROPOSAL HELPER. Every input is validated by the existing v2 types, including the
    strategy version and rule hash that the key leaves out (fail closed), then hashed with the
    existing canonical hash."""
    sk = v2.SetupKeyV2(c["venue"], v2.CandleRef(c["symbol"], c["timeframe"], c["bar_close_ms"]),
                       v2.RuleIdentity(c["strategy_id"], c["strategy_version"], c["rule_hash"]),
                       c["direction"])
    return B_PREFIX + v2.payload_hash([B_KEY_VERSION, sk.venue, sk.candle.symbol,
                                       sk.rule.strategy_id, sk.candle.timeframe,
                                       sk.candle.bar_close_ms, sk.direction])[:40]


def payload_b(c):
    """PROPOSAL HELPER. The rule identity is part of the payload, so a second version on the
    same bar can never match the first payload."""
    rule = v2.RuleIdentity(c["strategy_id"], c["strategy_version"], c["rule_hash"])
    return v2.payload_hash({"rule": [rule.strategy_version, rule.rule_hash],
                            "bracket": c["bracket"]})


@dataclass(frozen=True)
class Composition:
    name: str
    key: Callable
    payload: Callable


A = Composition("A_version_in_key", key_a, payload_a)
B = Composition("B_version_excluded", key_b, payload_b)
BOTH = pytest.mark.parametrize("comp", [A, B], ids=lambda c: c.name)


def f4_identity(comp, ledger, c, *, activation_ms, boundary_rule=True):
    """Model of the proposed F4 identity stage: key and payload first (fail closed), then the
    SE-36 activation-minute rule, then insert-once. ``boundary_rule=False`` exists only to show
    the hazard the rule removes; the proposal makes the rule mandatory for both compositions."""
    key, payload = comp.key(c), comp.payload(c)
    if boundary_rule:
        reason = v2.version_boundary_reason(bar_close_ms=c["bar_close_ms"],
                                            activation_ms=activation_ms)
        if reason is not None:
            return reason, ledger
    claim, ledger = v2.register_claim(ledger, key, payload)
    return (EMIT if claim.status == v2.NEW else claim.reason_code), ledger


def canonical_symbol(raw):
    """PROPOSAL HELPER for the upstream (F0) adapter: case and surrounding blanks only. Separator
    variants such as BTC-USDT need the venue's own listing and stay refused."""
    return raw.strip().upper() if isinstance(raw, str) else raw


def canonical_venue(raw):
    """PROPOSAL HELPER for the upstream adapter: venue identifiers are lowercase names."""
    return raw.strip().lower() if isinstance(raw, str) else raw


# ── pins: composition A is the iteration-1 key; B has its own namespace ─────

def test_composition_a_is_the_iteration1_key_unchanged():
    c = cand(rule_hash="ab" * 32, strategy_version="1.0.0")
    assert key_a(c) == "sk2_4ca8d606693ab978d0d16e3d17ed6472af4221e1"    # pinned in iteration 1
    expected = "sk2_" + v2.payload_hash([v2.SETUP_KEY_VERSION, "binance", "BTCUSDT",
                                         "momentum_breakout", "1.0.0", "ab" * 32, "4h",
                                         close_ms(T0, "4h"), "long"])[:40]
    assert key_a(c) == expected                     # direction and both version fields are hashed


def test_composition_b_key_is_pinned_and_version_free():
    c = cand(rule_hash="ab" * 32, strategy_version="1.0.0")
    assert key_b(c) == "skb_023354e622e5eb9a50b858823cab3c97da8e4c16"
    assert key_b(c) == key_b(cand(SV2)) == key_b(cand(SV1))
    assert len({key_b(c) for _ in range(20)}) == 1


def test_key_namespaces_are_disjoint_from_a44():
    ident = a44.SetupIdentity("BTCUSDT", "4h", ms(T0), close_ms(T0, "4h"), "momentum", "long",
                              "sb-2026.08", "fixed_execution_quality_v1")
    keys = {ident.key, key_a(cand()), key_b(cand())}
    assert len(keys) == 3
    assert {k.split("_")[0] for k in keys} == {"sk", "sk2", "skb"}
    assert {len(k) for k in keys} == {43, 44}             # all fit migration 011's TEXT column
    assert all(k.isascii() for k in keys)


# ── 1. same bar, same setup: duplicate ──────────────────────────────────────

@BOTH
@pytest.mark.parametrize("tf,repeats", [("1d", 12), ("4h", 2)])
def test_same_bar_same_setup_is_a_duplicate(comp, tf, repeats):
    """R3 test 1 model: one closed bar re-analysed every 2 h for its life, restart halfway."""
    c = cand(timeframe=tf, bar_close_ms=close_ms(T0, tf))
    activation = ms(T0 - timedelta(days=1))
    ledger, outcomes = {}, []
    for i in range(repeats):
        if i == repeats // 2:
            ledger = dict(ledger)                        # restart: the store keeps its keys
        out, ledger = f4_identity(comp, ledger, c, activation_ms=activation)
        outcomes.append(out)
    assert outcomes == [EMIT] + [v2.DUPLICATE_SETUP] * (repeats - 1)
    assert ledger == {comp.key(c): comp.payload(c)}
    assert v2.rejection_fields(v2.DUPLICATE_SETUP)["sub_stage"] == "shared.identity"


# ── 2. same key, different payload: conflict ────────────────────────────────

@BOTH
def test_same_key_different_payload_is_a_conflict(comp):
    first, recomputed = cand(), cand(bracket={**BRACKET, "stop_loss": 97.5})
    assert comp.key(first) == comp.key(recomputed)          # bracket prices are never keyed
    activation = ms(T0 - timedelta(days=1))
    seq = [first, recomputed, recomputed, first]
    outs, ledger = [], {}
    for c in seq:
        out, ledger = f4_identity(comp, ledger, c, activation_ms=activation)
        outs.append(out)
    assert outs == [EMIT, v2.SETUP_CONFLICT, v2.SETUP_CONFLICT, v2.DUPLICATE_SETUP]
    assert ledger == {comp.key(first): comp.payload(first)}   # the first payload is never replaced
    report = v2.detect_duplicates([(comp.key(c), comp.payload(c)) for c in seq])
    assert [(x.first_index, x.index) for x in report.conflicts] == [(0, 1), (0, 2)]


# ── 3. version bump on the same bar ─────────────────────────────────────────

LABEL_ONLY = StrategyVersion("momentum_breakout", "1.0.1", "11" * 32, "22" * 32, "33" * 32)
UNDECLARED = StrategyVersion("momentum_breakout", "1.0.0", "55" * 32, "22" * 32, "33" * 32)


@pytest.mark.parametrize("comp,expected", [(A, EMIT), (B, v2.SETUP_CONFLICT)],
                         ids=["A_version_in_key", "B_version_excluded"])
@pytest.mark.parametrize("bumped", [SV2, LABEL_ONLY, UNDECLARED],
                         ids=["major_rule_change", "label_only", "undeclared_hash_change"])
def test_version_bump_on_the_same_bar_without_the_boundary_rule(comp, expected, bumped):
    """With the activation-minute rule switched off, A re-keys the bar (a second emission) and B
    refuses it as a conflict even when the bracket is identical."""
    activation = ms(T0 - timedelta(days=1))
    out1, ledger = f4_identity(comp, {}, cand(SV1), activation_ms=activation, boundary_rule=False)
    out2, ledger = f4_identity(comp, ledger, cand(bumped), activation_ms=activation,
                               boundary_rule=False)
    assert (out1, out2) == (EMIT, expected)
    assert (comp.key(cand(SV1)) == comp.key(cand(bumped))) is (comp is B)


@BOTH
def test_lineage_only_change_is_the_same_setup(comp):
    """WP-IR-09 / WP-IT-09: lineage is metadata, so re-parenting never re-keys or conflicts."""
    reparented = StrategyVersion(SV1.strategy_id, SV1.version, SV1.source_hash, SV1.config_hash,
                                 SV1.contract_hash, lineage=("another", "ancestry"))
    assert reparented.identity_hash == SV1.identity_hash
    assert comp.key(cand(reparented)) == comp.key(cand(SV1))
    _, ledger = f4_identity(comp, {}, cand(SV1), activation_ms=ms(T0))
    out, _ = f4_identity(comp, ledger, cand(reparented), activation_ms=ms(T0))
    assert out == v2.DUPLICATE_SETUP


@pytest.mark.parametrize("field", ["strategy_id", "version", "source_hash", "config_hash",
                                   "contract_hash"])
def test_each_identity_field_reaches_the_key_or_the_payload(field):
    changed = {"strategy_id": "range_reversion", "version": "1.1.0", "source_hash": "66" * 32,
               "config_hash": "77" * 32, "contract_hash": "88" * 32}[field]
    fields = {**SV1.identity(), field: changed}
    other = StrategyVersion(**fields)
    assert other.identity_hash != SV1.identity_hash
    assert key_a(cand(other)) != key_a(cand(SV1))                       # A: always in the key
    assert (key_b(cand(other)) != key_b(cand(SV1))) is (field == "strategy_id")
    assert payload_b(cand(other)) != payload_b(cand(SV1))               # B: always in the payload


# ── 4. timeframe and direction separation ───────────────────────────────────

@BOTH
def test_timeframes_sharing_a_close_are_separate_keys(comp):
    day_end = close_ms(T0, "1d")
    bars = {"15m": T0 + timedelta(hours=23, minutes=45), "1h": T0 + timedelta(hours=23),
            "4h": T0 + timedelta(hours=20), "1d": T0}
    closes = {tf: close_ms(open_dt, tf) for tf, open_dt in bars.items()}
    assert set(closes.values()) == {day_end}                # one millisecond, four bars
    keys = {comp.key(cand(timeframe=tf, bar_close_ms=day_end)) for tf in closes}
    assert len(keys) == 4
    opens = [(tf, T0 + timedelta(milliseconds=TF[tf] * i)) for tf in TF for i in range(96)]
    grid = {comp.key(cand(timeframe=tf, bar_close_ms=close_ms(o, tf))) for tf, o in opens}
    assert len(grid) == 96 * len(TF)


@BOTH
@pytest.mark.parametrize("tf", ["1w", "4H", "5m", ""])
def test_unsupported_timeframe_fails_closed(comp, tf):
    with pytest.raises(v2.IntegrityInputError, match="timeframe_unknown"):
        comp.key(cand(timeframe=tf))


@BOTH
def test_direction_is_long_only_and_keyed(comp, monkeypatch):
    with pytest.raises(v2.IntegrityInputError, match="direction_unsupported"):
        comp.key(cand(direction="short"))
    monkeypatch.setattr(v2, "DIRECTIONS", ("long", "short"))     # a hypothetical two-sided venue
    assert comp.key(cand(direction="short")) != comp.key(cand(direction="long"))


# ── 5. symbol case and venue normalisation ──────────────────────────────────

@BOTH
@pytest.mark.parametrize("symbol", ["btcusdt", "BtcUsdt", " BTCUSDT", "BTCUSDT ", "BTC-USDT",
                                    "BTC/USDT", ""])
def test_non_canonical_symbol_is_refused_not_normalised(comp, symbol):
    with pytest.raises(v2.IntegrityInputError, match="symbol"):
        comp.key(cand(symbol=symbol))


@BOTH
@pytest.mark.parametrize("venue", ["Binance", "BINANCE", " binance", "binance-spot", ""])
def test_non_canonical_venue_is_refused_not_normalised(comp, venue):
    with pytest.raises(v2.IntegrityInputError, match="venue"):
        comp.key(cand(venue=venue))


@BOTH
def test_explicit_upstream_normalisation_gives_one_key(comp):
    variants = ["BTCUSDT", "btcusdt", " BtcUsdt ", "btcUSDT"]
    keys = {comp.key(cand(symbol=canonical_symbol(s), venue=canonical_venue(" Binance ")))
            for s in variants}
    assert keys == {comp.key(cand())}
    for still_bad in ("BTC-USDT", "BTC/USDT"):
        with pytest.raises(v2.IntegrityInputError):
            comp.key(cand(symbol=canonical_symbol(still_bad)))


@BOTH
def test_distinct_venues_are_never_merged(comp):
    assert comp.key(cand(venue="binance")) != comp.key(cand(venue="binance_us"))


def test_a44_key_is_case_sensitive_today():
    """Legacy behaviour pinned: the A44 key neither refuses nor normalises symbol case."""
    def ident(symbol):
        return a44.SetupIdentity(symbol, "4h", ms(T0), close_ms(T0, "4h"), "momentum", "long",
                                 "sb-2026.08", "fixed_execution_quality_v1")
    assert ident("btcusdt").key != ident("BTCUSDT").key


# ── 6. missing or invalid rule_hash fails closed ────────────────────────────

BAD_RULE_HASHES = [None, "", "AB" * 32, ("ab" * 32)[:-1], "ab" * 32 + "0", "g" * 64,
                   "sb-2026.08", 7]


@BOTH
@pytest.mark.parametrize("bad", BAD_RULE_HASHES, ids=repr)
def test_missing_or_invalid_rule_hash_fails_closed(comp, bad):
    c = cand(rule_hash=bad)
    with pytest.raises(v2.IntegrityInputError, match="rule_hash"):
        comp.key(c)
    with pytest.raises(v2.IntegrityInputError, match="rule_hash") if comp is B else nullcontext():
        comp.payload(c)
    ledger = {"sk_existing": "p"}
    with pytest.raises(v2.IntegrityInputError):
        f4_identity(comp, ledger, c, activation_ms=ms(T0))
    assert ledger == {"sk_existing": "p"}                  # nothing was claimed


@BOTH
@pytest.mark.parametrize("bad", [None, "sb-2026.08", "1.0", "v1.0.0", "01.0.0"])
def test_missing_or_invalid_strategy_version_fails_closed(comp, bad):
    with pytest.raises(v2.IntegrityInputError, match="strategy_version"):
        comp.key(cand(strategy_version=bad))


# ── 7. boundary-crossing re-fire (SE-36; WP-C05; F4.bar_before_version_activation) ──

BAR0 = close_ms(T0, "4h")                                    # closes 1 ms before T0 + 4 h
BAR1 = close_ms(T0 + timedelta(hours=4), "4h")
ACT2 = ms(T0 + timedelta(hours=4, minutes=30))               # SV2 activation minute


@pytest.mark.parametrize("comp,without_rule", [(A, EMIT), (B, v2.SETUP_CONFLICT)],
                         ids=["A_version_in_key", "B_version_excluded"])
def test_boundary_crossing_refire_of_an_emitted_bar(comp, without_rule):
    _, ledger = f4_identity(comp, {}, cand(SV1, bar_close_ms=BAR0), activation_ms=ms(T0))
    refire = cand(SV2, bar_close_ms=BAR0)
    with_rule, _ = f4_identity(comp, ledger, refire, activation_ms=ACT2)
    assert with_rule == v2.BAR_BEFORE_VERSION_ACTIVATION
    no_rule, _ = f4_identity(comp, ledger, refire, activation_ms=ACT2, boundary_rule=False)
    assert no_rule == without_rule
    out, ledger = f4_identity(comp, ledger, cand(SV2, bar_close_ms=BAR1), activation_ms=ACT2)
    again, _ = f4_identity(comp, ledger, cand(SV2, bar_close_ms=BAR1), activation_ms=ACT2)
    assert (out, again) == (EMIT, v2.DUPLICATE_SETUP)


@BOTH
def test_boundary_rule_is_needed_even_when_the_version_is_not_keyed(comp):
    """SV1 evaluated BAR0 and found no setup, so no key exists. Without the rule, SV2 would act
    on a bar the old version already decided, under either composition."""
    refire = cand(SV2, bar_close_ms=BAR0)
    assert f4_identity(comp, {}, refire, activation_ms=ACT2, boundary_rule=False)[0] == EMIT
    assert f4_identity(comp, {}, refire, activation_ms=ACT2)[0] == v2.BAR_BEFORE_VERSION_ACTIVATION


@pytest.mark.parametrize("comp,early", [(A, EMIT), (B, v2.SETUP_CONFLICT)],
                         ids=["A_version_in_key", "B_version_excluded"])
def test_misrecorded_activation_minute(comp, early):
    _, ledger = f4_identity(comp, {}, cand(SV1, bar_close_ms=BAR0), activation_ms=ms(T0))
    recorded_early = ms(T0 + timedelta(hours=3))             # before BAR0 closed: unsafe side
    assert f4_identity(comp, ledger, cand(SV2, bar_close_ms=BAR0),
                       activation_ms=recorded_early)[0] == early
    recorded_late = ms(T0 + timedelta(hours=9))              # after BAR1 closed: safe side
    for bar in (BAR0, BAR1):
        assert f4_identity(comp, ledger, cand(SV2, bar_close_ms=bar),
                           activation_ms=recorded_late)[0] == v2.BAR_BEFORE_VERSION_ACTIVATION


@pytest.mark.parametrize("comp,without_rule", [(A, EMIT), (B, v2.SETUP_CONFLICT)],
                         ids=["A_version_in_key", "B_version_excluded"])
def test_rollback_is_a_new_activation(comp, without_rule):
    _, ledger = f4_identity(comp, {}, cand(SV2, bar_close_ms=BAR1), activation_ms=ACT2)
    act3 = ms(T0 + timedelta(hours=8, minutes=15))           # SV1 reinstated after BAR1 closed
    back = cand(SV1, bar_close_ms=BAR1)
    with_rule, _ = f4_identity(comp, ledger, back, activation_ms=act3)
    no_rule, _ = f4_identity(comp, ledger, back, activation_ms=act3, boundary_rule=False)
    assert (with_rule, no_rule) == (v2.BAR_BEFORE_VERSION_ACTIVATION, without_rule)


@BOTH
def test_boundary_dead_zone_lasts_at_most_one_bar(comp):
    """A 1d bar that closed before activation stays the latest bar for up to a day; no 1d setup
    of the new version is possible until the next daily close."""
    act = ms(T0 + timedelta(days=1, hours=1))
    day0, day1 = close_ms(T0, "1d"), close_ms(T0 + timedelta(days=1), "1d")
    assert f4_identity(comp, {}, cand(SV2, timeframe="1d", bar_close_ms=day0),
                       activation_ms=act)[0] == v2.BAR_BEFORE_VERSION_ACTIVATION
    assert f4_identity(comp, {}, cand(SV2, timeframe="1d", bar_close_ms=day1),
                       activation_ms=act)[0] == EMIT


# ── 8. compatibility with the A44 key and persisted signals ─────────────────

@BOTH
def test_identity_scheme_switch_is_a_rekey_boundary(comp):
    """A row keyed by A44 (or an unkeyed off-mode row, which migration 011 leaves NULL) never
    matches an A or B key, so switching the identity version is itself guarded only by the rule."""
    ident = a44.SetupIdentity("BTCUSDT", "4h", ms(T0), BAR0, "momentum", "long", "sb-2026.08",
                              "fixed_execution_quality_v1")
    persisted = {ident.key: a44.bracket_hash(BRACKET)}
    switch = ms(T0 + timedelta(hours=4, minutes=1))
    c = cand(SV1, bar_close_ms=BAR0)
    assert f4_identity(comp, persisted, c, activation_ms=switch, boundary_rule=False)[0] == EMIT
    assert f4_identity(comp, persisted, c, activation_ms=switch)[0] == (
        v2.BAR_BEFORE_VERSION_ACTIVATION)


def test_composition_a_statuses_equal_the_a44_ledger_within_one_version():
    ledger, seen = a44.EmissionLedger(), {}
    a44_status = {"claimed": EMIT, "duplicate": v2.DUPLICATE_SETUP, "conflict": v2.SETUP_CONFLICT}
    for i in range(24):
        open_dt = T0 + timedelta(hours=4 * (i % 3))
        bracket = {**BRACKET, "entry_price": 100.0 + (i % 5 == 4)}
        ident = a44.SetupIdentity("BTCUSDT", "4h", ms(open_dt), close_ms(open_dt, "4h"),
                                  "momentum", "long", "sb-2026.08", "fixed_execution_quality_v1")
        expected = a44_status[ledger.claim_sync(ident, a44.bracket_hash(bracket)).status]
        c = cand(bar_close_ms=close_ms(open_dt, "4h"), bracket=bracket)
        out, seen = f4_identity(A, seen, c, activation_ms=ms(T0))
        assert out == expected
