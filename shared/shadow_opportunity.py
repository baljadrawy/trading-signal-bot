"""Shadow opportunity ledger -- pure, synthetic-tested, NOT wired into any runtime service.

Purpose: measure what Paper *portfolio capacity* blocks. A shadow opportunity is a candidate
that passed every strategy/technical check and was refused ONLY by a Paper portfolio
capacity / concentration / exposure limit. It is never a trade, never executed, and never
counted as Paper performance (see docs/ops/SHADOW_OPPORTUNITY_LEDGER.md).

Labelling invariants (enforced on construction, append, read and aggregation):
* opportunity rows: ``record_kind="shadow_opportunity"``, ``executed=False``,
  ``is_executed_trade=False``;
* outcome rows: ``record_kind="shadow_outcome"``, ``executed=False``,
  ``is_executed_trade=False``;
* economic (enforce-mode) halts, technical halts, administrative stops and observed-only
  reasons are real stops, not opportunities: ``build_opportunity`` refuses them.

Outcomes reuse the frozen A42 bar replay (``shared.counterfactual_barrier.replay_bracket``:
the same entry rules, triple barrier, partial exits and timeframe expiry as Paper trades);
trade types that replay does not support fall back to a documented conservative
approximation flagged ``outcome_model="approx"``. Costs come from
``shared.signal_quality.CostModel`` (0.10 %/side fee + declared slippage + optional spread).

Storage: append-only JSONL with a SHA-256 hash chain, under a file/stream name that can
never coincide with a Paper trade store. Nothing here touches a database or the network.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, Sequence

from shared.counterfactual_barrier import MODEL_VERSION as REPLAY_MODEL_VERSION
from shared.counterfactual_barrier import Bar, replay_bracket
from shared.economic_halt_policy import PORTFOLIO_LIMITS, SIZING_REASONS, classify_reason
from shared.evidence_v2 import canonical_json, sha256_hex
from shared.signal_quality import TIMEFRAME_MS, CostModel

SCHEMA_VERSION = "shadow-opp-v1"
RECORD_KIND = "shadow_opportunity"
OUTCOME_KIND = "shadow_outcome"
SHADOW_KINDS = frozenset({RECORD_KIND, OUTCOME_KIND})
STREAM_NAME = "paper.shadow_opportunity.v1"      # evidence stream name reserved for wiring
DEFAULT_FILENAME = "shadow_opportunity_ledger.jsonl"
APPROX_MODEL = "approx"
GENESIS_HASH = "0" * 64

LAYER_DELIVERY = "telegram_delivery"             # telegram.main.can_deliver_candidate
LAYER_ADMISSION = "tracker_admission"            # trade_tracker risk admission
LAYERS = (LAYER_DELIVERY, LAYER_ADMISSION)
_DELIVERY_CAPACITY_RE = re.compile(r"^portfolio_capacity_(\d+)/(\d+)$")


class ShadowError(ValueError):
    """Base class for every refusal raised by this module."""


class NotAnOpportunityError(ShadowError):
    """The refusal is a real stop (economic / technical / admin / observed), not capacity."""


class NotATradeError(ShadowError):
    """A shadow record was offered (or requested) as an executed trade."""


class MixedPopulationError(ShadowError):
    """Shadow and executed records were mixed in one population."""


class LedgerTamperError(ShadowError):
    """The hash chain or a row's content does not verify."""


