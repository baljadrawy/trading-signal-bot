"""WP2 lane C (R3): candle key, rule-aware setup key, duplicates, freshness, version boundary
and fail-closed settings of ``shared/signal_integrity_v2.py``.

Deterministic synthetic inputs only; every datetime is built with ``datetime(...)`` and
arithmetic. These tests show engineering properties (identity, idempotency, determinism, parity
with A44); they say nothing about market behaviour. No database, network or market data.
"""
import sys; sys.path.insert(0, '.')
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from shared import signal_identity as a44
from shared.signal_integrity_v2 import (
    A44_FRESHNESS_REASON, BAR_BEFORE_VERSION_ACTIVATION, BAR_NOT_CLOSED, BAR_STALE,
    CONFLICT, DATA_QUALITY, DUPLICATE, DUPLICATE_SETUP, IDENTITY_VERSIONS, MINUTE_MS, NEW,
    REASON_CODES, SETUP_CONFLICT, SETUP_KEY_VERSION, CandleRef, IntegrityInputError,
    IntegritySettingsError, RuleIdentity, SetupKeyV2, candle_key, classify_claim,
    closed_bar_freshness, detect_duplicates, duration_of, epoch_ms, parse_integrity_settings,
    payload_hash, register_claim, rejection_fields, setup_key_v2, version_boundary_reason)

UTC = timezone.utc
HOUR = 3_600_000
DAY = 86_400_000
TF = dict(a44.TIMEFRAME_MS)
Res = namedtuple("Res", "admissible reason_code age_ms")
T0 = datetime(2026, 10, 1, tzinfo=UTC)
RULE_A = "ab" * 32
RULE_B = "cd" * 32


def close_ms(open_dt, tf):
    """Venue close ms (last ms inside the bar) of the bar opening at ``open_dt``."""
    return epoch_ms(open_dt) + TF[tf] - 1


def skey(**over):
    args = dict(venue="binance", symbol="BTCUSDT", strategy_id="momentum_breakout",
                strategy_version="1.0.0", rule_hash=RULE_A, timeframe="4h",
                bar_close_ms=close_ms(T0, "4h"), direction="long")
    args.update(over)
    return setup_key_v2(**args)


def a44_identity(tf="4h", open_dt=T0, strategy_version="sb-2026.08", symbol="BTCUSDT"):
    open_ms = epoch_ms(open_dt)
    cand = {"symbol": symbol, "timeframe": tf, "trade_type": "momentum",
            "selection_policy": "fixed_execution_quality_v1",
            "candle_identity": {"version": 1, "candle_open_time_ms": open_ms,
                                "candle_close_time_ms": open_ms + TF[tf] - 1}}
    return a44.identity_from_candidate(cand, strategy_version=strategy_version,
                                       allow_pit_fallback=False)


# ── determinism ─────────────────────────────────────────────────────────────

def test_keys_are_pinned_and_repeatable():
    bar = close_ms(T0, "4h")
    assert bar == epoch_ms(T0 + timedelta(hours=4)) - 1
    assert candle_key("BTCUSDT", "4h", bar) == "ck_1f1d5cbc0cc861ec9f4959643302469a065d9c7a"
    assert skey() == "sk2_4ca8d606693ab978d0d16e3d17ed6472af4221e1"
    assert payload_hash({"stop_loss": 98.0, "entry_price": 100.0}) == (
        "5696bef211f4fffff8ee7bb021efbd57a539c9ff6ec23e0ad7d85c03f8c8de7b")
    assert len({skey() for _ in range(50)}) == 1
    assert len({candle_key("BTCUSDT", "4h", bar) for _ in range(50)}) == 1


def test_numpy_style_integers_are_normalised():
    class FakeInt(int):
        pass
    ref = CandleRef("BTCUSDT", "4h", FakeInt(close_ms(T0, "4h")))
    assert type(ref.bar_close_ms) is int
    assert ref.key == candle_key("BTCUSDT", "4h", close_ms(T0, "4h"))


# ── candle identity is version-free (R3.d) ──────────────────────────────────

