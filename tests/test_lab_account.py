"""Lab virtual account safeguards (lab/account.py): owner-approved rules R0-R10 incl. the R9 risk policy."""
from decimal import Decimal as D

import pytest

from lab import account as A
from lab.account import (ACTIVE, BLOCKED_INTEGRITY, CLOSED, SUSPENDED_REVIEW, Account, AccountError,
                         AccountRules, ExecutionCosts, ExitPlan, Lab)

C = ExecutionCosts(D("0.0002"), D("0.0005"))       # tiered half-spread + a48-cost-v1 slippage
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"]


def ts(i):
    return f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00Z"


def buy(acct, sym, price="100", i=0, plan=ExitPlan()):
    d = acct.request_entry(f"i-{sym}-{i}", sym, price, ts(i), plan)
    assert d.accepted, d.reason
    return acct.fill_entry(d.order_id, price, C, ts(i))


# ---------------------------------------------------------------- R0-R4: balance, size, positions, cap, no floor
def test_initial_state_and_rules():
    a = Account("s1")
    assert a.cash == D(5000) and a.status == ACTIVE and a.exposure() == 0 and a.equity() == D(5000)
    assert a.ledger[0]["type"] == "OPEN" and a.verify_ledger()


def test_target_order_and_fee_booking():
    a = Account("s1")
    f = buy(a, "BTCUSDT")
    assert f["notional"] == D("500.00") and f["fee"] == D("0.50000000")
    assert a.cash == D("4499.50000000")
    assert a.positions["BTCUSDT"].cost_basis == D("500.50000000")          # buy fee in cost basis
    assert f["price"] == D(100) * (1 + D("0.0007"))                        # spread + slippage against the buyer
    assert f["implicit_cost"] > 0 and a.integrity_problems() == []


def test_one_position_per_symbol_including_pending():
    a = Account("s1")
    d = a.request_entry("i1", "BTCUSDT", "100", ts(0))
    assert d.accepted
    assert a.request_entry("i2", "BTCUSDT", "100", ts(1)).reason == "symbol_already_open"
    a.fill_entry(d.order_id, "100", C, ts(2))
    assert a.request_entry("i3", "BTCUSDT", "100", ts(3)).reason == "symbol_already_open"


def test_exposure_cap_clips_fifth_order_and_rejects_sixth():
    a = Account("s1")
    for k, s in enumerate(SYMS[:4]):
        buy(a, s, i=k)
    # 4 x 500.50 = 2002 used; headroom 498 -> clipped to 498/(1.001) rounded down
    d = a.request_entry("i5", SYMS[4], "100", ts(9))
    assert d.accepted and d.notional == D("497.50")
    a.fill_entry(d.order_id, "100", C, ts(9))
    assert a.exposure() <= D(2500)
    assert a.request_entry("i6", SYMS[5], "100", ts(10)).reason == "max_positions"


def test_cap_counts_pending_reservations_and_cost_basis_not_mark():
    a = Account("s1")
    for k, s in enumerate(SYMS[:4]):
        a.request_entry(f"p{k}", s, "100", ts(k))                          # reserved, not filled
    assert a.exposure() == 4 * D("500.50")
    b = Account("s2")
    for k, s in enumerate(SYMS[:4]):
        buy(b, s, i=k)
    b.mark({s: "200" for s in SYMS[:4]}, ts(20))                           # positions double in value
    assert b.exposure() == 4 * D("500.50")                                  # mark never frees or uses cap
    assert b.request_entry("x", SYMS[4], "100", ts(21)).notional == D("497.50")


def test_max_five_positions_by_count():
    r = AccountRules(exposure_cap=D("100000"), initial_cash=D("100000"))
    a = Account("s1", r)
    for k, s in enumerate(SYMS[:5]):
        buy(a, s, i=k)
    assert a.request_entry("i6", SYMS[5], "100", ts(9)).reason == "max_positions"


def test_no_permanent_cash_floor_after_losses():
    a = Account("s1")
    for k, s in enumerate(SYMS[:5]):
        buy(a, s, i=k)
    for k, s in enumerate(SYMS[:5]):
        a.fill_exit(f"x{k}", s, "90", C, ts(30 + k))                       # ~10 % loss each
    assert a.status == ACTIVE and a.cash < D(5000)
    d = a.request_entry("again", "BTCUSDT", "100", ts(40))
    assert d.accepted and d.notional == D("500.00")                         # the unused 2,500 is not a floor