# ---- refusal classification --------------------------------------------------------------
def classify_capacity_refusal(refusal_code: str, layer: str) -> str:
    """Return the capacity class of a refusal, or raise NotAnOpportunityError.

    * ``telegram_delivery``: only ``portfolio_capacity_<n>/<cap>`` qualifies; pause reasons
      (``trading_paused`` and free-text pauses) are administrative stops.
    * ``tracker_admission``: the PORTFOLIO_LIMITS set (gross/symbol/strategy/regime exposure,
      ``max_open_trades``) or a sizing label, which the tracker uses as the reason of the
      ``max_open_trades`` capacity block when the reduced position count is reached.
    """
    code = str(refusal_code or "")
    if layer not in LAYERS:
        raise ShadowError(f"unknown refusal layer {layer!r}")
    if layer == LAYER_DELIVERY:
        m = _DELIVERY_CAPACITY_RE.match(code)
        if m and int(m.group(2)) > 0 and int(m.group(1)) >= int(m.group(2)):
            return "delivery_portfolio_capacity"
        raise NotAnOpportunityError(f"delivery refusal {code!r} is not a portfolio-capacity block")
    kind = classify_reason(code)
    if kind == "portfolio" and code in PORTFOLIO_LIMITS:
        return "max_open_trades" if code == "max_open_trades" else code
    if kind == "sizing" and code in SIZING_REASONS:
        return "max_open_trades"                    # sizing-labelled capacity block
    raise NotAnOpportunityError(
        f"admission refusal {code!r} is class {kind!r}: a real stop, never an opportunity")


# ---- construction ------------------------------------------------------------------------
def _price(x, name: str, *, optional: bool = False) -> float | None:
    if x is None and optional:
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0:
        raise ShadowError(f"{name} must be a finite positive number")
    return float(x)


def _text(x, name: str) -> str:
    if not isinstance(x, str) or not x.strip():
        raise ShadowError(f"{name} is required")
    return x