def test_candle_key_ignores_release_label_while_a44_key_does_not():
    old, new = a44_identity(strategy_version="sb-2026.08"), a44_identity(strategy_version="sb-2026.09")
    assert old.key != new.key                         # today: the label re-keys the same candle
    assert CandleRef.from_setup_identity(old).key == CandleRef.from_setup_identity(new).key


@pytest.mark.parametrize("tf", sorted(TF))
def test_candle_bounds_match_a44(tf):
    ident = a44_identity(tf=tf)
    ref = CandleRef.from_setup_identity(ident)
    assert ref.bar_open_ms == ident.candle_open_ms
    assert ref.bar_close_ms == ident.candle_close_ms
    assert ref.bar_end_ms == ident.candle_end_ms
    assert CandleRef.from_open("BTCUSDT", tf, ident.candle_open_ms) == ref


@pytest.mark.parametrize("tf", sorted(TF))
@pytest.mark.parametrize("shift", [-1, 1, 1000, MINUTE_MS])
def test_misaligned_close_refused_exactly_where_a44_refuses(tf, shift):
    open_ms = epoch_ms(T0)
    close = open_ms + TF[tf] - 1 + shift
    cand = {"symbol": "BTCUSDT", "timeframe": tf, "trade_type": "momentum",
            "candle_identity": {"candle_open_time_ms": open_ms, "candle_close_time_ms": close}}
    with pytest.raises(a44.IdentityError):
        a44.identity_from_candidate(cand, strategy_version="x", allow_pit_fallback=False)
    with pytest.raises(IntegrityInputError, match="bar_close_not_aligned"):
        CandleRef("BTCUSDT", tf, close)


@pytest.mark.parametrize("bad", [None, True, 1.0, "1790827199999", -1, 0])
def test_candle_close_must_be_a_positive_integer(bad):
    with pytest.raises(IntegrityInputError):
        CandleRef("BTCUSDT", "4h", bad)


@pytest.mark.parametrize("symbol", ["", "btcusdt", " BTCUSDT", "BTC-USDT", None, 7])
def test_symbol_is_never_normalised(symbol):
    with pytest.raises(IntegrityInputError):
        CandleRef(symbol, "4h", close_ms(T0, "4h"))


@pytest.mark.parametrize("tf", ["1w", "5m", "4H", "", None])
def test_unsupported_timeframe_refused(tf):
    with pytest.raises(IntegrityInputError, match="timeframe_unknown"):
        duration_of(tf)


@pytest.mark.parametrize("tf", sorted(TF))
def test_new_bar_new_key(tf):
    opens = [T0 + timedelta(milliseconds=TF[tf] * i) for i in range(96)]
    ckeys = [candle_key("BTCUSDT", tf, close_ms(o, tf)) for o in opens]
    skeys = [skey(timeframe=tf, bar_close_ms=close_ms(o, tf)) for o in opens]
    assert len(set(ckeys)) == len(set(skeys)) == len(opens)


# ── rule-aware setup key (WP-C02; WP-IR-09; OF-T09 version test) ────────────

@pytest.mark.parametrize("field,value", [
    ("venue", "binance_alt"), ("symbol", "ETHUSDT"), ("strategy_id", "range_reversion"),
    ("strategy_version", "1.0.1"), ("rule_hash", RULE_B), ("timeframe", "1d"),
    ("bar_close_ms", close_ms(T0 + timedelta(hours=4), "4h")),
])
def test_every_identity_field_changes_the_key(field, value):
    over = {field: value}
    if field == "timeframe":
        over["bar_close_ms"] = close_ms(T0, "1d")
    assert skey(**over) != skey()


def test_key_is_not_derived_from_a_release_label():
    for bad in ("sb-2026.08", "v1.0.0", "1.0", "01.0.0", ""):
        with pytest.raises(IntegrityInputError, match="strategy_version"):
            skey(strategy_version=bad)
    for bad in ("sb-2026.08", RULE_A.upper(), RULE_A[:-1], RULE_A + "0", None):
        with pytest.raises(IntegrityInputError, match="rule_hash"):
            skey(rule_hash=bad)
    assert skey().startswith("sk2_") and not skey().startswith("sk_")
    assert SETUP_KEY_VERSION != a44.IDENTITY_VERSION


