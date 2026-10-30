"""Design A v1.0 timing and data contract (brief items 4-6, 23, 24): the decision instant, the
Sunday-ending 200-day window, the closed-candle rule, and refusal of invalid input. Synthetic only."""
import sys
from datetime import timedelta, timezone
from decimal import Decimal as D

import pytest

sys.path.insert(0, ".")
import design_a_synthetic as syn  # noqa: E402
from research.design_a import state as S  # noqa: E402
from research.design_a import timing as T  # noqa: E402
from research.mechanisms.simulate import SYNTHETIC, DatasetPermission  # noqa: E402

MONDAY = syn.day(203)
SUNDAY = MONDAY - S.DAY
DECISION = syn.at_decision(MONDAY)
SECOND = timedelta(seconds=1)


def window_of(candles, as_of=DECISION):
    return T.signal_window(syn.snapshot(as_of, candles), 200)


# --- item 5: the Monday decision instant ------------------------------------------------------

def test_only_monday_plus_thirty_seconds_is_a_decision_instant():
    assert T.is_decision_instant(DECISION)
    for wrong in (MONDAY, DECISION - SECOND, DECISION + SECOND, DECISION + timedelta(microseconds=1),
                  DECISION + timedelta(minutes=1), DECISION + timedelta(hours=1),
                  DECISION + S.DAY, DECISION - S.DAY, DECISION + S.WEEK + SECOND):
        assert not T.is_decision_instant(wrong), wrong
    assert T.is_decision_instant(DECISION + S.WEEK)


def test_the_next_decision_instant_is_strictly_later():
    assert T.next_decision_instant(DECISION - SECOND) == DECISION
    assert T.next_decision_instant(DECISION) == DECISION + S.WEEK
    assert T.next_decision_instant(MONDAY + S.DAY * 6) == DECISION + S.WEEK      # from Sunday
    assert T.next_decision_instant(MONDAY) == DECISION


def test_instants_must_be_utc():
    for bad in (DECISION.replace(tzinfo=None), DECISION.astimezone(timezone(timedelta(hours=1)))):
        with pytest.raises(S.DesignAError):
            T.is_decision_instant(bad)


# --- item 4: the latest completed Sunday ends the window ---------------------------------------

def test_sunday_and_tuesday_are_derived_from_the_decision_instant():
    assert T.latest_sunday_open(DECISION) == SUNDAY and SUNDAY.weekday() == 6
    tuesday = T.scheduled_reference_open(DECISION)
    assert tuesday == MONDAY + S.DAY and tuesday.weekday() == 1 and S.is_midnight(tuesday)


def test_the_window_is_the_200_days_ending_with_the_sunday():
    candles = syn.ending(SUNDAY, [str(100 + i) for i in range(250)])
    window, refusal = window_of(candles)
    assert refusal is None
    assert [c.open_time for c in window] == [SUNDAY - S.DAY * k for k in range(199, -1, -1)]
    assert window[-1].close == D("349")
    with pytest.raises(S.DesignAError):           # only meaningful at a decision instant
        T.signal_window(syn.snapshot(DECISION + S.DAY, candles), 200)


# --- item 6: closed candles only, no future observations ---------------------------------------

def test_a_candle_is_available_from_the_end_of_its_day():
    c = syn.candle(SUNDAY, "100")
    assert T.available_from(SUNDAY) == MONDAY
    assert not T.is_available(c, MONDAY - timedelta(microseconds=1))
    assert T.is_available(c, MONDAY) and T.is_available(c, DECISION)
    assert not T.is_available(syn.candle(MONDAY, "100"), DECISION)     # still open at the decision


def test_incomplete_and_future_candles_are_refused():
    history = tuple(syn.ending(SUNDAY, ["100"] * 200))
    assert S.Snapshot(DECISION, history, SYNTHETIC).candles == history
    with pytest.raises(S.DesignAError, match="incomplete"):            # the open Monday candle
        S.Snapshot(DECISION, history + (syn.candle(MONDAY, "100000"),), SYNTHETIC)
    with pytest.raises(S.DesignAError, match="future"):
        S.Snapshot(DECISION, (syn.candle(MONDAY + S.DAY, "100"),), SYNTHETIC)
    with pytest.raises(S.DesignAError, match="future"):                # opening exactly at as_of
        S.Snapshot(MONDAY, (syn.candle(MONDAY, "100"),), SYNTHETIC)