def test_no_leverage_order_limited_by_cash():
    r = AccountRules(initial_cash=D("300"), equity_suspend_below=D("0"))
    a = Account("s1", r)
    d = a.request_entry("i1", "BTCUSDT", "100", ts(0))
    assert d.notional == (D(300) / D("1.001")).quantize(D("0.01"), rounding="ROUND_DOWN")
    a.fill_entry(d.order_id, "100", C, ts(0))
    assert a.cash >= 0
    assert a.request_entry("i2", "ETHUSDT", "100", ts(1)).reason == "below_min_order"


def test_no_topup_reset_or_reopen():
    lab = Lab()
    lab.open_account("s1", ts(0))
    with pytest.raises(AccountError):
        lab.open_account("s1", ts(1))
    assert not any(hasattr(Account, m) for m in ("deposit", "reset", "top_up", "replenish", "delete"))


def test_independent_accounts_same_symbol():
    lab = Lab()
    a, b = lab.open_account("s1", ts(0)), lab.open_account("s2", ts(0))
    buy(a, "BTCUSDT")
    buy(b, "BTCUSDT", price="200")
    a.fill_exit("x", "BTCUSDT", "50", C, ts(5))
    assert "BTCUSDT" in b.positions and b.cash == D("4499.50000000")
    assert a.ledger[-1]["account_id"] == "s1" and all(e["account_id"] == "s2" for e in b.ledger)


# ---------------------------------------------------------------- R5/R6: costs
def test_costs_below_model_refused():
    a = Account("s1")
    d = a.request_entry("i1", "BTCUSDT", "100", ts(0))
    with pytest.raises(AccountError):
        a.fill_entry(d.order_id, "100", ExecutionCosts(D(0), D(0)), ts(0))
    with pytest.raises(AccountError):
        a.fill_entry(d.order_id, "100", ExecutionCosts(D("0.0001"), D("0.0001")), ts(0))
    assert a.reservations and not a.positions                              # nothing booked


def test_round_trip_cost_accounting():
    a = Account("s1")
    buy(a, "BTCUSDT")
    x = a.fill_exit("x", "BTCUSDT", "100", C, ts(5))                       # flat price: pure cost drag
    total_cost = D(5000) - a.cash
    assert x["pnl"] < 0 and total_cost == -x["pnl"]
    assert total_cost == a.fees_total + a.implicit_cost_total or abs(total_cost - a.fees_total - a.implicit_cost_total) < D("1e-6")
    assert a.integrity_problems() == []


# ---------------------------------------------------------------- idempotency and transactions
def test_idempotent_intent_fill_and_exit():
    a = Account("s1")
    d1 = a.request_entry("i1", "BTCUSDT", "100", ts(0))
    assert a.request_entry("i1", "BTCUSDT", "100", ts(1)) is d1
    f1 = a.fill_entry(d1.order_id, "100", C, ts(2))
    assert a.fill_entry(d1.order_id, "100", C, ts(3)) is f1
    with pytest.raises(AccountError):
        a.fill_entry(d1.order_id, "101", C, ts(3))                         # conflicting replay
    x1 = a.fill_exit("x1", "BTCUSDT", "110", C, ts(4))
    assert a.fill_exit("x1", "BTCUSDT", "110", C, ts(5)) is x1
    assert sum(e["type"] == "FILL_BUY" for e in a.ledger) == 1 and sum(e["type"] == "FILL_SELL" for e in a.ledger) == 1


def test_failure_mid_transaction_leaves_nothing(monkeypatch):
    a = Account("s1")
    d = a.request_entry("i1", "BTCUSDT", "100", ts(0))
    before = (a.cash, dict(a.reservations), len(a.ledger), a.ledger[-1]["hash"])
    real = Account._post

    def boom(self, kind, t, **p):
        if kind == "FILL_BUY":
            raise RuntimeError("crash between fill and ledger")
        return real(self, kind, t, **p)
    monkeypatch.setattr(Account, "_post", boom)
    with pytest.raises(RuntimeError):
        a.fill_entry(d.order_id, "100", C, ts(1))
    monkeypatch.setattr(Account, "_post", real)
    assert (a.cash, dict(a.reservations), len(a.ledger), a.ledger[-1]["hash"]) == before
    assert not a.positions and a.integrity_problems() == []
    a.fill_entry(d.order_id, "100", C, ts(2))                               # retry works exactly once
    assert a.integrity_problems() == []


def test_cancel_releases_reservation():
    a = Account("s1")
    d = a.request_entry("i1", "BTCUSDT", "100", ts(0))
    a.cancel(d.order_id, "expired", ts(1))
    assert a.exposure() == 0 and a.ledger[-1]["type"] == "RELEASE"
    with pytest.raises(AccountError):
        a.fill_entry(d.order_id, "100", C, ts(2))