@pytest.mark.parametrize("over,match", [
    ({"direction": "short"}, "direction"), ({"venue": "Binance"}, "venue"),
    ({"strategy_id": "Momentum"}, "strategy_id"), ({"strategy_id": None}, "strategy_id_missing"),
])
def test_setup_key_inputs_fail_closed(over, match):
    with pytest.raises(IntegrityInputError, match=match):
        skey(**over)


def test_setup_key_object_requires_typed_parts():
    with pytest.raises(IntegrityInputError, match="candle"):
        SetupKeyV2("binance", ("BTCUSDT", "4h", 1), RuleIdentity("m", "1.0.0", RULE_A), "long")
    with pytest.raises(IntegrityInputError, match="rule_identity"):
        SetupKeyV2("binance", CandleRef("BTCUSDT", "4h", close_ms(T0, "4h")), None, "long")


# ── duplicates and conflicts ────────────────────────────────────────────────

def test_classify_and_register_are_insert_once_and_pure():
    seen = {}
    claim, after = register_claim(seen, "k1", "p1")
    assert claim.status == NEW and claim.reason_code is None and seen == {}
    dup, after2 = register_claim(after, "k1", "p1")
    assert (dup.status, dup.reason_code) == (DUPLICATE, DUPLICATE_SETUP)
    con, after3 = register_claim(after2, "k1", "p2")
    assert (con.status, con.reason_code, con.first_payload_hash) == (CONFLICT, SETUP_CONFLICT, "p1")
    assert after == after2 == after3 == {"k1": "p1"}       # the first payload is never replaced
    assert classify_claim(after3, "k2", "p1").status == NEW


@pytest.mark.parametrize("key,payload", [("", "p"), ("k", ""), (None, "p"), ("k", 3)])
def test_claim_inputs_fail_closed(key, payload):
    with pytest.raises(IntegrityInputError):
        classify_claim({}, key, payload)


def test_detect_duplicates_reports_in_input_order():
    entries = [("a", "x"), ("b", "y"), ("a", "x"), ("a", "z"), ("c", "w"), ("b", "y"), ("p", "q")]
    report = detect_duplicates(entries, seen={"p": "old"})
    assert [c.status for c in report.claims] == [NEW, NEW, DUPLICATE, CONFLICT, NEW, DUPLICATE,
                                                 CONFLICT]
    assert report.unique_keys == ("a", "b", "c")
    assert report.duplicate_indices == (2, 5)
    assert [(c.key, c.first_index, c.index, c.first_payload_hash, c.payload_hash)
            for c in report.conflicts] == [("a", 0, 3, "x", "z"), ("p", None, 6, "old", "q")]
    assert report.reason_counts == {DUPLICATE_SETUP: 2, SETUP_CONFLICT: 2}
    assert detect_duplicates(entries, seen={"p": "old"}) == report
    with pytest.raises(IntegrityInputError, match="entry_malformed"):
        detect_duplicates([("a", "x", "extra")])


def test_duplicate_statuses_equal_a44_emission_ledger():
    ledger, seen = a44.EmissionLedger(), {}
    a44_status = {"claimed": NEW, "duplicate": DUPLICATE, "conflict": CONFLICT}
    for i in range(40):
        ident = a44_identity(open_dt=T0 + timedelta(hours=4 * (i % 3)))
        bracket = {"entry_price": 100.0 + (i % 4 == 3), "stop_loss": 98.0, "stop_policy": "m"}
        bh = a44.bracket_hash(bracket)
        expected = ledger.claim_sync(ident, bh)
        claim, seen = register_claim(seen, ident.key, bh)
        assert claim.status == a44_status[expected.status]
        assert claim.first_payload_hash == expected.first_bracket


def test_payload_hash_is_canonical_and_refuses_nan():
    assert payload_hash({"a": 1, "b": [1.5, None]}) == payload_hash({"b": [1.5, None], "a": 1})
    assert payload_hash({"a": 1.0}) != payload_hash({"a": 1.0000001})
    for bad in (float("nan"), float("inf"), {1, 2}):
        with pytest.raises(IntegrityInputError, match="payload_not_canonical"):
            payload_hash({"a": bad})


@pytest.mark.parametrize("tf,repeats,gap", [("1d", 12, timedelta(hours=2)),
                                            ("4h", 2, timedelta(hours=2))])
