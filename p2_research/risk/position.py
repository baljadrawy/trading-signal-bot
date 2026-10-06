"""Canonical hypothetical position (RM0-POSITION 1.0.0): validation and duplicate-identity normalization.

Crypto / Binance spot only (the canonical ``p2_research.instrument`` identity). Long is the only AUTHORIZED side;
short exists conceptually in the contract and is refused unless ``conceptual_short=True`` (contract tests only).
Positions are hypothetical research inputs: Paper, live, account or balance provenance is refused.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .. import instrument as IN
from ..execution import model as XM

SIDES_AUTHORIZED = ("long",)
SIDES_CONCEPTUAL = ("long", "short")
PROVENANCE_CLASSES = ("SYNTHETIC_FIXTURE", "HYPOTHETICAL_RESEARCH")
REQUIRED = ("asset_class", "venue", "product", "instrument_id", "symbol", "quote_currency", "side", "quantity",
            "reference_price", "notional", "decision_time_ms", "reference_time_ms", "provenance")
OPTIONAL = ("hypothesis_id", "strategy_id")
_HYP = re.compile(r"^H-[A-Za-z0-9._-]+$")
_FORBIDDEN_PROV = re.compile(r"PAPER|LIVE|ACCOUNT|BALANCE", re.I)
NOTIONAL_RTOL = 1e-9


class PositionError(ValueError):
    pass


class UnauthorizedSide(PositionError):
    pass


class DuplicateIdentity(PositionError):
    pass


@dataclass(frozen=True)
class Position:
    asset_class: str
    venue: str
    product: str
    instrument_id: str
    symbol: str
    quote_currency: str
    side: str
    quantity: float
    reference_price: float
    notional: float
    decision_time_ms: int
    reference_time_ms: int
    provenance: tuple                      # sorted (key, value) pairs; canonical, hashable
    hypothesis_id: str | None = None
    strategy_id: str | None = None

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1

    @property
    def signed_notional(self) -> float:
        return self.sign * self.notional

    @property
    def base_currency(self) -> str:
        return IN.binance_spot_instrument(self.symbol).base_currency

    def as_dict(self) -> dict:
        d = asdict(self)
        d["provenance"] = {k: v for k, v in self.provenance}
        return d


def _num(x, what):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or x in (float("inf"), float("-inf")):
        raise PositionError(f"{what} must be a finite number, got {x!r}")
    if not x > 0:
        raise PositionError(f"{what} must be > 0, got {x!r}")
    return float(x)


def _int(x, what):
    if isinstance(x, bool) or not isinstance(x, int):
        raise PositionError(f"{what} must be an int (ms), got {x!r}")
    return x


def _prov(p) -> tuple:
    if not isinstance(p, dict) or not isinstance(p.get("source"), str) or not p.get("source"):
        raise PositionError("provenance must be an object with a non-empty source")
    if p.get("class") not in PROVENANCE_CLASSES:
        raise PositionError(f"provenance class must be one of {PROVENANCE_CLASSES}, got {p.get('class')!r}")
    for k, v in p.items():
        if not isinstance(k, str) or not isinstance(v, (str, int, float, bool, type(None), tuple)):
            raise PositionError("provenance values must be scalars")
        if _FORBIDDEN_PROV.search(f"{k}={v}"):
            raise PositionError(f"provenance refers to Paper / live / account / balance data: {k}={v!r} (refused)")
    return tuple(sorted(p.items()))


def validate(raw: dict, conceptual_short: bool = False) -> Position:
    """Validate one raw position dict (fail closed) and return the canonical Position."""
    if not isinstance(raw, dict):
        raise PositionError("position must be an object")
    unknown = sorted(set(raw) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        raise PositionError(f"unknown position fields: {unknown}")
    miss = [k for k in REQUIRED if k not in raw]
    if miss:
        raise PositionError(f"missing position fields: {miss}")
    sym = raw["symbol"]
    try:
        ins = IN.binance_spot_instrument(sym)
    except ValueError as e:
        raise PositionError(str(e)) from None
    IN.require_supported_market({"asset_class": raw["asset_class"], "venue": raw["venue"], "product": raw["product"]})
    for k in ("asset_class", "venue", "product", "instrument_id", "quote_currency"):
        if raw[k] != getattr(ins, k):
            raise PositionError(f"{k}={raw[k]!r} differs from the canonical identity {getattr(ins, k)!r}")
    side = raw["side"]
    if side not in SIDES_CONCEPTUAL:
        raise PositionError(f"side must be long|short, got {side!r}")
    if side not in SIDES_AUTHORIZED and not conceptual_short:
        raise UnauthorizedSide("short is conceptual in RM0-POSITION and NOT authorized (Binance spot is long-only)")
    qty = _num(raw["quantity"], "quantity")
    px = _num(raw["reference_price"], "reference_price")
    nt = _num(raw["notional"], "notional")
    if abs(nt - qty * px) > NOTIONAL_RTOL * nt:
        raise PositionError(f"notional {nt} != quantity x reference_price {qty * px}")
    dt_ = _int(raw["decision_time_ms"], "decision_time_ms")
    rt = _int(raw["reference_time_ms"], "reference_time_ms")
    if rt > dt_:
        raise PositionError("reference_time_ms must be <= decision_time_ms")
    XM.require_outside_w3(dt_, "position decision_time")
    hyp = raw.get("hypothesis_id")
    if hyp is not None and (not isinstance(hyp, str) or not _HYP.match(hyp)):
        raise PositionError(f"hypothesis_id must match ^H-..., got {hyp!r}")
    sid = raw.get("strategy_id")
    if sid is not None and not isinstance(sid, str):
        raise PositionError("strategy_id must be a string or null")
    return Position(asset_class=ins.asset_class, venue=ins.venue, product=ins.product, instrument_id=ins.instrument_id,
                    symbol=sym, quote_currency=ins.quote_currency, side=side, quantity=qty, reference_price=px,
                    notional=nt, decision_time_ms=dt_, reference_time_ms=rt, provenance=_prov(raw["provenance"]),
                    hypothesis_id=hyp, strategy_id=sid)


def normalize(raws, duplicates: str = "reject", conceptual_short: bool = False) -> tuple:
    """Validate every position and resolve duplicate instrument identities. Returns positions sorted by
    instrument_id plus a normalization log. ``duplicates`` = "reject" (default) | "aggregate"."""
    if duplicates not in ("reject", "aggregate"):
        raise PositionError(f"unknown duplicate policy {duplicates!r}")
    ps = [x if isinstance(x, Position) else validate(x, conceptual_short) for x in raws]
    if not conceptual_short and any(p.side not in SIDES_AUTHORIZED for p in ps):
        raise UnauthorizedSide("short position present without conceptual_short")
    by = {}
    for p in ps:
        by.setdefault(p.instrument_id, []).append(p)
    out, log = [], []
    for iid in sorted(by):
        grp = by[iid]
        if len(grp) == 1:
            out.append(grp[0])
            continue
        if len({p.side for p in grp}) > 1:
            raise DuplicateIdentity(f"opposite sides on one instrument are refused: {iid}")
        if duplicates == "reject":
            raise DuplicateIdentity(f"duplicate instrument identity refused: {iid} x{len(grp)}")
        grp = sorted(grp, key=lambda p: (p.decision_time_ms, p.reference_time_ms, p.notional, p.quantity,
                                         p.provenance, p.hypothesis_id or "", p.strategy_id or ""))
        qty = sum(p.quantity for p in grp)
        nt = sum(p.notional for p in grp)
        hyps = {p.hypothesis_id for p in grp}
        sids = {p.strategy_id for p in grp}
        prov = (("class", "HYPOTHETICAL_RESEARCH"), ("merged_from", len(grp)),
                ("source", "RM0-POSITION aggregate of " + ",".join(sorted({dict(p.provenance)["source"] for p in grp}))))
        out.append(Position(asset_class=grp[0].asset_class, venue=grp[0].venue, product=grp[0].product,
                            instrument_id=iid, symbol=grp[0].symbol, quote_currency=grp[0].quote_currency,
                            side=grp[0].side, quantity=qty, reference_price=nt / qty, notional=nt,
                            decision_time_ms=max(p.decision_time_ms for p in grp),
                            reference_time_ms=max(p.reference_time_ms for p in grp), provenance=prov,
                            hypothesis_id=hyps.pop() if len(hyps) == 1 else None,
                            strategy_id=sids.pop() if len(sids) == 1 else None))
        log.append({"instrument_id": iid, "merged": len(grp), "policy": "aggregate"})
    return tuple(out), log