# --- item 23: invalid or duplicate timestamps --------------------------------------------------

def test_invalid_candle_timestamps_are_refused():
    for open_time in (SUNDAY.replace(tzinfo=None), SUNDAY.astimezone(timezone(timedelta(hours=2))),
                      SUNDAY + timedelta(hours=1), SUNDAY + timedelta(milliseconds=1)):
        with pytest.raises(S.DesignAError):
            S.Candle(open_time, D("1"), D("1"), D("1"), D("1"))


def test_duplicate_or_unordered_candles_are_refused():
    saturday, sunday = syn.candle(SUNDAY - S.DAY, "100"), syn.candle(SUNDAY, "101")
    with pytest.raises(S.DesignAError, match="duplicate"):
        S.Snapshot(DECISION, (saturday, sunday, syn.candle(SUNDAY, "102")), SYNTHETIC)
    with pytest.raises(S.DesignAError, match="ascending"):
        S.Snapshot(DECISION, (sunday, saturday), SYNTHETIC)
    with pytest.raises(TypeError):
        S.Snapshot(DECISION, [saturday, sunday], SYNTHETIC)


def test_inconsistent_or_non_decimal_prices_are_refused():
    with pytest.raises(TypeError):
        S.Candle(SUNDAY, 100.0, D("1"), D("1"), D("1"))
    for o, h, lo, c in (("NaN", "1", "1", "1"), ("Infinity", "1", "1", "1"), ("0", "1", "0", "1"),
                        ("-1", "1", "-1", "1"), ("1", "2", "1", "3"), ("1", "2", "1.5", "2")):
        with pytest.raises(S.DesignAError):
            S.Candle(SUNDAY, D(o), D(h), D(lo), D(c))


def test_only_the_synthetic_permission_is_accepted():
    real = DatasetPermission("binance_spot_daily", True, True, "hypothetical owner record")
    assert real.allows()    # would pass the S4 gate; Design A v1.0 still refuses every real dataset
    fake = DatasetPermission("not_synthetic", True, True, "x", synthetic=True)

    class Lenient(DatasetPermission):
        def allows(self):
            return True

    lenient = Lenient("binance_spot_daily", False, False, "", synthetic=True)
    for permission in (real, fake, lenient, "SYNTHETIC", None):
        with pytest.raises(S.DesignAError):
            S.Snapshot(DECISION, (), permission)


def test_synthetic_snapshots_predate_bitcoin():
    S.Snapshot(S.SYNTHETIC_BEFORE - SECOND, (), SYNTHETIC)
    with pytest.raises(S.DesignAError, match="before 2009-01-03"):
        S.Snapshot(S.SYNTHETIC_BEFORE, (), SYNTHETIC)


# --- item 24: interrupted or incomplete input is reported, never repaired ----------------------

def test_interrupted_input_is_never_repaired():
    full = syn.ending(SUNDAY, [str(100 + i % 7) for i in range(260)])
    assert window_of(full)[1] is None
    cut = [c for c in full if c.open_time <= SUNDAY - 2 * S.DAY]             # the feed stopped Friday
    assert window_of(cut)[1] == (S.Event.SKIP_MISSING_SUNDAY, "SUNDAY_CANDLE_UNAVAILABLE")
    holed = [c for c in full if c.open_time != SUNDAY - 50 * S.DAY]           # a day lost inside
    assert window_of(holed)[1] == (S.Event.SKIP_INVALID_DATA, "GAP_IN_WINDOW")
    first = [c for c in full if c.open_time != SUNDAY - 199 * S.DAY]          # lost with older history
    assert window_of(first)[1] == (S.Event.SKIP_INVALID_DATA, "GAP_IN_WINDOW")
    older = [c for c in full if c.open_time != SUNDAY - 220 * S.DAY]          # lost before the window
    assert window_of(older)[1] is None and window_of(older)[0] == window_of(full)[0]
    late = full[-150:]                                                        # history starts late
    assert window_of(late)[1] == (S.Event.WARMUP, "INSUFFICIENT_HISTORY")
    late_and_holed = [c for c in late if c.open_time != SUNDAY - 10 * S.DAY]
    assert window_of(late_and_holed)[1] == (S.Event.SKIP_INVALID_DATA, "GAP_IN_WINDOW")
    assert window_of([])[1] == (S.Event.WARMUP, "INSUFFICIENT_HISTORY")