def test_reanalysis_of_one_bar_emits_once_across_restart(tf, repeats, gap):
    """R3 test 1-2 model: the same closed bar re-analysed on every scan, with a restart halfway."""
    bar = close_ms(T0, tf)
    bracket = payload_hash({"entry_price": 100.0, "stop_loss": 98.0})
    seen, emitted = {}, 0
    for i in range(repeats):
        decided = T0 + timedelta(milliseconds=TF[tf]) + gap * i
        assert epoch_ms(decided) > bar                   # every re-analysis is after the close
        if i == repeats // 2:
            seen = dict(seen)                            # restart: the store keeps its keys
        claim, seen = register_claim(seen, skey(timeframe=tf, bar_close_ms=bar), bracket)
        emitted += claim.status == NEW
    assert emitted == 1


def test_admission_by_key_admits_at_most_once_whatever_happened_first():
    """R3.b model: the first emission of a bar is refused (capacity full); its re-emissions may
    then open at most one trade for that key, never a second one."""
    k, k_next = skey(), skey(bar_close_ms=close_ms(T0 + timedelta(hours=4), "4h"))
    events = [(k, False), (k, True), (k, True), (k_next, True), (k, True), (k_next, False)]
    admitted, trades = {}, []
    for key, capacity_free in events:
        if not capacity_free:
            continue
        claim, admitted = register_claim(admitted, key, "admitted")
        if claim.status == NEW:
            trades.append(key)
    assert trades == [k, k_next]
    assert all(trades.count(x) <= 1 for x in trades)


# ── closed-bar freshness (OF-T08; R3 test 6) ────────────────────────────────

@pytest.mark.parametrize("tf", sorted(TF))
def test_freshness_boundaries(tf):
    step = TF[tf]
    bar = close_ms(T0, tf)
    bound = step                                         # the A44 one-bar ceiling, as an input

    def at(now):
        f = closed_bar_freshness(bar_close_ms=bar, timeframe_ms=step, now_ms=now, max_age_ms=bound)
        return Res(f.admissible, f.reason_code, f.age_ms)
    assert at(bar - 1) == (False, BAR_NOT_CLOSED, -2)
    assert at(bar).reason_code == BAR_NOT_CLOSED          # exactly at the venue close ms
    assert at(bar + 1) == (True, None, 0)                 # first ms after the close
    assert at(epoch_ms(T0 + timedelta(milliseconds=step))).admissible
    assert at(bar + bound).admissible                     # one ms inside the bound
    assert at(bar + 1 + bound) == (False, BAR_STALE, bound)   # exactly at the bound
    assert at(bar + 1 + bound + DAY).reason_code == BAR_STALE


def test_freshness_with_a_tighter_bound():
    bar = close_ms(T0, "4h")
    bound = 5 * MINUTE_MS
    f = lambda now: closed_bar_freshness(bar_close_ms=bar, timeframe_ms=TF["4h"], now_ms=now,
                                         max_age_ms=bound)
    assert f(epoch_ms(T0 + timedelta(hours=4, minutes=4, seconds=59))).admissible
    assert f(epoch_ms(T0 + timedelta(hours=4, minutes=5))).reason_code == BAR_STALE


def test_freshness_bound_is_required_and_validated():
    base = dict(bar_close_ms=close_ms(T0, "4h"), timeframe_ms=TF["4h"], now_ms=epoch_ms(T0))
    with pytest.raises(TypeError):
        closed_bar_freshness(**base)                      # no default bound exists
    for bad in (0, -1, 1.5, True, None, "60000", TF["4h"] + 1):
        with pytest.raises(ValueError):
            closed_bar_freshness(**base, max_age_ms=bad)
    for name in ("timeframe_ms", "now_ms"):
        for bad in (0, -5, 2.0, None, False):
            with pytest.raises(ValueError):
                closed_bar_freshness(**{**base, name: bad}, max_age_ms=MINUTE_MS)