# ---------------------------------------------------------------- R8: ledger, snapshots, evidence
def test_ledger_chain_and_cash_reconciliation():
    a = Account("s1")
    buy(a, "BTCUSDT")
    a.fill_exit("x", "BTCUSDT", "105", C, ts(3), fraction="0.25", reason="target1")
    assert a.verify_ledger() and a.ledger_cash() == a.cash
    text = a.export_jsonl()
    assert text.count("\n") == len(a.ledger) and '"type":"FILL_SELL"' in text
    a.ledger[2]["payload"]["notional"] = "1"                                # tamper
    assert not a.verify_ledger() and "ledger_chain" in a.integrity_problems()


def test_daily_snapshot_once_per_day():
    a = Account("s1")
    buy(a, "BTCUSDT")
    s = a.daily_snapshot("2026-01-01", {"BTCUSDT": "110"}, ts(100))
    assert a.daily_snapshot("2026-01-01", {"BTCUSDT": "50"}, ts(101)) is s
    assert s["equity"] == a.cash + a.positions["BTCUSDT"].qty * D(110)
    assert s["unrealized"] > 0 and s["exposure"] == D("500.50000000")
    assert sum(e["type"] == "EQUITY_SNAPSHOT" for e in a.ledger) == 1


def test_rejections_are_evidence():
    a = Account("s1")
    buy(a, "BTCUSDT")
    a.request_entry("dup", "BTCUSDT", "100", ts(9))
    ev = [e for e in a.ledger if e["type"] == "INTENT"]
    assert [e["payload"]["accepted"] for e in ev] == [True, False] and ev[1]["payload"]["reason"] == "symbol_already_open"


# ---------------------------------------------------------------- R9 risk policy (owner, 2026-10-21)
def test_drawdown_30pct_from_peak_suspends_and_exits_continue():
    r = AccountRules(exposure_cap=D("5000"), target_order=D("4900"), equity_suspend_below=D("0"))
    a = Account("s1", r)
    buy(a, "BTCUSDT", plan=ExitPlan(stop=D("50")))
    a.mark({"BTCUSDT": "120"}, ts(5))                                       # new peak
    peak = a.peak_equity
    a.mark({"BTCUSDT": "85"}, ts(6))                                        # ~28.7 % below peak: no trigger
    assert a.status == ACTIVE
    a.mark({"BTCUSDT": "80"}, ts(6))                                        # ~32.8 % below peak
    assert a.status == SUSPENDED_REVIEW and "drawdown" in a.status_reason
    assert (peak - a.equity()) / peak >= D("0.30")
    assert a.request_entry("n", "ETHUSDT", "100", ts(7)).reason == "status_suspended_review"
    assert "BTCUSDT" in a.positions                                         # nothing force-closed
    out = a.on_price("BTCUSDT", "49", C, ts(8))                            # predeclared stop still runs
    assert out and out[0]["reason"] == "stop" and not a.positions
    assert a.status == SUSPENDED_REVIEW                                     # no automatic resumption


def test_equity_below_2000_suspends():
    r = AccountRules(exposure_cap=D("5000"), target_order=D("4000"), drawdown_suspend=D("0.99"))
    a = Account("s1", r)
    buy(a, "BTCUSDT")
    a.mark({"BTCUSDT": "50"}, ts(5))                                        # equity ~ 3000
    assert a.status == ACTIVE
    a.mark({"BTCUSDT": "20"}, ts(6))                                        # equity ~ 1800
    assert a.status == SUSPENDED_REVIEW and "below 2000" in a.status_reason


def test_eight_consecutive_losses_alert_only():
    a = Account("s1")
    for k in range(8):
        buy(a, "BTCUSDT", i=k)
        a.fill_exit(f"x{k}", "BTCUSDT", "99", C, ts(k))
    alerts = [e for e in a.ledger if e["type"] == "REVIEW_ALERT"]
    assert len(alerts) == 1 and alerts[0]["payload"]["streak"] == 8
    assert a.status == ACTIVE                                               # alert and review only
    assert a.request_entry("next", "ETHUSDT", "100", ts(99)).accepted


def test_win_resets_loss_streak():
    a = Account("s1")
    for k in range(7):
        buy(a, "BTCUSDT", i=k)
        a.fill_exit(f"x{k}", "BTCUSDT", "99", C, ts(k))
    buy(a, "BTCUSDT", i=50)
    a.fill_exit("w", "BTCUSDT", "120", C, ts(50))
    assert a.loss_streak == 0 and not [e for e in a.ledger if e["type"] == "REVIEW_ALERT"]