def minute_iso(ms: int) -> str:
    """Minute-precision UTC label (docs/human use); the data keeps full ms."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def cost_model_version(cost: CostModel) -> str:
    return f"{cost.label}|rt={cost.roundtrip_pct(0.0 if cost.include_spread else None):.6f}" \
        f"|stop_slip={cost.stop_slippage_frac:.6f}|spread={'obs' if cost.include_spread else 'none'}"


def build_opportunity(*, signal_id: str, candidate_id: str, symbol: str, trade_type: str,
                      timeframe: str, strategy_version: str, risk_policy_version: str,
                      refusal_code: str, refusal_layer: str, decision_ms: int,
                      planned_entry: float, stop_loss: float, target_1: float,
                      target_2: float, target_3: float, invalidation_price: float | None = None,
                      cost: CostModel = CostModel()) -> dict:
    """Return one shadow-opportunity record, or raise (never silently records a real stop)."""
    refusal_class = classify_capacity_refusal(refusal_code, refusal_layer)
    if isinstance(decision_ms, bool) or not isinstance(decision_ms, int) or decision_ms <= 0:
        raise ShadowError("decision_ms must be a positive integer (epoch ms)")
    if cost.validate():
        raise ShadowError(f"invalid cost model: {cost.validate()}")
    body = {
        "record_kind": RECORD_KIND, "executed": False, "is_executed_trade": False,
        "schema_version": SCHEMA_VERSION, "stream": STREAM_NAME,
        "signal_id": _text(signal_id, "signal_id"),
        "candidate_id": _text(candidate_id, "candidate_id"),
        "symbol": _text(symbol, "symbol"), "trade_type": _text(trade_type, "trade_type"),
        "timeframe": _text(timeframe, "timeframe"),
        "strategy_version": _text(strategy_version, "strategy_version"),
        "risk_policy_version": _text(risk_policy_version, "risk_policy_version"),
        "refusal_code": str(refusal_code), "refusal_layer": refusal_layer,
        "refusal_class": refusal_class,
        "decision_ms": decision_ms, "decision_minute_utc": minute_iso(decision_ms),
        "planned_entry": _price(planned_entry, "planned_entry"),
        "stop_loss": _price(stop_loss, "stop_loss"),
        "target_1": _price(target_1, "target_1"), "target_2": _price(target_2, "target_2"),
        "target_3": _price(target_3, "target_3"),
        "invalidation_price": _price(invalidation_price, "invalidation_price", optional=True),
        "cost_model_version": cost_model_version(cost), "cost_model": asdict(cost),
    }
    body["opportunity_id"] = sha256_hex(canonical_json(
        [body["signal_id"], body["candidate_id"], refusal_layer, decision_ms]))
    return body


# ---- outcome resolution ------------------------------------------------------------------
def _bars(path: Sequence[Sequence[float]]) -> tuple[list[Bar], str]:
    """(t, high, low, close) or (t, open, high, low, close) -> Bars.

    A 4-tuple path has no open: bar i opens at bar i-1's close and bar 0 at its own close
    (``open_source="prev_close"``); a 5-tuple path keeps its opens (``"given"``).
    """
    if not path:
        return [], "none"
    width = {len(p) for p in path}
    if width not in ({4}, {5}):
        raise ShadowError("path rows must all be (t, high, low, close) or (t, open, high, low, close)")
    bars, prev_close = [], None
    for p in path:
        if len(p) == 5:
            t, o, h, lo, c = p
        else:
            t, h, lo, c = p
            o = c if prev_close is None else min(max(prev_close, lo), h)
        bars.append(Bar(int(t), float(o), float(h), float(lo), float(c)))
        prev_close = float(c)
    return bars, ("given" if width == {5} else "prev_close")


def _approx(rec: dict, bars: list[Bar], cost: CostModel, cost_pct: float) -> dict:
    """Conservative single-exit approximation for trade types the replay does not support.

    Fill at planned entry on the first bar whose range contains it (else no fill); then per
    bar the stop is checked BEFORE target_1 (a bar touching both is a loss); stop fills at
    min(stop, bar open) x (1 - stop_slippage); target_1 exits the full position; no partial
    exits, no break-even move, no trailing; a path that ends first is ``open_at_end``.
    """
    entry, stop, t1 = rec["planned_entry"], rec["stop_loss"], rec["target_1"]
    fill_i = next((i for i, b in enumerate(bars) if b.low <= entry <= b.high), None)
    if fill_i is None:
        return {"status": "not_filled", "reason": "entry_not_in_range"}
    for i in range(fill_i, len(bars)):
        b = bars[i]
        if b.low <= stop:
            px = min(stop, b.open if i > fill_i else stop) * (1 - cost.stop_slippage_frac)
            reason = "stop_loss"
        elif b.high >= t1:
            px, reason = t1, "target_1"
        else:
            continue
        gross = (px / entry - 1) * 100
        return {"status": "closed", "exit_reason": reason, "exit_price": px,
                "gross_pct": gross, "net_pct": gross - cost_pct, "bars_used": i + 1,
                "target_reached": 1 if reason == "target_1" else 0, "fill_price": entry}
    return {"status": "open_at_end", "reason": "insufficient_bars", "fill_price": entry,
            "bars_used": len(bars)}


def resolve_outcome(record: dict, path: Sequence[Sequence[float]], *, bar_timeframe: str,
                    cost: CostModel | None = None, spread_pct: float | None = None,
                    resolved_ms: int | None = None) -> dict:
    """Resolve the hypothetical outcome of one shadow opportunity on a later price path.

    The path must start at or after the decision (look-ahead guard inside the replay).
    Returns a ``shadow_outcome`` row; ``net_pct`` is net of the record's cost model.
    """
    require_shadow(record, RECORD_KIND)
    if bar_timeframe not in TIMEFRAME_MS:
        raise ShadowError(f"unknown bar_timeframe {bar_timeframe!r}")
    cost = cost or CostModel(**record["cost_model"])
    cost_pct = cost.roundtrip_pct(spread_pct)
    bars, open_source = _bars(path)
    base = {"record_kind": OUTCOME_KIND, "executed": False, "is_executed_trade": False,
            "schema_version": SCHEMA_VERSION, "opportunity_id": record["opportunity_id"],
            "symbol": record["symbol"], "trade_type": record["trade_type"],
            "strategy_version": record["strategy_version"],
            "cost_model_version": cost_model_version(cost), "cost_roundtrip_pct": cost_pct,
            "spread_pct": spread_pct, "bar_timeframe": bar_timeframe, "open_source": open_source,
            "path_first_ms": bars[0].open_ms if bars else None,
            "path_last_ms": bars[-1].open_ms if bars else None, "resolved_ms": resolved_ms}
    if bars and bars[0].open_ms < record["decision_ms"]:
        raise ShadowError("path starts before the decision (look-ahead)")
    o = replay_bracket(trade_type=record["trade_type"], planned_entry=record["planned_entry"],
                       stop_loss=record["stop_loss"], target_1=record["target_1"],
                       target_2=record["target_2"], target_3=record["target_3"],
                       signal_timeframe=record["timeframe"], bars=bars,
                       bar_timeframe=bar_timeframe, decision_ms=record["decision_ms"],
                       invalidation_price=record["invalidation_price"], cost=cost,
                       spread_pct=spread_pct)
    if o.status == "rejected" and o.reason == "unsupported_trade_type":
        res = _approx(record, bars, cost, cost_pct)
        return {**base, "outcome_model": APPROX_MODEL, "reason": None, "exit_reason": None,
                "exit_price": None, "gross_pct": None, "net_pct": None, "target_reached": 0,
                "fill_price": None, "bars_used": 0, **res}
    return {**base, "outcome_model": REPLAY_MODEL_VERSION, "status": o.status,
            "reason": o.reason, "fill_price": o.fill_price, "exit_reason": o.exit_reason,
            "exit_price": o.exit_price, "target_reached": o.target_reached,
            "gross_pct": o.gross_pct, "net_pct": o.net_pct, "bars_used": o.bars_used}


# ---- labelling guards --------------------------------------------------------------------
def require_shadow(row: Any, kind: str) -> None:
    if not isinstance(row, dict) or row.get("record_kind") != kind \
            or row.get("executed") is not False or row.get("is_executed_trade") is not False:
        raise ShadowError(f"not a correctly labelled {kind} row")


def assert_not_shadow(row: Any) -> None:
    """Guard for any code path that consumes *executed* trades."""
    if isinstance(row, dict) and (row.get("record_kind") in SHADOW_KINDS
                                  or row.get("executed") is False
                                  or row.get("is_executed_trade") is False):
        raise NotATradeError("a shadow record can never be treated as an executed trade")


def _finite_json(obj: Any, where: str = "row") -> None:
    if isinstance(obj, float) and not math.isfinite(obj):
        raise ShadowError(f"non-finite number in {where}")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _finite_json(v, f"{where}.{k}")
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _finite_json(v, where)


# ---- append-only hash-chained ledger -----------------------------------------------------
def _entry_hash(seq: int, prev_hash: str, body: dict) -> str:
    return sha256_hex(canonical_json({"seq": seq, "prev_hash": prev_hash, "body": body}))


class ShadowOpportunityLedger:
    """Append-only JSONL; one line = {seq, prev_hash, body, entry_hash}.

    The file name must start with ``shadow_opportunity`` and end with ``.jsonl`` and may not
    contain ``trade``, so it cannot be confused with (or pointed at) a Paper trade store.
    There is deliberately no method that returns trades.
    """

    def __init__(self, path: str):
        base = os.path.basename(path)
        if not (base.startswith("shadow_opportunity") and base.endswith(".jsonl")) \
                or "trade" in base.lower():
            raise ShadowError(f"ledger file name {base!r} is not a shadow-opportunity stream")
        self.path = path

    def _rows(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        import json
        rows = []
        with open(self.path, encoding="utf-8") as fh:
            for n, line in enumerate(fh):
                if not line.strip():
                    raise LedgerTamperError(f"blank line at {n}")
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    raise LedgerTamperError(f"unparseable line {n}: {exc}") from None
        return rows

    def verify(self) -> list[dict]:
        """Verify the whole chain and every row's labels; return the rows."""
        rows, prev = self._rows(), GENESIS_HASH
        for i, r in enumerate(rows):
            if set(r) != {"seq", "prev_hash", "body", "entry_hash"} or r["seq"] != i \
                    or r["prev_hash"] != prev \
                    or r["entry_hash"] != _entry_hash(i, prev, r["body"]):
                raise LedgerTamperError(f"hash chain broken at seq {i}")
            body = r["body"]
            try:
                require_shadow(body, body.get("record_kind") if isinstance(body, dict) else None)
            except ShadowError:
                raise LedgerTamperError(f"row {i} is not a labelled shadow row") from None
            if body["record_kind"] not in SHADOW_KINDS:
                raise LedgerTamperError(f"row {i} has kind {body['record_kind']!r}")
            prev = r["entry_hash"]
        return rows

    def _append(self, body: dict) -> str:
        _finite_json(body)
        rows = self.verify()
        ids = {(r["body"]["record_kind"], r["body"]["opportunity_id"]) for r in rows}
        if (body["record_kind"], body["opportunity_id"]) in ids:
            raise ShadowError(f"duplicate {body['record_kind']} {body['opportunity_id']}")
        if body["record_kind"] == OUTCOME_KIND and \
                (RECORD_KIND, body["opportunity_id"]) not in ids:
            raise ShadowError("outcome for an unknown opportunity")
        seq = len(rows)
        prev = rows[-1]["entry_hash"] if rows else GENESIS_HASH
        h = _entry_hash(seq, prev, body)
        line = canonical_json({"seq": seq, "prev_hash": prev, "body": body, "entry_hash": h})
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return h

    def append_opportunity(self, record: dict) -> str:
        require_shadow(record, RECORD_KIND)
        return self._append(record)

    def append_outcome(self, outcome: dict) -> str:
        require_shadow(outcome, OUTCOME_KIND)
        return self._append(outcome)

    def opportunities(self) -> Iterator[dict]:
        for r in self.verify():
            if r["body"]["record_kind"] == RECORD_KIND:
                yield dict(r["body"])

    def outcomes(self) -> Iterator[dict]:
        for r in self.verify():
            if r["body"]["record_kind"] == OUTCOME_KIND:
                yield dict(r["body"])

    def trades(self):
        raise NotATradeError("the shadow ledger holds no trades; read the Paper trade store")