@pytest.mark.parametrize("bad", [None, "1", 1.0, True, 0, -1, close_ms(T0, "4h") + 1])
def test_malformed_bar_is_data_quality(bad):
    f = closed_bar_freshness(bar_close_ms=bad, timeframe_ms=TF["4h"], now_ms=epoch_ms(T0),
                             max_age_ms=TF["4h"])
    assert (f.admissible, f.reason_code, f.age_ms) == (False, DATA_QUALITY, None)


@pytest.mark.parametrize("tf", sorted(TF))
@pytest.mark.parametrize("bars", [1.0, 0.5, 0.25])
def test_freshness_equals_a44_reference(tf, bars):
    step = TF[tf]
    bar = close_ms(T0, tf)
    bound = int(step * bars)
    offsets = [-step, -2, -1, 0, 1, 2, bound - 1, bound, bound + 1, bound + 2, step, 3 * step]
    for off in offsets:
        now = bar + off
        ref = a44.freshness_at(tf, bar, now, max_age_bars=bars)
        mine = closed_bar_freshness(bar_close_ms=bar, timeframe_ms=step, now_ms=now,
                                    max_age_ms=bound)
        assert mine.admissible == ref.admissible
        assert mine.reason_code == (None if ref.reason is None else A44_FRESHNESS_REASON[ref.reason])
        assert mine.age_ms == ref.age_ms


def test_reason_codes_are_canonical_f4_names():
    for code in REASON_CODES:
        rec = rejection_fields(code)
        assert rec["stage"] == "F4" and rec["reason_code"].startswith(rec["stage"] + ".")
        assert rec["sub_stage"] in (None, "shared.identity")
    assert set(A44_FRESHNESS_REASON.values()) <= REASON_CODES
    with pytest.raises(ValueError):
        rejection_fields("F4.cooldown_active")


# ── UTC only, no DST (WP-IR-01 item 6) ──────────────────────────────────────

@pytest.mark.parametrize("day", [datetime(2026, 3, 8, tzinfo=UTC), datetime(2026, 3, 29, tzinfo=UTC),
                                 datetime(2026, 10, 25, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)])
def test_dst_switch_days_have_uniform_utc_bars(day):
    closes = [close_ms(day + timedelta(hours=h), "1h") for h in range(24)]
    assert all(b - a == HOUR for a, b in zip(closes, closes[1:]))
    assert len({candle_key("BTCUSDT", "1h", c) for c in closes}) == 24
    assert close_ms(day, "1d") == closes[-1]              # the daily bar ends with the 24th hour


def test_epoch_ms_is_offset_invariant_and_refuses_naive_or_sub_ms():
    moment = T0 + timedelta(hours=3, minutes=7)
    for hours in (-8, -5, 0, 1, 2, 3, 14):
        local = moment.astimezone(timezone(timedelta(hours=hours)))
        assert epoch_ms(local) == epoch_ms(moment)
    assert epoch_ms(datetime(1970, 1, 1, tzinfo=UTC)) == 0
    assert epoch_ms(T0) % DAY == 0
    with pytest.raises(IntegrityInputError, match="timezone_aware"):
        epoch_ms(datetime(2026, 10, 1))
    with pytest.raises(IntegrityInputError, match="sub_millisecond"):
        epoch_ms(T0 + timedelta(microseconds=1))
    with pytest.raises(IntegrityInputError):
        epoch_ms(epoch_ms(T0))


# ── no re-fire across a version boundary (SE-36; SE-84; WP-C05) ─────────────

def test_version_boundary_blocks_rekeyed_refire_of_an_old_bar():
    activation = epoch_ms(T0 + timedelta(hours=4))       # the new version's activation minute
    old_bar = close_ms(T0, "4h")                         # closed 1 ms before activation
    new_bar = close_ms(T0 + timedelta(hours=4), "4h")
    assert skey(strategy_version="1.0.0", rule_hash=RULE_A) != skey(strategy_version="1.1.0",
                                                                     rule_hash=RULE_B)
    assert version_boundary_reason(bar_close_ms=old_bar, activation_ms=activation) == (
        BAR_BEFORE_VERSION_ACTIVATION)
    assert version_boundary_reason(bar_close_ms=new_bar, activation_ms=activation) is None
    assert version_boundary_reason(bar_close_ms=activation, activation_ms=activation) is None
    assert version_boundary_reason(bar_close_ms=activation - 1, activation_ms=activation) == (
        BAR_BEFORE_VERSION_ACTIVATION)
    assert version_boundary_reason(bar_close_ms=None, activation_ms=activation) == DATA_QUALITY