def test_integrity_failure_blocks_new_orders_immediately_and_releases_pending():
    a = Account("s1")
    buy(a, "BTCUSDT", plan=ExitPlan(stop=D("90")))
    pend = a.request_entry("p", "ETHUSDT", "100", ts(3))
    a.cash -= D("1")                                                        # corruption outside the API
    a.mark({}, ts(4))
    assert a.status == BLOCKED_INTEGRITY and "cash_identity" in a.status_reason
    assert pend.order_id not in a.reservations                              # pending new order released
    assert a.request_entry("n", "SOLUSDT", "100", ts(5)).reason == "status_blocked_integrity"
    out = a.on_price("BTCUSDT", "89", C, ts(6))                            # open-position risk handling continues
    assert out[0]["reason"] == "stop"
    with pytest.raises(AccountError):                                       # no resume while invariants fail
        a.owner_review("resume", "owner", "REV-1", ts(7))


def test_no_automatic_resumption_owner_review_required():
    r = AccountRules(exposure_cap=D("5000"), target_order=D("4000"), drawdown_suspend=D("0.99"))
    a = Account("s1", r)
    buy(a, "BTCUSDT")
    a.mark({"BTCUSDT": "20"}, ts(5))
    assert a.status == SUSPENDED_REVIEW
    a.mark({"BTCUSDT": "200"}, ts(6))                                       # recovery does not resume
    assert a.status == SUSPENDED_REVIEW
    with pytest.raises(AccountError):
        a.owner_review("resume", "", "", ts(7))
    a.owner_review("keep_suspended", "owner", "REV-0", ts(7))
    assert a.status == SUSPENDED_REVIEW
    a.owner_review("resume", "owner", "REV-1", ts(8))
    assert a.status == ACTIVE and [e for e in a.ledger if e["type"] == "OWNER_REVIEW"][-1]["payload"]["ref"] == "REV-1"


def test_close_experiment_keeps_exits_and_evidence():
    a = Account("s1")
    buy(a, "BTCUSDT", plan=ExitPlan(expiry_ts=ts(50)))
    a.owner_review("close_experiment", "owner", "REV-9", ts(10))
    assert a.status == CLOSED and a.request_entry("n", "ETHUSDT", "100", ts(11)).reason == "status_closed"
    assert a.on_price("BTCUSDT", "101", C, ts(50))[0]["reason"] == "expiry"
    assert a.verify_ledger() and a.integrity_problems() == []


# ---------------------------------------------------------------- predeclared exit plan
def test_targets_25_50_25_and_stop_validation():
    a = Account("s1")
    plan = ExitPlan(stop=D("95"), targets=((D("103"), D("0.25")), (D("106"), D("0.50")), (D("110"), D("0.25"))))
    assert a.request_entry("bad", "ETHUSDT", "100", ts(0), ExitPlan(stop=D("101"))).reason == "bad_exit_plan"
    buy(a, "BTCUSDT", plan=plan)
    q0 = a.positions["BTCUSDT"].orig_qty
    r1 = a.on_price("BTCUSDT", "104", C, ts(1))
    assert [x["reason"] for x in r1] == ["target1"] and abs(r1[0]["qty"] - q0 * D("0.25")) < D("1e-9")
    r2 = a.on_price("BTCUSDT", "111", C, ts(2))                            # gap through T2 and T3
    assert [x["reason"] for x in r2] == ["target2", "target3"] and not a.positions
    assert a.integrity_problems() == [] and a.ledger_cash() == a.cash


def test_module_is_not_imported_by_production_code():
    import pathlib
    root = pathlib.Path(A.__file__).resolve().parents[1]
    for d in ("analyzer", "signal_engine", "scanner", "telegram", "trade_tracker", "shared", "p2_forward"):
        for f in (root / d).rglob("*.py"):
            t = f.read_text(errors="ignore")
            assert "from lab" not in t and "import lab" not in t, f


def test_rehashed_ledger_edit_detected_by_cash_reconciliation():
    import hashlib
    a = Account("s1")
    buy(a, "BTCUSDT")
    ev = next(e for e in a.ledger if e["type"] == "FILL_BUY")
    ev["payload"]["fee"] = "0.00000000"                                    # forged, then the chain is re-hashed
    prev = "0" * 64
    for e in a.ledger:
        e["prev"] = prev
        e["hash"] = hashlib.sha256(A._canon({k: v for k, v in e.items() if k != "hash"}).encode()).hexdigest()
        prev = e["hash"]
    assert a.verify_ledger()
    assert "ledger_cash_mismatch" in a.integrity_problems()
    a.mark({}, ts(9))
    assert a.status == BLOCKED_INTEGRITY