# ---- aggregation (always two separate populations) ---------------------------------------
def _stats(nets: list[float], grosses: list[float]) -> dict:
    gp = sum(g for g in grosses if g > 0)
    gl = -sum(g for g in grosses if g < 0)
    n = len(nets)
    return {"n_closed": n, "wins_net": sum(1 for x in nets if x > 0),
            "mean_net_pct": (sum(nets) / n) if n else None, "sum_net_pct": sum(nets),
            "gross_profit_factor": (gp / gl) if gl > 0 else None}


def aggregate(shadow_outcomes: Iterable[dict], executed_trades: Iterable[dict]) -> dict:
    """Report shadow and executed statistics side by side; never pooled.

    ``executed_trades`` rows need ``net_pct`` and ``gross_pct``; a shadow row in that list (or
    an executed row among the shadow outcomes) raises MixedPopulationError.
    """
    shadow, by_model, status = [], {}, {}
    for o in shadow_outcomes:
        try:
            require_shadow(o, OUTCOME_KIND)
        except ShadowError:
            raise MixedPopulationError("non-shadow row in the shadow population") from None
        status[o["status"]] = status.get(o["status"], 0) + 1
        if o["status"] == "closed":
            shadow.append(o)
            by_model[o["outcome_model"]] = by_model.get(o["outcome_model"], 0) + 1
    executed = []
    for t in executed_trades:
        try:
            assert_not_shadow(t)
        except NotATradeError:
            raise MixedPopulationError("shadow row in the executed population") from None
        executed.append(t)
    return {
        "shadow": {**_stats([o["net_pct"] for o in shadow], [o["gross_pct"] for o in shadow]),
                   "by_status": status, "closed_by_outcome_model": by_model,
                   "counted_as_paper_performance": False},
        "executed": _stats([float(t["net_pct"]) for t in executed],
                           [float(t["gross_pct"]) for t in executed]),
        "pooled": None,
        "note": "shadow opportunities are a selected, non-executed population; never pool",
    }


def merge_populations(*_args, **_kwargs):
    raise MixedPopulationError("shadow and executed statistics are never merged")