@pytest.mark.parametrize("bad", [0, -MINUTE_MS, MINUTE_MS + 1, 1.0 * MINUTE_MS, None, True])
def test_activation_must_be_a_whole_minute(bad):
    with pytest.raises(ValueError):
        version_boundary_reason(bar_close_ms=close_ms(T0, "4h"), activation_ms=bad)


# ── fail-closed settings ────────────────────────────────────────────────────

def test_default_settings_equal_today():
    s = parse_integrity_settings({})
    assert (s.mode, s.identity_version, s.freshness_max_age_ms) == ("off", a44.IDENTITY_VERSION, ())
    assert s.mode == a44.integrity_mode(SimpleNamespace())
    with pytest.raises(IntegritySettingsError, match="no freshness bound"):
        s.max_age_ms("4h")


@pytest.mark.parametrize("raw", ["off", "enforce", " ENFORCE ", "Off", "", "validate", "on",
                                 "enforce,off", "0"])
def test_mode_parsing_equals_a44(raw):
    try:
        expected = a44.integrity_mode(SimpleNamespace(SIGNAL_INTEGRITY_MODE=raw))
    except RuntimeError as exc:
        with pytest.raises(RuntimeError) as got:
            parse_integrity_settings({"SIGNAL_INTEGRITY_MODE": raw})
        assert str(got.value) == str(exc)
    else:
        assert parse_integrity_settings({"SIGNAL_INTEGRITY_MODE": raw}).mode == expected


def test_identity_version_parsing():
    for raw, want in ((" WP2-SID-V2 ", SETUP_KEY_VERSION), ("a43-sid-v1", a44.IDENTITY_VERSION)):
        assert parse_integrity_settings({"SIGNAL_IDENTITY_VERSION": raw}).identity_version == want
    assert IDENTITY_VERSIONS[0] == a44.IDENTITY_VERSION
    for bad in ("", "v2", "wp2-sid-v3"):
        with pytest.raises(IntegritySettingsError):
            parse_integrity_settings({"SIGNAL_IDENTITY_VERSION": bad})


def test_freshness_bound_parsing():
    s = parse_integrity_settings({"SIGNAL_FRESHNESS_MAX_AGE_MS": " 4h=14400000 , 15m=300000"})
    assert s.freshness_max_age_ms == (("15m", 300_000), ("4h", 14_400_000))
    assert s.max_age_ms("15m") == 300_000
    with pytest.raises(IntegritySettingsError):
        s.max_age_ms("1d")


@pytest.mark.parametrize("raw", ["", " ", "4h", "4h=", "=900000", "4h=0", "4h=-1", "4h=1.5",
                                 "4h=14400001", "1w=1000", "4h=1000,4h=2000", "4h=1000,,1d=5",
                                 "4h=1e3", "4h=١٢"])
def test_freshness_bound_parsing_fails_closed(raw):
    with pytest.raises(IntegritySettingsError):
        parse_integrity_settings({"SIGNAL_FRESHNESS_MAX_AGE_MS": raw})


@pytest.mark.parametrize("source", [
    {"SIGNAL_INTEGRITY_MDOE": "enforce"}, {"SIGNAL_IDENTITY_VER": "wp2-sid-v2"},
    {"SIGNAL_FRESHNESS_MAX_AGE": "4h=1000"}, {"SIGNAL_INTEGRITY_MODE": None},
    {"SIGNAL_IDENTITY_VERSION": 2}, [("SIGNAL_INTEGRITY_MODE", "off")],
])
def test_unknown_or_non_string_settings_refuse(source):
    with pytest.raises(IntegritySettingsError):
        parse_integrity_settings(source)


def test_unrelated_settings_are_ignored():
    s = parse_integrity_settings({"SIGNAL_INTEGRITY_MODE": "enforce", "APP_VERSION": "sb-2026.08",
                                  "SIGNALS_PER_CYCLE": "x"})
    assert (s.mode, s.identity_version) == ("enforce", a44.IDENTITY_VERSION)
