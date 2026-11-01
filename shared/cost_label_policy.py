"""Tracker cost booking under ``legacy_tracker_v1`` and the R4 single-count alternatives.

``trade_tracker/main.py`` books every cost through the bound model of ``shared/cost_models.py``
(``legacy_tracker_v1_from_config``). This module adds the two flagged R4 alternatives; both are
derived from that same registered model, and neither selects a research model (WP-IR-07).

**R4.a / R4.e (WP-E07): ``net_single_count_legacy_v1``.** The legacy flat round trip
``FEE_ROUNDTRIP_PCT`` is documented as fee plus a slippage allowance (``shared/config.py:L89-91``;
registry attribution ``fee_part_pct`` 0.2 + ``slippage_allowance_pct`` 0.1), while every stop exit
already fills at ``stop × (1 − STOP_SLIPPAGE)`` (``shared/triple_barrier.py:L320``). The
single-count rule books:

* the fee once per leg, on that leg's executed notional, at ``fee_part_pct / 2`` per side;
* slippage once, where it occurs: inside the stop fill, which the stored gross already contains.
  Target exits fill at the target and observed-price exits at the observation, so the legacy
  model itself states no in-price cost for them (``shared/cost_models.py``, component
  ``stop_fill_slippage``). This is the ``a48-cost-v1`` convention
  (``shared/execution_calibration.py``) with spread not modelled.

The attribution 0.2 + 0.1 holds only for the code defaults 0.3 and 0.001. Any other runtime value
refuses (``require_single_count_basis``), so the services refuse to start instead of inventing a
split. The stored legacy columns (``profit_percent``, ``profit_usdt``, ``result``) and the risk-guard
input (``trade_tracker/main.py`` ``assess_new_trade_risk``, SE-11) stay on the legacy model.

**R4.b (WP-G06): ``single_count_legacy_v1`` break-even.** The legacy post-T1 stop is
``entry × (1 + 0.003) / (1 − 0.001)`` (``shared/triple_barrier.py:L92-96``): both cost terms.
SE-42 gives ``entry × (1 + c_entry) / (1 − c_exit)`` from per-side costs. With the single-count
costs above, an exit at stop S nets ``S (1 − s)(1 − f)`` against the outlay ``entry (1 + f)``, so the
level is ``entry (1 + f) / ((1 − s)(1 − f))``. The pinned formula divides by ``(1 − s)`` itself, so
the wrapper passes ``roundtrip_cost = (1 + f) / (1 − f) − 1`` and leaves ``shared/triple_barrier.py``
unchanged. The result is capped at T1 by the pinned code. This changes exits: a strategy-version
boundary (WP-G06; OQ-08, SE-82, SE-83). It is never the default.

**R4.d / R7.f (WP-E06): counter basis.** ``COUNTER_BASES`` names the basis (gross, or net with its
``cost_model_id`` and ``label_policy``) of every counter and report figure of the tracker and
telegram. ``PAPER_COUNTER_LABELS`` (default ``off``) shows those tags and adds net counters,
stratified by ``label_policy``, beside the legacy gross counters; off changes nothing.

**R4.c (WP-E09): side-by-side cost report.** ``side_by_side_report`` books given synthetic legs
under ``legacy_tracker_v1`` and the two PROPOSED research models, one column per model, never
pooled (``docs/design/COST_REPORTING_SIDE_BY_SIDE.md``). No service calls it.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from shared import cost_models as _cm
from shared import fees as _fees
from shared.accounting_flags import (BREAK_EVEN_POLICIES, LABEL_POLICIES, LEGACY_BREAK_EVEN,
                                     LEGACY_LABEL_POLICY, SINGLE_COUNT_BREAK_EVEN,
                                     SINGLE_COUNT_LABEL_POLICY)
from shared.cost_models import LegacyTrackerV1, legacy_tracker_v1_from_config

if _fees.LABEL_POLICY != LEGACY_LABEL_POLICY:              # one name, two modules: kept equal
    raise RuntimeError("shared.fees.LABEL_POLICY changed; update shared.accounting_flags")


class SingleCountBasisError(RuntimeError):
    """The runtime costs are not the values the registry attribution describes."""


def bound_costs(cfg) -> LegacyTrackerV1:
    """``legacy_tracker_v1`` bound to ``cfg`` (FEE_ROUNDTRIP_PCT, STOP_SLIPPAGE, TRADE_AMOUNT_USDT).
    Invalid values raise ``CostModelError``; the services call this once at start-up."""
    return legacy_tracker_v1_from_config(cfg)


def fee_per_side(bound: LegacyTrackerV1) -> float:
    """``fee_part_pct / 2 / 100`` of the registered legacy model (0.001 at the code defaults)."""
    require_single_count_basis(bound)
    return float(bound.model.parameter("fee_part_pct").value) / 2 / 100.0


def require_single_count_basis(bound: LegacyTrackerV1) -> None:
    if not bound.matches_code_defaults():
        raise SingleCountBasisError(
            f"single-count costs need the registry attribution of FEE_ROUNDTRIP_PCT 0.3 and "
            f"STOP_SLIPPAGE 0.001; runtime is {bound.fee_roundtrip_pct!r} / {bound.stop_slippage!r}")


def validate_policies(bound: LegacyTrackerV1, *, cost_label_policy: str, break_even_policy: str) -> None:
    """Start-up check: known policy names, and the single-count basis when either needs it."""
    if cost_label_policy not in LABEL_POLICIES:
        raise RuntimeError(f"unknown cost label policy {cost_label_policy!r}")
    if break_even_policy not in BREAK_EVEN_POLICIES:
        raise RuntimeError(f"unknown break-even policy {break_even_policy!r}")
    if SINGLE_COUNT_LABEL_POLICY == cost_label_policy or SINGLE_COUNT_BREAK_EVEN == break_even_policy:
        require_single_count_basis(bound)


def leg_notionals(*, notional: float, entry_price: float, target_fills: Iterable,
                  final_exit_price: float, remaining_fraction: float) -> list:
    """Executed notional of every leg: the entry (the configured notional), each target fill
    ``(fraction, price)`` and the final exit of the remaining fraction (omitted when 0)."""
    entry = float(entry_price)
    out = [float(notional)]
    for fraction, price in target_fills:
        out.append(float(notional) * float(fraction) * float(price) / entry)
    if float(remaining_fraction) > 0:
        out.append(float(notional) * float(remaining_fraction) * float(final_exit_price) / entry)
    return out


def single_count_close(bound: LegacyTrackerV1, gross_usdt: float, *, entry_price: float,
                       target_fills: Sequence, final_exit_price: float,
                       remaining_fraction: float) -> dict:
    """The economic fields of one close under ``net_single_count_legacy_v1``, with the same keys,
    rounding and labels as ``shared.fees.economic_close``. ``target_fills`` are
    ``(quantity_fraction, fill_price)`` pairs of ``trade_target_fills``."""
    if not math.isfinite(float(gross_usdt)):
        raise ValueError(f"single_count_close: non-finite gross {gross_usdt!r}")
    rate = fee_per_side(bound)
    legs = leg_notionals(notional=bound.configured_notional_usdt, entry_price=entry_price,
                         target_fills=target_fills, final_exit_price=final_exit_price,
                         remaining_fraction=remaining_fraction)
    cost = rate * sum(legs)
    if not math.isfinite(cost) or cost < 0:
        raise ValueError(f"single_count_close: invalid cost {cost!r}")
    net = round(round(float(gross_usdt), 4) - cost, 6)
    return {'cost_usdt': round(cost, 6), 'net_profit_usdt': net,
            'economic_result': _fees.economic_result(net), 'label_policy': SINGLE_COUNT_LABEL_POLICY}


def close_economics(bound: LegacyTrackerV1, policy: str, gross_usdt: float, **legs) -> dict:
    """The stored economic fields under ``policy``. The legacy policy ignores ``legs`` and is
    exactly ``bound.economic_close(gross_usdt)``."""
    if policy == LEGACY_LABEL_POLICY:
        return bound.economic_close(gross_usdt)
    if policy == SINGLE_COUNT_LABEL_POLICY:
        return single_count_close(bound, gross_usdt, **legs)
    raise RuntimeError(f"unknown cost label policy {policy!r}")


def close_booking(bound: LegacyTrackerV1, policy: str, **legs):
    """The booking function of one close, ``gross_usdt -> economic fields``, under ``policy``.
    Legacy: ``bound.economic_close`` itself (the leg data is not used)."""
    if policy == LEGACY_LABEL_POLICY:
        return bound.economic_close
    if policy == SINGLE_COUNT_LABEL_POLICY:
        return lambda gross_usdt: single_count_close(bound, gross_usdt, **legs)
    raise RuntimeError(f"unknown cost label policy {policy!r}")


def break_even_roundtrip(bound: LegacyTrackerV1) -> float:
    """``roundtrip_cost`` that makes the pinned break-even formula equal the single-count level."""
    f = fee_per_side(bound)
    return (1 + f) / (1 - f) - 1


def barrier_cost_kwargs(bound: LegacyTrackerV1, policy: str) -> dict:
    """Cost arguments of ``create_config_from_trade``. Legacy: ``bound.barrier_cost_kwargs()``."""
    if policy == LEGACY_BREAK_EVEN:
        return bound.barrier_cost_kwargs()
    if policy == SINGLE_COUNT_BREAK_EVEN:
        return {"stop_slippage": bound.stop_slippage, "roundtrip_cost": break_even_roundtrip(bound)}
    raise RuntimeError(f"unknown break-even policy {policy!r}")


# ── WP-E06 (R4.d, R7.f; PR-C14, PR-15, CON-09): the basis of every counter and report figure ──
# Citations are ``@ 6ae70a2`` (the sources before this change). The tracker and telegram mix
# bases today: the ``risk_management.wins``/``losses`` counters and the ``result`` column are
# gross, ``daily_pnl_percent`` and the loss streak are net of the flat cost recomputed from the
# current config, and /stats and /performance count the stored economic label. A trade with
# 0 < gross < cost is a gross WIN, an economic LOSS and a streak loss at once (PR-T17).
#
# ``PAPER_COUNTER_LABELS`` (default ``off``; ``on``; any other value refuses to start) adds the
# basis tag to every such figure and a net-labelled counter beside each legacy gross counter.
# Off, every message, log line and database call is byte-identical to 6ae70a2. On, no stored
# value changes either: the net counters are counted from the economic fields every
# ``trade_results`` row already stores (``economic_result``, ``label_policy``; A38), stratified by
# ``label_policy`` and never pooled across policies (R4 test 4). A stored per-day net column
# would join the WP-E03 migration; none is added here.

COUNTER_LABELS_ENV = "PAPER_COUNTER_LABELS"
COUNTER_LABEL_MODES = ("off", "on")


def counter_labels_enabled(environ=None) -> bool:
    """``PAPER_COUNTER_LABELS``: missing means ``off``; an empty or unknown value raises."""
    env = os.environ if environ is None else environ
    raw = env.get(COUNTER_LABELS_ENV)
    if raw is None:
        return False
    value = str(raw).strip().lower()
    if value not in COUNTER_LABEL_MODES:
        raise RuntimeError(f"unknown {COUNTER_LABELS_ENV} {raw!r}; expected one of {COUNTER_LABEL_MODES}")
    return value == "on"


BASIS_GROSS = "gross_before_cost"
BASIS_NET_STORED = "net_stored"                       # the row's stored economic fields
BASIS_NET_STORED_ELSE_RECOMPUTED = "net_stored_else_recomputed"   # shared.fees.economic_result_sql
BASIS_NET_RECOMPUTED = "net_recomputed_flat"          # gross minus the flat cost of the current config
BASIS_COUNT = "count_no_pnl_basis"
COUNTER_BASIS_KINDS = (BASIS_GROSS, BASIS_NET_STORED, BASIS_NET_STORED_ELSE_RECOMPUTED,
                       BASIS_NET_RECOMPUTED, BASIS_COUNT)
POLICY_PER_ROW = "per_row_label_policy"              # each row names its own label_policy

LEGACY_TRACKER_V1 = _cm.LEGACY_TRACKER_V1
# Both tracker label policies are rules of the registered legacy model (module docstring).
LABEL_POLICY_COST_MODEL = {LEGACY_LABEL_POLICY: LEGACY_TRACKER_V1,
                           SINGLE_COUNT_LABEL_POLICY: LEGACY_TRACKER_V1}
UNSPECIFIED_COST_MODEL = "UNSPECIFIED"


@dataclass(frozen=True)
class CounterBasis:
    """The basis of one counter or report figure. ``cost_model_id`` and ``label_policy`` are
    ``None`` for a gross or a plain count figure, which carries no cost."""
    field: str
    basis: str
    cost_model_id: str | None
    label_policy: str | None
    source: str

    def __post_init__(self):
        if self.basis not in COUNTER_BASIS_KINDS:
            raise ValueError(f"unknown counter basis {self.basis!r}")
        costless = self.basis in (BASIS_GROSS, BASIS_COUNT)
        named = (self.cost_model_id is not None, self.label_policy is not None)
        if named != ((False, False) if costless else (True, True)):
            raise ValueError(f"{self.field}: a net figure names its cost model and label policy, "
                             f"a gross or count figure names neither")

    def tag(self) -> str:
        if self.cost_model_id is None:
            return f"[{self.basis}]"
        return f"[{self.basis} · {self.cost_model_id} · {self.label_policy}]"


_TT6 = "trade_tracker/main.py"
_TG6 = "telegram/main.py"
_C = "@ 6ae70a2"

COUNTER_BASES = {b.field: b for b in (
    # trade_tracker: stored columns, the risk counters and the close event
    CounterBasis("trade_results.result", BASIS_GROSS, None, None, f"{_TT6}:L1525 {_C}"),
    CounterBasis("trade_results.profit_usdt", BASIS_GROSS, None, None, f"{_TT6}:L1524 {_C}"),
    CounterBasis("trade_results.economic_result", BASIS_NET_STORED, LEGACY_TRACKER_V1,
                 POLICY_PER_ROW, f"{_TT6}:L1502-1528 {_C}"),
    CounterBasis("risk_management.wins", BASIS_GROSS, None, None, f"{_TT6}:L1532-1540 {_C}"),
    CounterBasis("risk_management.losses", BASIS_GROSS, None, None, f"{_TT6}:L1532-1540 {_C}"),
    CounterBasis("risk_management.daily_pnl_percent", BASIS_NET_RECOMPUTED, LEGACY_TRACKER_V1,
                 LEGACY_LABEL_POLICY, f"{_TT6}:L1086-1100, L1209-1222 {_C} (includes unrealized)"),
    CounterBasis("risk_management.consecutive_losses", BASIS_NET_RECOMPUTED, LEGACY_TRACKER_V1,
                 LEGACY_LABEL_POLICY, f"{_TT6}:L1092, L1104 {_C}; shared/risk_epoch.py"),
    CounterBasis("risk_management.signals_sent", BASIS_COUNT, None, None,
                 f"signal_engine/signal_logic.py:L1017-1020 {_C}"),
    CounterBasis("evidence.trade.closed.result_label", BASIS_GROSS, None, None, f"{_TT6}:L447 {_C}"),
    CounterBasis("evidence.trade.closed.net_profit_usdt", BASIS_NET_RECOMPUTED, LEGACY_TRACKER_V1,
                 LEGACY_LABEL_POLICY, f"{_TT6}:L446 {_C}"),
    CounterBasis("tracker.close_log.result", BASIS_GROSS, None, None, f"{_TT6}:L1553, L1557-1561 {_C}"),
    # telegram reports
    CounterBasis("status.wins", BASIS_GROSS, None, None, f"{_TG6}:L790 {_C}"),
    CounterBasis("status.losses", BASIS_GROSS, None, None, f"{_TG6}:L791 {_C}"),
    CounterBasis("stats.wins_losses_breakeven", BASIS_NET_STORED_ELSE_RECOMPUTED, LEGACY_TRACKER_V1,
                 POLICY_PER_ROW, f"{_TG6}:L960-966, L981-983 {_C} (pooled over label policies)"),
    CounterBasis("stats.gross_wins_losses", BASIS_GROSS, None, None, f"{_TG6}:L967-968, L984-985 {_C}"),
    CounterBasis("stats.net_pnl", BASIS_NET_RECOMPUTED, LEGACY_TRACKER_V1, LEGACY_LABEL_POLICY,
                 f"{_TG6}:L975-977, L986-987 {_C}"),
    CounterBasis("trades.net", BASIS_NET_RECOMPUTED, LEGACY_TRACKER_V1, LEGACY_LABEL_POLICY,
                 f"{_TG6}:L1022-1032 {_C}"),
    CounterBasis("performance.wins_losses", BASIS_NET_STORED_ELSE_RECOMPUTED, LEGACY_TRACKER_V1,
                 POLICY_PER_ROW, f"{_TG6}:L1136-1146 {_C} (pooled over label policies)"),
    CounterBasis("daily.wins_losses", BASIS_GROSS, None, None, f"{_TG6}:L1244-1245, L1264 {_C}"),
    CounterBasis("daily.net", BASIS_NET_RECOMPUTED, LEGACY_TRACKER_V1, LEGACY_LABEL_POLICY,
                 f"{_TG6}:L1218-1224, L1265 {_C}"),
    CounterBasis("closed_message.gross", BASIS_GROSS, None, None,
                 f"shared/telegram_messages.py:L145 {_C}"),
    CounterBasis("closed_message.net", BASIS_NET_RECOMPUTED, LEGACY_TRACKER_V1, LEGACY_LABEL_POLICY,
                 f"shared/telegram_messages.py:L124-128, L147 {_C}"),
    CounterBasis("net_counter", BASIS_NET_STORED_ELSE_RECOMPUTED, LEGACY_TRACKER_V1, POLICY_PER_ROW,
                 "shared/cost_label_policy.py net_counter_sql (new, stratified)"),
)}


def counter_tag(field: str) -> str:
    """The basis tag of a registered field; an unregistered field raises KeyError."""
    return COUNTER_BASES[field].tag()


def net_counter_sql(where_sql: str) -> str:
    """Counts of ``trade_results`` rows by ``label_policy`` and economic label over ``where_sql``,
    with ``$1`` the current flat cost (as /stats). A row without a stored label (before A38) is
    labelled by ``shared.fees.economic_result_sql``, which is the legacy policy's own rule."""
    label = _fees.economic_result_sql('$1::numeric')
    return (f"SELECT COALESCE(label_policy, '{LEGACY_LABEL_POLICY}') AS label_policy, "
            f"{label} AS economic_result, COUNT(*) AS n FROM trade_results "
            f"WHERE {where_sql} GROUP BY 1, 2 ORDER BY 1, 2")


