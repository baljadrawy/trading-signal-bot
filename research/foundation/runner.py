"""Dataset-to-artifacts runner for deterministic offline experiments."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any
import pandas as pd

from shared.execution import rebase_long_bracket
from shared.risk_management import RiskLimits, RiskSnapshot, evaluate_new_trade
from .contract import current_contract
from .costs import CostModel
from .dataset import DatasetSnapshot, universe_at
from .experiment import ExperimentWriter
from .holdout import allow_partition
from .labels import excursions, forward_labels, forward_time_labels
from .metrics import trade_metrics
from .opportunity import RejectionCode
from .quality import validate_candles
from .replay import ReplayContext, config_from_levels, evaluate_opportunity
from .replay_position import ReplayPosition, apply_costs
from .portfolio import mark_to_market, risk_fields


def run_experiment(*, dataset: DatasetSnapshot, writer: ExperimentWriter,
                   indicator_params: dict[str, Any], config: dict[str, Any]) -> dict:
    partition = config.get("research_partition", "UNASSIGNED")
    allow_partition(partition, purpose="replay", unlock_holdout=bool(config.get("unlock_holdout")))
    contract = writer.contract; frames = []; quality_rows = []
    for item in dataset.manifest["identity"]["files"]:
        path = dataset.root / "files" / item["name"]
        if path.suffix.lower() != ".csv": continue
        frame = pd.read_csv(path)
        if not {"symbol", "timeframe"}.issubset(frame.columns):
            quality_rows.append({"file": item["name"], "status": "FAIL",
                                 "failures": ["symbol_and_timeframe_required"]}); continue
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True)
        for (symbol, timeframe), group in frame.groupby(["symbol", "timeframe"], sort=True):
            group = group.sort_values("timestamp").reset_index(drop=True)
            q = validate_candles(group, str(timeframe)); quality_rows.append({"file": item["name"],
                "symbol": symbol, "timeframe": timeframe, **q})
            if q["status"] != "FAIL": frames.append((str(symbol), str(timeframe), group))
    context = ReplayContext(dataset.dataset_id, writer.manifest["experiment_id"],
        writer.manifest["git_sha"], config.get("strategy_version", "sb-2026.08"),
        partition, contract, indicator_params)
    opportunities: list[tuple[Any, dict | None, pd.DataFrame, int]] = []
    universe = dataset.manifest["identity"]["universe"]
    for symbol, timeframe, frame in frames:
        for i in range(199, len(frame) - 1):
            row = frame.iloc[i]; decision = pd.Timestamp(row["close_time"]).isoformat()
            market = _market(row)
            eligible = symbol in universe_at(universe, decision)
            record, levels = evaluate_opportunity(raw_history=frame.iloc[:i + 1],
                decision_time=decision, symbol=symbol, timeframe=timeframe,
                market=market, context=context, universe_eligible=eligible)
            opportunities.append((record, levels, frame, i))
    opportunities = sorted(_apply_ranking(opportunities),
                           key=lambda x: (x[0].decision_time, x[0].symbol, x[0].timeframe))
    trades, events = [], []
    processed = []
    peak_equity = contract["risk"]["capital_usdt"]
    for record, levels, frame, i in opportunities:
        future = frame.iloc[i + 1:].copy()
        if levels:
            decision = pd.Timestamp(record.decision_time)
            risk = _risk_decision(record, trades, decision, frames, contract, peak_equity)
            state = {**record.strategy_state, "risk_admission_pass": risk.allowed,
                     "risk_reason": risk.reason}
            if not risk.allowed:
                code = _risk_rejection(risk.reason)
                record = replace(record, accepted=False, rejection_code=code.value,
                                 rejection_detail={"risk_reason": risk.reason},
                                 strategy_state=state)
                levels = None
            else:
                record = replace(record, strategy_state=state)
        if levels:
            trade = _replay_trade(record, levels, future, contract, config)
            if trade:
                trades.append(trade); events.extend(trade.pop("events"))
                peak_equity = max(peak_equity, contract["risk"]["capital_usdt"] +
                                  sum(float(t["net_usdt"]) for t in trades))
        processed.append((record, levels, frame, i))
    opportunities = processed
    # Rebuild labelled records deterministically without mutating decision features.
    emitted = []
    for record, levels, frame, i in opportunities:
        future = frame.iloc[i + 1:].copy(); labels = {}
        entry = levels["entry"] if levels else record.features.get("close")
        if entry and not future.empty:
            label_window = future.head(int(config.get("label_horizon_bars", 24)))
            labels = {**forward_labels(float(entry), future),
                      **forward_time_labels(float(entry), record.decision_time, future),
                      **excursions(float(entry), label_window,
                                   before_t1=levels["t1"] if levels else None)}
        emitted.append(replace(record, labels=labels).as_dict())
    writer.write_jsonl("opportunities.jsonl", emitted)
    writer.write_jsonl("trades.jsonl", trades)
    writer.write_jsonl("trade_events.jsonl", events)
    metrics = trade_metrics(trades)
    prices = {}
    for symbol, _, frame in frames:
        prices.setdefault(symbol, {}).update({pd.Timestamp(row["timestamp"]).isoformat(): float(row["close"])
                                               for _, row in frame.iterrows()})
    equity, exposure = mark_to_market(contract["risk"]["capital_usdt"], trades, prices)
    writer.write_jsonl("equity_curve.jsonl", equity)
    metrics["portfolio"] = exposure
    quality = {"files": quality_rows,
               "pass": sum(x["status"] == "PASS" for x in quality_rows),
               "warn": sum(x["status"] == "WARN" for x in quality_rows),
               "failure": sum(x["status"] == "FAIL" for x in quality_rows)}
    parity = {"exact_match": 0, "acceptable_known_difference": 0, "failure": 0,
              "note": "No production golden-case snapshot supplied."}
    counts = {"opportunities": len(emitted), "accepted": sum(x["accepted"] for x in emitted),
              "trades": len(trades), "trade_events": len(events), "equity_rows": len(equity)}
    writer.finish(counts=counts, warnings=[], parity=parity, quality=quality, metrics=metrics)
    return {"experiment_id": writer.manifest["experiment_id"], "counts": counts, "metrics": metrics}


def _market(row) -> dict:
    def value(name, default=None):
        v = row.get(name, default)
        return default if pd.isna(v) else v
    macro = value("macro_pass")
    if isinstance(macro, str): macro = macro.lower() in {"1", "true", "yes"}
    return {"btc_return": value("btc_return"), "usdt_d_state": value("usdt_d_state"),
            "macro_pass": macro, "quote_volume": value("quote_volume"),
            "spread": value("spread"), "change_24h_pct": value("change_24h_pct"),
            "spread_data_mode": value("spread_data_mode", "NO_SPREAD_DATA")}


def _apply_ranking(items):
    grouped = {}
    for item in items:
        if item[0].accepted: grouped.setdefault(item[0].decision_time, []).append(item)
    winners = set()
    for candidates in grouped.values():
        best = min(candidates, key=lambda x: (float(x[0].liquidity["spread"]),
            -float(x[0].liquidity["quote_volume"]), x[0].symbol, x[0].timeframe))
        winners.add(best[0].opportunity_id)
    output = []
    for record, levels, frame, i in items:
        if record.accepted and record.opportunity_id not in winners:
            record = replace(record, accepted=False,
                rejection_code=RejectionCode.REJECT_RANK_CAPACITY.value,
                rejection_detail={"policy": "fixed_execution_quality_v1"})
            levels = None
        output.append((record, levels, frame, i))
    return output


def _risk_rejection(reason: str) -> RejectionCode:
    return {"daily_loss_limit": RejectionCode.REJECT_DAILY_RISK,
            "weekly_loss_limit": RejectionCode.REJECT_WEEKLY_RISK,
            "max_drawdown_limit": RejectionCode.REJECT_DRAWDOWN,
            "max_open_trades": RejectionCode.REJECT_MAX_TRADES}.get(
                reason, RejectionCode.REJECT_PORTFOLIO_CAP)


def _risk_decision(record, trades, decision, frames, contract, peak_equity):
    closed = [t for t in trades if pd.Timestamp(t["exit_time"]) <= decision]
    opened = [t for t in trades if pd.Timestamp(t["entry_time"]) <= decision < pd.Timestamp(t["exit_time"])]
    realized = sum(float(t["net_usdt"]) for t in closed)
    day = decision.date(); week_start = day - pd.Timedelta(days=day.weekday())
    daily = sum(float(t["net_usdt"]) for t in closed if pd.Timestamp(t["exit_time"]).date() == day)
    weekly = sum(float(t["net_usdt"]) for t in closed
                 if week_start <= pd.Timestamp(t["exit_time"]).date() <= day)
    unrealized = 0.0
    for trade in opened:
        price = _price_at(frames, trade["symbol"], decision)
        if price is None:
            return type("RiskUnavailable", (), {"allowed": False,
                "reason": "historical_mark_price_unavailable"})()
        unrealized += (price / float(trade["entry_price"]) - 1) * float(trade["notional"])
    losses = 0
    for trade in sorted(closed, key=lambda t: t["exit_time"], reverse=True):
        if float(trade["net_usdt"]) >= 0: break
        losses += 1
    r = contract["risk"]
    limits = RiskLimits(capital_usdt=r["capital_usdt"], trade_amount_usdt=r["trade_amount_usdt"],
        max_open_trades=r["max_open_trades"], max_gross_exposure_pct=r["max_gross_exposure_pct"],
        max_symbol_exposure_pct=r["max_symbol_exposure_pct"],
        max_strategy_exposure_pct=r["max_strategy_exposure_pct"],
        max_regime_exposure_pct=r["max_regime_exposure_pct"],
        max_daily_loss_pct=r["max_daily_loss_pct"], max_weekly_loss_pct=r["max_weekly_loss_pct"],
        max_drawdown_pct=r["max_drawdown_pct"], loss_halt_count=r["loss_halt_count"])
    snapshot = RiskSnapshot(realized_total_usdt=realized, daily_pnl_usdt=daily,
        weekly_pnl_usdt=weekly, unrealized_pnl_usdt=unrealized, peak_equity_usdt=peak_equity,
        open_count=len(opened), symbol_open_count=sum(t["symbol"] == record.symbol for t in opened),
        consecutive_losses=losses,
        strategy_open_count=sum(t.get("trade_type") == record.strategy_state.get("trade_type_candidate") for t in opened),
        regime_open_count=sum(t.get("market_regime") == record.market_context.get("market_regime") for t in opened))
    return evaluate_new_trade(snapshot, limits)


def _price_at(frames, symbol: str, decision) -> float | None:
    candidates = []
    for sym, _, frame in frames:
        if sym != symbol: continue
        rows = frame[pd.to_datetime(frame["close_time"], utc=True) <= decision]
        if not rows.empty: candidates.append((pd.Timestamp(rows.iloc[-1]["close_time"]), float(rows.iloc[-1]["close"])))
    return max(candidates)[1] if candidates else None


def _replay_trade(record, levels, future, contract, config):
    fill = None; fill_i = None; planned = levels["entry"]
    for idx, row in future.iterrows():
        open_price, low = float(row["open"]), float(row["low"])
        if open_price <= levels["stop"]: return None
        if open_price <= planned: fill, fill_i = open_price, idx; break
        if low <= levels["stop"]: return None  # stop and unfilled limit crossed: fail closed
        if low <= planned: fill, fill_i = planned, idx; break
    if fill is None: return None
    bracket = rebase_long_bracket(planned, fill, levels["t1"], levels["t2"],
                                  levels["t3"], levels["stop"])
    rebased = {"entry": bracket["entry_price"], "t1": bracket["target_1"],
               "t2": bracket["target_2"], "t3": bracket["target_3"], "stop": bracket["stop_loss"]}
    cfg = config_from_levels(record.symbol, record.timeframe, rebased, contract)
    fill_row = future.loc[fill_i]; opened_ms = int(pd.Timestamp(fill_row["timestamp"]).timestamp() * 1000)
    position = ReplayPosition(record.opportunity_id, cfg, opened_ms,
                              levels["stop_invalidation"], record.timeframe)
    hours = {"15m": .25, "1h": 1, "4h": 4, "1d": 24}[record.timeframe]
    result = None
    for _, row in future.loc[fill_i:].iloc[1:].iterrows():
        candle = row.to_dict(); candle["timestamp"] = pd.Timestamp(row["timestamp"]).isoformat()
        candle["close_time_ms"] = int(pd.Timestamp(row["close_time"]).timestamp() * 1000)
        result = position.step(candle, hours=hours,
                               intrabar_policy=config.get("intrabar_policy", "CONSERVATIVE"))
        if result: break
    if not result: return None
    result = apply_costs(result, cfg.trade_amount, CostModel(**config.get("cost_model", {})))
    observed = future.loc[fill_i:].copy()
    result.update(excursions(cfg.entry, observed, before_t1=cfg.target_1))
    result.update({"opportunity_id": record.opportunity_id, "symbol": record.symbol,
                   "timeframe": record.timeframe, "entry_time": pd.Timestamp(fill_row["timestamp"]).isoformat(),
                   "fill_time": pd.Timestamp(fill_row["timestamp"]).isoformat(),
                   "exit_time": result["events"][-1]["timestamp"],
                   "fill_model": "NEXT_OBSERVABLE_MARKET_OR_LIMIT",
                   "intrabar_policy": config.get("intrabar_policy", "CONSERVATIVE"),
                   "trade_type": record.strategy_state.get("trade_type_candidate"),
                   "market_regime": record.market_context.get("market_regime"),
                   **risk_fields(cfg.entry, cfg.stop_loss, cfg.trade_amount,
                                 contract["risk"]["capital_usdt"])})
    return result
