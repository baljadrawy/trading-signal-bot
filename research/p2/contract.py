"""P2 canonical research dataset contract (P2-A).

Pure constants and pure functions only: no I/O, no third-party dependency. This module defines the governance
boundary (W1/W2/W3), the identity scheme, the provenance vocabulary, the canonical entity schemas, and the
historical decision-candle inference. It never reads outcome data.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import re

CONTRACT_VERSION = "p2a-contract-v1"
IDENTITY_VERSION = "v1"

# Governance: W3 = SEALED forward holdout (owner decision P2-G0). Boundary is exclusive for research: only
# authoritative timestamps strictly before FREEZE may enter canonical analytical data.
FREEZE_UTC = "2026-08-19T09:33:46Z"
FREEZE_SQL = "timestamp '2026-08-19 09:33:46'"            # production stores naive UTC
FREEZE_DATE_SQL = "date '2026-08-19'"                        # daily rows of the freeze day straddle the boundary
FREEZE_GIT_SHA = "63da7d3"
W1_END_EXCLUSIVE_SQL = "timestamp '2026-06-01 00:00:00'"   # W1 = through 2026-05-31 (certified candle coverage)
W1_END_EXCLUSIVE_UTC = "2026-06-01T00:00:00Z"


def _ms(iso_z: str) -> int:
    return int(_dt.datetime.fromisoformat(iso_z.replace("Z", "+00:00")).timestamp() * 1000)


FREEZE_MS = _ms(FREEZE_UTC)
W1_END_MS = _ms(W1_END_EXCLUSIVE_UTC)

WINDOWS = {
    "W1": "decision_time < 2026-06-01T00:00:00Z",
    "W2": "2026-06-01T00:00:00Z <= decision_time < 2026-08-19T09:33:46Z",
    "W3": "decision_time >= 2026-08-19T09:33:46Z (SEALED; never enters canonical analytical data)",
}

PROVENANCE = (
    "OBSERVED",               # recorded by the runtime at the time it happened (e.g. DB insert wall clock)
    "STORED_SNAPSHOT",        # value the runtime persisted with the decision (features_snapshot, geometry)
    "REBUILT_CERTIFIED",      # recomputed from a certified immutable dataset (e.g. ds-0928)
    "REBUILT_UNCERTIFIED",    # recomputed from data that is not (yet) certified
    "INFERRED",               # deterministic inference with an explicit method (e.g. decision candle)
    "APPROXIMATE",            # proxy value; never mixed with observed values
    "MISSING",                # not available
    "NOT_POINT_IN_TIME_SAFE", # present but could reveal information after the decision time
)
EXECUTION_PROVENANCE = ("PAPER_MODEL", "LIVE_EXECUTION")

MISSING_REASONS = ("NOT_COLLECTED", "NOT_APPLICABLE", "CANNOT_RECONSTRUCT", "AWAITING_P2B", "AWAITING_P2C",
                   "AWAITING_P2D")

TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

# Upper bound of the analysis-to-decision staleness accepted by signal_engine (analysis rows < 30 min old).
# Verified for current code (develop); for W1-era code it is an assumption and is flagged as such.
ANALYSIS_STALENESS_MS = 30 * 60 * 1000

# Names that must never appear in the feature (decision_market_context) layer.
OUTCOME_NAME_RE = re.compile(
    r"(^|[._])(result|results|profit\w*|pnl\w*|exit\w*|mfe\w*|mae\w*|wins?|loss(es)?|win_rate|wr|"
    r"\w*_hit|stop_hit|target_reached|duration\w*|outcome\w*|realized\w*|fwd_\w*|forward_\w*|return_\d+\w*|"
    r"label\w*|expectancy|profit_factor|pf)($|[._])", re.IGNORECASE)


def decision_uid(signal_id: int, symbol: str, timeframe: str, signal_time_text: str) -> str:
    """Deterministic historical decision identity (independent of row order and extraction run)."""
    key = f"tsb.p2.decision|{IDENTITY_VERSION}|sig|{int(signal_id)}|{symbol}|{timeframe}|{signal_time_text}"
    return "dec_" + hashlib.sha256(key.encode()).hexdigest()[:24]


def decision_key_for_candidate(candidate_id: str) -> str:
    """Forward (P1) decisions without a signal row are keyed by the P1 candidate_id itself."""
    return f"cand:{candidate_id}"


def candle_id(symbol: str, timeframe: str, open_time_ms: int) -> str:
    """Same format as P1 Evidence V2 `candle_id` (SYMBOL|timeframe|open_time_ms)."""
    return f"{symbol}|{timeframe}|{int(open_time_ms)}"


def infer_decision_candle(decision_ms: int, timeframe: str, staleness_ms: int = ANALYSIS_STALENESS_MS) -> dict:
    """Last candle of `timeframe` whose close_time (open + tf - 1 ms) is strictly before the decision.

    Ambiguous when a candle boundary falls inside (decision - staleness, decision]: the analysis the signal was
    built from may then have used the previous candle. Inference only; never labelled as observed.
    """
    tf = TF_MS[timeframe]
    open_ms = (decision_ms // tf) * tf - tf
    close_ms = open_ms + tf - 1
    earliest_analysis = decision_ms - staleness_ms
    ambiguous = (earliest_analysis // tf) != (decision_ms // tf)
    return {"open_ms": open_ms, "close_ms": close_ms, "ambiguous": ambiguous,
            "alt_open_ms": open_ms - tf if ambiguous else None}


def naive_utc_text_to_ms(text: str) -> int:
    """Production timestamps are naive UTC ('YYYY-MM-DD HH:MM:SS[.ffffff]'); TimeZone verified UTC."""
    d = _dt.datetime.fromisoformat(text)
    if d.tzinfo is not None:
        raise ValueError("expected naive UTC timestamp")
    return int(d.replace(tzinfo=_dt.timezone.utc).timestamp() * 1000)


def window_for_ms(decision_ms: int) -> str:
    if decision_ms >= FREEZE_MS:
        return "W3"
    return "W1" if decision_ms < W1_END_MS else "W2"


# Canonical entity schemas (column order is part of the contract; changing it bumps CONTRACT_VERSION).
SCHEMAS = {
    "decision": [
        "decision_uid", "decision_key", "signal_id", "candidate_id", "observed_candle_id", "symbol", "timeframe",
        "window", "decision_time_utc", "decision_time_ms", "decision_time_provenance", "strategy_version",
        "decision_source", "trade_type", "selection_policy", "market_condition", "score",
        "planned_entry", "planned_t1", "planned_t2", "planned_t3", "planned_stop", "geometry_provenance",
        "inferred_candle_id", "inferred_candle_open_ms", "inferred_candle_close_ms", "candle_provenance",
        "candle_inference_method", "candle_ambiguous", "candle_alt_open_ms", "candle_staleness_basis",
        "has_features_snapshot", "has_macro_snapshot", "risk_context_pit", "extraction_contract",
    ],
    "decision_market_context": [
        "decision_uid", "namespace", "feature_name", "value_json", "value_type", "provenance", "source",
        "observed_at_ms", "available_at_ms", "available_at_basis", "pit_safe", "feature_version",
    ],
    "market_outcome": [
        "decision_uid", "label_version", "horizon", "anchor", "label_name", "value", "provenance",
        "source_dataset_id", "computed_from_candles_through_ms", "censored_at_freeze",
    ],
    "execution_outcome": [
        "decision_uid", "signal_id", "window", "execution_provenance", "delivered", "admission_path",
        "approval_status", "approval_requested_ms", "approval_responded_ms", "entered", "active_trade_id",
        "entry_order_type", "planned_entry", "fill_price", "fill_time_ms", "fill_latency_ms",
        "fill_vs_planned_bps", "fill_price_basis", "no_fill_status",
    ],
    "trade_lifecycle": [
        "active_trade_id", "decision_uid", "signal_id", "window", "execution_provenance", "opened_ms",
        "status", "entry_order_type", "stop_policy", "exit_policy_version", "expiry_policy_version",
        "expiry_h", "t1_expiry_h", "no_t1_expiry_h", "highest_target_hit", "peak_price", "remaining_fraction",
        "realized_profit_percent", "realized_profit_usdt", "trade_result_id", "exit_ms", "exit_price",
        "result", "profit_percent", "profit_usdt", "target_reached", "stop_hit", "duration_hours",
        "failure_reason", "n_target_fills", "pnl_basis",
    ],
    "trade_target_fill": [
        "fill_id", "active_trade_id", "decision_uid", "target_number", "fill_price", "quantity_fraction",
        "notional_usdt", "gross_profit_percent_contribution", "gross_profit_usdt", "filled_ms",
        "execution_provenance", "fill_price_basis",
    ],
    "risk_context": [
        "risk_date", "signals_sent", "wins", "losses", "consecutive_losses", "daily_pnl_percent",
        "is_trading_paused", "pause_reason", "provenance", "pit_note",
    ],
    "provenance": [
        "source_id", "kind", "identity", "checksum_sha256", "authoritative_time_column", "w3_rule",
        "rows_included", "notes",
    ],
}

# Every timestamp column (ms) in the canonical analytical entities; all must be < FREEZE_MS.
TIME_COLUMNS_MS = {
    "decision": ["decision_time_ms", "inferred_candle_open_ms", "inferred_candle_close_ms"],
    "decision_market_context": ["observed_at_ms", "available_at_ms"],
    "execution_outcome": ["approval_requested_ms", "approval_responded_ms", "fill_time_ms"],
    "trade_lifecycle": ["opened_ms", "exit_ms"],
    "trade_target_fill": ["filled_ms"],
    "market_outcome": ["computed_from_candles_through_ms"],
}