@dataclass(frozen=True)
class NetCounter:
    """Net counters of ONE label policy. ``unlabelled`` counts rows whose label is NULL (an
    invalid historical value, ``economic_result_sql``)."""
    label_policy: str
    cost_model_id: str
    wins: int
    losses: int
    breakeven: int
    unlabelled: int

    def tag(self) -> str:
        return f"[{BASIS_NET_STORED_ELSE_RECOMPUTED} · {self.cost_model_id} · {self.label_policy}]"


def net_counter_strata(rows) -> tuple:
    """One ``NetCounter`` per label policy, sorted by policy name. Rows are
    ``{label_policy, economic_result, n}``. An unregistered policy gets its own stratum with
    ``cost_model_id`` UNSPECIFIED; strata are never added together."""
    acc: dict = {}
    for row in rows or ():
        policy = row['label_policy']
        if not isinstance(policy, str) or not policy:
            raise ValueError(f"net counter row without a label policy: {dict(row)!r}")
        n = int(row['n'] or 0)
        label = row['economic_result']
        key = {'WIN': 'wins', 'LOSS': 'losses', 'BREAKEVEN': 'breakeven'}.get(label, 'unlabelled')
        if label is not None and key == 'unlabelled':
            raise ValueError(f"unknown economic label {label!r}")
        acc.setdefault(policy, {'wins': 0, 'losses': 0, 'breakeven': 0, 'unlabelled': 0})[key] += n
    return tuple(NetCounter(p, LABEL_POLICY_COST_MODEL.get(p, UNSPECIFIED_COST_MODEL), **acc[p])
                 for p in sorted(acc))


