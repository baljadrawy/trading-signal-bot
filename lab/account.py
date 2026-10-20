"""Per-strategy virtual Paper accounts with the owner-approved safeguards (lab design §2.2, R0-R10).

Pure, in-memory and deterministic: no DB, network, clock or file access. This is the accounting core a later
LAB_MODE engine would persist; nothing imports it, no image copies it, and it activates nothing.

* Money is Decimal. Spot, long only: no leverage, borrowing, short sale, top-up or reset (R0).
* Fills are full fills (R6). The executed price is the observed price moved against the order by the half-spread
  plus slippage (``ExecutionCosts``, a48-cost-v1 shape); the 0.10 % fee per side is charged on executed notional (R5).
* Every operation is a transaction: on an exception nothing (state or ledger) is kept. Every accepted or rejected
  request and every fill, release, alert, status change, review and snapshot is a hash-chained ledger event (R8).
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Dict, List, Optional, Tuple

D = Decimal
ZERO = D(0)

ACTIVE = "ACTIVE"
SUSPENDED_REVIEW = "SUSPENDED_REVIEW"      # R9 risk trigger: no new entries; predeclared exits continue
BLOCKED_INTEGRITY = "BLOCKED_INTEGRITY"    # accounting invariant failed: no new orders; predeclared exits continue
CLOSED = "CLOSED"                          # owner closed the experiment: no new entries; exits continue


class AccountError(Exception):
    pass


def _d(x) -> D:
    return x if isinstance(x, D) else D(str(x))


MONEY, QTY = D("1e-8"), D("1e-12")


def _m(x: D) -> D:
    """Booked money amounts are rounded to 1e-8 USDT so that every ledger identity holds exactly."""
    return x.quantize(MONEY)


@dataclass(frozen=True)
class AccountRules:
    initial_cash: D = D("5000")
    target_order: D = D("500")
    max_positions: int = 5
    exposure_cap: D = D("2500")
    fee_rate: D = D("0.001")                 # per side, standard spot, no BNB/VIP discount
    min_order: D = D("50")
    min_slippage: D = D("0.0005")            # a48-cost-v1 slippage floor
    drawdown_suspend: D = D("0.30")          # from peak equity
    equity_suspend_below: D = D("2000")
    loss_alert_streak: int = 8               # alert and review only

    def as_dict(self) -> dict:
        return {k: str(v) for k, v in self.__dict__.items()}


@dataclass(frozen=True)
class ExecutionCosts:
    half_spread: D
    slippage: D

    def check(self, rules: AccountRules):
        if self.half_spread <= ZERO or self.slippage < rules.min_slippage:
            raise AccountError("execution costs below the model: half_spread > 0 and slippage >= min_slippage required")

    def executed(self, side: str, observed: D) -> D:
        adj = self.half_spread + self.slippage
        return observed * (1 + adj) if side == "BUY" else observed * (1 - adj)


@dataclass(frozen=True)
class ExitPlan:
    """Predeclared risk handling for one position (fixed at entry, never changed by the account)."""
    stop: Optional[D] = None
    targets: Tuple[Tuple[D, D], ...] = ()    # (price, fraction of the ORIGINAL quantity), ascending price
    expiry_ts: Optional[str] = None          # ISO-8601 UTC; compared lexically


@dataclass
class Position:
    symbol: str
    qty: D
    orig_qty: D
    cost_basis: D            # remaining entry cost incl. buy fee
    entry_price: D           # executed
    plan: ExitPlan
    targets_hit: int = 0
    realized: D = ZERO


@dataclass
class Reservation:
    order_id: str
    intent_id: str
    symbol: str
    notional: D
    est_fee: D
    plan: ExitPlan


@dataclass
class Decision:
    accepted: bool
    reason: str
    order_id: Optional[str] = None
    notional: D = ZERO


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


_STATE = ("cash", "positions", "reservations", "decisions", "fills", "exits", "marks", "realized_total",
          "fees_total", "implicit_cost_total", "status", "status_reason", "peak_equity", "loss_streak",
          "_below_floor", "_seq", "snapshots")


@dataclass
class Account:
    account_id: str
    rules: AccountRules = field(default_factory=AccountRules)
    created_ts: str = ""

    def __post_init__(self):
        self.cash: D = self.rules.initial_cash
        self.positions: Dict[str, Position] = {}
        self.reservations: Dict[str, Reservation] = {}
        self.decisions: Dict[str, Decision] = {}
        self.fills: Dict[str, dict] = {}
        self.exits: Dict[str, dict] = {}
        self.marks: Dict[str, D] = {}
        self.snapshots: Dict[str, dict] = {}
        self.realized_total = self.fees_total = self.implicit_cost_total = ZERO
        self.status, self.status_reason = ACTIVE, ""
        self.peak_equity: D = self.rules.initial_cash
        self.loss_streak = 0
        self._below_floor = False
        self._seq = 0
        self.ledger: List[dict] = []
        self._post("OPEN", self.created_ts, rules=self.rules.as_dict(), cash=self.cash)

    # ------------------------------------------------------------ transactions and ledger
    @contextlib.contextmanager
    def _txn(self):
        saved = copy.deepcopy({k: getattr(self, k) for k in _STATE})
        n = len(self.ledger)
        try:
            yield
        except BaseException:
            for k, v in saved.items():
                setattr(self, k, v)
            del self.ledger[n:]
            raise

    def _post(self, kind: str, ts: str, **payload) -> dict:
        prev = self.ledger[-1]["hash"] if self.ledger else "0" * 64
        ev = {"seq": self._seq, "ts": ts, "account_id": self.account_id, "type": kind,
              "payload": json.loads(_canon(payload)), "prev": prev}
        ev["hash"] = hashlib.sha256(_canon(ev).encode()).hexdigest()
        self.ledger.append(ev)
        self._seq += 1
        return ev

    def verify_ledger(self) -> bool:
        prev = "0" * 64
        for i, ev in enumerate(self.ledger):
            body = {k: v for k, v in ev.items() if k != "hash"}
            if ev["seq"] != i or ev["prev"] != prev or hashlib.sha256(_canon(body).encode()).hexdigest() != ev["hash"]:
                return False
            prev = ev["hash"]
        return True

    def ledger_cash(self) -> D:
        """Cash recomputed from ledger events only (evidence reconciliation)."""
        cash = ZERO
        for ev in self.ledger:
            p = ev["payload"]
            if ev["type"] == "OPEN":
                cash = D(p["cash"])
            elif ev["type"] == "FILL_BUY":
                cash -= D(p["notional"]) + D(p["fee"])
            elif ev["type"] == "FILL_SELL":
                cash += D(p["gross"]) - D(p["fee"])
        return cash

    def export_jsonl(self) -> str:
        return "".join(_canon(ev) + "\n" for ev in self.ledger)

    # ------------------------------------------------------------ derived quantities
    def reserved_total(self) -> D:
        return sum((r.notional + r.est_fee for r in self.reservations.values()), ZERO)

    def exposure(self) -> D:
        """R1: entry cost basis of open positions + reserved notional and fees of pending orders (never mark value)."""
        return sum((p.cost_basis for p in self.positions.values()), ZERO) + self.reserved_total()

    def equity(self) -> D:
        return self.cash + sum((p.qty * self.marks.get(s, p.entry_price) for s, p in self.positions.items()), ZERO)

    def open_slots(self) -> int:
        return len(self.positions) + len(self.reservations)

    # ------------------------------------------------------------ integrity
    def integrity_problems(self) -> List[str]:
        probs = []
        basis = sum((p.cost_basis for p in self.positions.values()), ZERO)
        if self.cash != self.rules.initial_cash + self.realized_total - basis:
            probs.append("cash_identity")
        if self.cash < ZERO:
            probs.append("negative_cash")
        if self.reserved_total() > self.cash:
            probs.append("reservations_exceed_cash")
        if self.exposure() > self.rules.exposure_cap:
            probs.append("exposure_above_cap")
        if self.open_slots() > self.rules.max_positions:
            probs.append("too_many_positions")
        syms = [r.symbol for r in self.reservations.values()]
        if len(set(syms)) != len(syms) or set(syms) & set(self.positions):
            probs.append("duplicate_symbol")
        if any(p.qty <= ZERO or p.cost_basis < ZERO for p in self.positions.values()):
            probs.append("bad_position")
        if not self.verify_ledger():
            probs.append("ledger_chain")
        elif self.ledger_cash() != self.cash:
            probs.append("ledger_cash_mismatch")
        return probs

    def _after(self, ts: str):
        probs = self.integrity_problems()
        if probs:
            if self.status != BLOCKED_INTEGRITY:
                self._enter(BLOCKED_INTEGRITY, "integrity:" + ",".join(probs), ts)
            return
        self._risk_triggers(ts)

    def _enter(self, status: str, reason: str, ts: str):
        """Leave ACTIVE: pending (unfilled) entry orders are released; open positions are untouched."""
        old, self.status, self.status_reason = self.status, status, reason
        self._post("STATUS", ts, old=old, new=status, reason=reason)
        for oid in list(self.reservations):
            r = self.reservations.pop(oid)
            self._post("RELEASE", ts, order_id=oid, symbol=r.symbol, notional=r.notional, reason="status_" + status)

    def _risk_triggers(self, ts: str):
        eq = self.equity()
        if eq > self.peak_equity:
            self.peak_equity = eq
        r = self.rules
        dd = (self.peak_equity - eq) / self.peak_equity
        below = eq < r.equity_suspend_below
        crossed, self._below_floor = below and not self._below_floor, below
        if self.status != ACTIVE:
            return
        if dd >= r.drawdown_suspend:
            self._enter(SUSPENDED_REVIEW, f"drawdown {dd:.4f} from peak {self.peak_equity}", ts)
        elif crossed:
            self._enter(SUSPENDED_REVIEW, f"equity {eq} below {r.equity_suspend_below}", ts)

    # ------------------------------------------------------------ entries
    def request_entry(self, intent_id: str, symbol: str, ref_price, ts: str, plan: ExitPlan = ExitPlan()) -> Decision:
        if intent_id in self.decisions:                                   # idempotent replay
            return self.decisions[intent_id]
        with self._txn():
            dec = self._decide(intent_id, symbol, _d(ref_price), plan)
            self.decisions[intent_id] = dec
            self._post("INTENT", ts, intent_id=intent_id, symbol=symbol, ref_price=_d(ref_price),
                       accepted=dec.accepted, reason=dec.reason, order_id=dec.order_id, notional=dec.notional)
            self._after(ts)
        return dec

    def _decide(self, intent_id: str, symbol: str, ref_price: D, plan: ExitPlan) -> Decision:
        r = self.rules
        if self.status != ACTIVE:
            return Decision(False, "status_" + self.status.lower())
        if ref_price <= ZERO:
            return Decision(False, "bad_price")
        if plan.stop is not None and plan.stop >= ref_price:
            return Decision(False, "bad_exit_plan")
        if symbol in self.positions or any(x.symbol == symbol for x in self.reservations.values()):
            return Decision(False, "symbol_already_open")
        if self.open_slots() >= r.max_positions:
            return Decision(False, "max_positions")
        room = min(r.exposure_cap - self.exposure(), self.cash - self.reserved_total())
        notional = min(r.target_order, room / (1 + r.fee_rate)).quantize(D("0.01"), rounding=ROUND_DOWN)
        if notional < r.min_order:
            return Decision(False, "below_min_order")
        oid = f"{self.account_id}:{intent_id}"
        self.reservations[oid] = Reservation(oid, intent_id, symbol, notional, _m(notional * r.fee_rate), plan)
        return Decision(True, "reserved", oid, notional)

    def cancel(self, order_id: str, reason: str, ts: str):
        with self._txn():
            res = self.reservations.pop(order_id, None)
            if res is None:
                raise AccountError(f"unknown or already settled order {order_id}")
            self._post("RELEASE", ts, order_id=order_id, symbol=res.symbol, notional=res.notional, reason=reason)
            self._after(ts)

    def fill_entry(self, order_id: str, observed_price, costs: ExecutionCosts, ts: str) -> dict:
        observed = _d(observed_price)
        if order_id in self.fills:                                        # idempotent execution
            if self.fills[order_id]["observed"] != observed:
                raise AccountError(f"conflicting replay of fill {order_id}")
            return self.fills[order_id]
        costs.check(self.rules)
        with self._txn():
            res = self.reservations.pop(order_id, None)
            if res is None:
                raise AccountError(f"unknown or released order {order_id}")
            if observed <= ZERO:
                raise AccountError("bad fill price")
            px = costs.executed("BUY", observed)
            qty = (res.notional / px).quantize(QTY, rounding=ROUND_DOWN)
            fee = _m(res.notional * self.rules.fee_rate)
            implicit = _m(qty * (px - observed))
            self.positions[res.symbol] = Position(res.symbol, qty, qty, res.notional + fee, px, res.plan)
            self.cash -= res.notional + fee
            self.fees_total += fee
            self.implicit_cost_total += implicit
            self.marks[res.symbol] = observed
            out = {"order_id": order_id, "symbol": res.symbol, "observed": observed, "price": px, "qty": qty,
                   "notional": res.notional, "fee": fee, "implicit_cost": implicit}
            self.fills[order_id] = out
            self._post("FILL_BUY", ts, **out, cash=self.cash)
            self._after(ts)
        return out

    # ------------------------------------------------------------ exits: processed in every status
    def fill_exit(self, exit_id: str, symbol: str, observed_price, costs: ExecutionCosts, ts: str,
                  fraction="1", reason: str = "exit") -> dict:
        observed, fraction = _d(observed_price), _d(fraction)
        if exit_id in self.exits:                                         # idempotent execution
            if self.exits[exit_id]["observed"] != observed or self.exits[exit_id]["symbol"] != symbol:
                raise AccountError(f"conflicting replay of exit {exit_id}")
            return self.exits[exit_id]
        costs.check(self.rules)
        with self._txn():
            pos = self.positions.get(symbol)
            if pos is None:
                raise AccountError(f"no open position {symbol}")
            if observed <= ZERO or not (ZERO < fraction <= 1):
                raise AccountError("bad exit price or fraction")
            closed = fraction == 1
            qty = pos.qty if closed else (pos.qty * fraction).quantize(QTY, rounding=ROUND_DOWN)
            basis = pos.cost_basis if closed else _m(pos.cost_basis * fraction)
            px = costs.executed("SELL", observed)
            gross = _m(qty * px)
            fee = _m(gross * self.rules.fee_rate)
            pnl = gross - fee - basis
            self.cash += gross - fee
            self.fees_total += fee
            self.implicit_cost_total += _m(qty * (observed - px))
            self.realized_total += pnl
            pos.qty -= qty
            pos.cost_basis -= basis
            pos.realized += pnl
            self.marks[symbol] = observed
            out = {"exit_id": exit_id, "symbol": symbol, "observed": observed, "price": px, "qty": qty,
                   "gross": gross, "fee": fee, "pnl": pnl, "reason": reason, "closed": closed}
            self.exits[exit_id] = out
            self._post("FILL_SELL", ts, **out, cash=self.cash)
            if closed:
                trade_pnl = self.positions.pop(symbol).realized
                self.loss_streak = self.loss_streak + 1 if trade_pnl < ZERO else 0
                if self.loss_streak and self.loss_streak % self.rules.loss_alert_streak == 0:
                    self._post("REVIEW_ALERT", ts, reason="consecutive_losses", streak=self.loss_streak)
            self._after(ts)
        return out

    def on_price(self, symbol: str, observed_price, costs: ExecutionCosts, ts: str) -> List[dict]:
        """Apply the position's predeclared plan (stop, targets, expiry). Runs in every status."""
        observed = _d(observed_price)
        pos = self.positions.get(symbol)
        if pos is None:
            return []
        done, plan = [], pos.plan
        if plan.stop is not None and observed <= plan.stop:
            return [self.fill_exit(f"{symbol}:{ts}:stop", symbol, observed, costs, ts, reason="stop")]
        if plan.expiry_ts is not None and ts >= plan.expiry_ts:
            return [self.fill_exit(f"{symbol}:{ts}:expiry", symbol, observed, costs, ts, reason="expiry")]
        while symbol in self.positions and pos.targets_hit < len(plan.targets) and observed >= plan.targets[pos.targets_hit][0]:
            k = pos.targets_hit
            last = k == len(plan.targets) - 1
            frac = D(1) if last else min(D(1), pos.orig_qty * plan.targets[k][1] / pos.qty)
            done.append(self.fill_exit(f"{symbol}:{ts}:t{k + 1}", symbol, observed, costs, ts, frac, f"target{k + 1}"))
            pos.targets_hit = k + 1
        if not done:
            with self._txn():
                self.marks[symbol] = observed
                self._after(ts)
        return done

    # ------------------------------------------------------------ marks and daily snapshots
    def mark(self, prices: Dict[str, object], ts: str) -> D:
        with self._txn():
            for s, p in prices.items():
                if s in self.positions and _d(p) > ZERO:
                    self.marks[s] = _d(p)
            self._after(ts)
        return self.equity()

    def daily_snapshot(self, date: str, prices: Dict[str, object], ts: str) -> dict:
        if date in self.snapshots:                                        # one snapshot per UTC day
            return self.snapshots[date]
        eq = self.mark(prices, ts)
        with self._txn():
            basis = sum((p.cost_basis for p in self.positions.values()), ZERO)
            snap = {"date": date, "equity": eq, "cash": self.cash, "exposure": self.exposure(),
                    "unrealized": eq - self.cash - basis, "realized_total": self.realized_total,
                    "fees_total": self.fees_total, "implicit_cost_total": self.implicit_cost_total,
                    "peak_equity": self.peak_equity, "open_positions": len(self.positions),
                    "loss_streak": self.loss_streak, "status": self.status}
            self.snapshots[date] = snap
            self._post("EQUITY_SNAPSHOT", ts, **snap)
        return snap

    # ------------------------------------------------------------ owner review: the only way out of a suspension
    def owner_review(self, decision: str, by: str, ref: str, ts: str):
        if not by or not ref:
            raise AccountError("owner review needs `by` and `ref`")
        with self._txn():
            if decision == "resume":
                if self.status not in (SUSPENDED_REVIEW, BLOCKED_INTEGRITY):
                    raise AccountError(f"nothing to resume from {self.status}")
                if self.status == BLOCKED_INTEGRITY and self.integrity_problems():
                    raise AccountError("integrity problems remain; resume refused")
                self.peak_equity = self.equity()          # PROP: drawdown re-measured from the review point
                self._post("OWNER_REVIEW", ts, decision=decision, by=by, ref=ref, review_equity=self.peak_equity)
                old, self.status, self.status_reason = self.status, ACTIVE, f"owner resume {ref}"
                self._post("STATUS", ts, old=old, new=ACTIVE, reason=self.status_reason)
            elif decision == "close_experiment":
                self._post("OWNER_REVIEW", ts, decision=decision, by=by, ref=ref)
                if self.status == ACTIVE:
                    self._enter(CLOSED, f"owner close {ref}", ts)
                else:
                    old, self.status, self.status_reason = self.status, CLOSED, f"owner close {ref}"
                    self._post("STATUS", ts, old=old, new=CLOSED, reason=self.status_reason)
            elif decision == "keep_suspended":
                self._post("OWNER_REVIEW", ts, decision=decision, by=by, ref=ref)
            else:
                raise AccountError(f"unknown decision {decision}")


class Lab:
    """Registry of independent strategy accounts. No shared cash, positions, risk state or netting.
    Accounts are never deleted, refilled or reset; an id can be opened once."""

    def __init__(self, rules: AccountRules = AccountRules()):
        self.rules = rules
        self.accounts: Dict[str, Account] = {}

    def open_account(self, strategy_id: str, ts: str) -> Account:
        if strategy_id in self.accounts:
            raise AccountError(f"account {strategy_id} exists; accounts are never reset or reopened")
        self.accounts[strategy_id] = Account(strategy_id, self.rules, ts)
        return self.accounts[strategy_id]