def require_single_label_policy(strata) -> NetCounter:
    """The one stratum of ``strata``; more than one policy refuses (no unstratified pooling)."""
    strata = tuple(strata)
    if len(strata) != 1:
        raise ValueError(f"refused: {len(strata)} label policies cannot be reported as one figure")
    return strata[0]


def close_counter_log(profit_usdt: float, econ: dict) -> str:
    """The tracker's labelled counter line for one recorded close (``PAPER_COUNTER_LABELS=on``):
    the legacy gross increment and, beside it, the net label stored on the same row."""
    column = 'wins' if profit_usdt > 0 else 'losses'
    policy = econ['label_policy']
    cost_model_id = LABEL_POLICY_COST_MODEL.get(policy, UNSPECIFIED_COST_MODEL)
    return (f"counter basis: risk_management.{column} +1 {counter_tag('risk_management.' + column)}"
            f" | net {econ['economic_result']} [{BASIS_NET_STORED} · {cost_model_id} · {policy}]"
            f" (trade_results.economic_result)")


# ── WP-E09 (R4.c, OQ-08; DFP:L61): side-by-side cost report on synthetic trades ─────────────
# The runtime model next to the two PROPOSED research models, each figure under its own
# cost_model_id and label_policy, never pooled. It is a pure function on given synthetic legs; no
# service imports it and no live report calls it (docs/design/COST_REPORTING_SIDE_BY_SIDE.md).

SIDE_BY_SIDE_SCHEME = "tsb-cost-side-by-side/1"
SIDE_BY_SIDE_EVIDENCE_CLASS = "synthetic"


def side_by_side_report(trades: Mapping, *, legacy: LegacyTrackerV1, evidence_class: str) -> dict:
    """``trades`` maps ``position_id`` to its ``shared.cost_models.Leg`` sequence. Every trade is
    booked separately under ``legacy_tracker_v1`` (bound to ``legacy``), ``research_baseline_v1``
    and ``research_stress_v1``. Returns one column per model, keyed by ``cost_model_id``, with no
    total across columns. Only ``evidence_class='synthetic'`` is accepted: running research models
    on recorded trades is PR-C15 and needs its own authorization."""
    if evidence_class != SIDE_BY_SIDE_EVIDENCE_CLASS:
        raise ValueError(f"side_by_side_report accepts synthetic trades only, not {evidence_class!r}")
    if not isinstance(legacy, LegacyTrackerV1):
        raise TypeError("legacy must be a bound legacy_tracker_v1")
    items = sorted(dict(trades).items())
    if not items:
        raise ValueError("side_by_side_report: no trades")
    pricers = ((LEGACY_TRACKER_V1, legacy),
               (_cm.RESEARCH_BASELINE_V1, _cm.ResearchPricer(_cm.RESEARCH_BASELINE_V1)),
               (_cm.RESEARCH_STRESS_V1, _cm.ResearchPricer(_cm.RESEARCH_STRESS_V1)))
    columns, gross = {}, None
    for cost_model_id, pricer in pricers:
        booked = []
        for position_id, legs in items:
            book = _cm.CostBook(pricer, position_id=position_id)
            for leg in legs:
                book.book(leg)
            booked.append(book.close())
        totals = _cm.aggregate(booked)             # one model only; refuses a mix
        model = pricer.model
        per_trade = {t.position_id: {"gross_reference_pnl": t.gross_reference_pnl,
                                     "total_costs": t.total_costs, "net_pnl": t.net_pnl,
                                     "net_label": _fees.economic_result(t.net_pnl)}
                     for t in booked}
        trade_gross = {p: v["gross_reference_pnl"] for p, v in per_trade.items()}
        if gross is None:
            gross = trade_gross
        elif gross != trade_gross:                 # the gross is model-independent by construction
            raise RuntimeError("side_by_side_report: gross differs between models")
        labels = [v["net_label"] for v in per_trade.values()]
        columns[cost_model_id] = {
            "cost_model_id": cost_model_id, "label_policy": model.label_policy,
            "model_status": model.status, "round_trip_pct": model.round_trip_pct,
            "content_hash": model.content_hash, "trades": totals["trades"],
            "fees": totals["fees"], "explicit_costs": totals["explicit_costs"],
            "in_price_costs": totals["in_price_costs"], "net_pnl": totals["net_pnl"],
            "net_wins": labels.count("WIN"), "net_losses": labels.count("LOSS"),
            "net_breakeven": labels.count("BREAKEVEN"),
            "double_counted_kinds": sorted({k for t in booked for k in t.double_counted_kinds}),
            "per_trade": per_trade,
        }
    gross_rows = list(gross.values())
    return {"scheme": SIDE_BY_SIDE_SCHEME, "evidence_class": evidence_class,
            "not_profitability_evidence": True, "pooled": False,
            "binding": legacy.binding(),
            "gross": {"basis": BASIS_GROSS, "trades": len(gross_rows),
                      "gross_reference_pnl": sum(gross_rows, Decimal(0)),
                      "gross_wins": sum(1 for g in gross_rows if g > 0),
                      "gross_losses": sum(1 for g in gross_rows if g <= 0)},
            "columns": columns}


def render_side_by_side(report: dict) -> list:
    """Plain-text lines: one block per model, every figure tagged with its cost_model_id and
    label_policy. There is no combined line."""
    g = report["gross"]
    lines = [f"evidence_class={report['evidence_class']} (not profitability evidence)",
             f"gross [{g['basis']}]: trades={g['trades']} pnl={g['gross_reference_pnl']} "
             f"wins={g['gross_wins']} losses={g['gross_losses']}"]
    for cost_model_id in _cm.COST_MODEL_IDS:
        c = report["columns"][cost_model_id]
        tag = f"[{c['cost_model_id']} · {c['label_policy']} · {c['model_status']}]"
        lines.append(f"{tag} round_trip_pct={c['round_trip_pct']} fees={c['fees']} "
                     f"explicit={c['explicit_costs']} in_price={c['in_price_costs']} "
                     f"net_pnl={c['net_pnl']} net_wins={c['net_wins']} "
                     f"net_losses={c['net_losses']} net_breakeven={c['net_breakeven']}")
    return lines
