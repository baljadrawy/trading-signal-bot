"""Build explicitly inferred universe events from normalized market-data presence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def build_events(quality: list[dict], *, historical_end: str) -> tuple[list[dict], dict]:
    by_symbol: dict[str, list[dict]] = {}
    for row in quality:
        if row.get("status") in {"PASS", "WARN"}:
            by_symbol.setdefault(row["symbol"], []).append(row)
    events = []
    for symbol, rows in sorted(by_symbol.items()):
        first = min(row["first_open"] for row in rows)
        last = max(row["last_close"] for row in rows)
        events.append({
            "symbol": symbol, "quote_asset": "USDT", "event_type": "LISTED",
            "event_time": first, "source_tier": "B", "source": "Binance Public Data spot klines",
            "source_reference": "first observed official archive candle",
            "evidence_timestamp": first, "confidence": "MEDIUM",
            "evidence_kind": "FIRST_TRADE_OBSERVED_NOT_LISTING_ANNOUNCEMENT",
        })
        # A missing tail materially establishes no archive data, but not the legal delisting time.
        if last < historical_end:
            events.append({
                "symbol": symbol, "quote_asset": "USDT", "event_type": "DELISTED",
                "event_time": last, "source_tier": "D", "source": "Binance Public Data spot klines",
                "source_reference": "last observed official archive candle",
                "evidence_timestamp": last, "confidence": "LOW",
                "evidence_kind": "INFERRED_LAST_DATA",
            })
    confidence = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for symbol in by_symbol:
        levels = {e["confidence"] for e in events if e["symbol"] == symbol}
        confidence["MEDIUM" if "MEDIUM" in levels else "LOW"] += 1
    summary = {
        "symbols_total": len(by_symbol), "symbols_high_confidence": confidence["HIGH"],
        "symbols_medium_confidence": confidence["MEDIUM"],
        "symbols_low_confidence": confidence["LOW"], "symbols_unknown": confidence["UNKNOWN"],
        "known_delistings": sum(e["event_type"] == "DELISTED" and e["source_tier"] == "A" for e in events),
        "inferred_delistings": sum(e["event_type"] == "DELISTED" and e["evidence_kind"] == "INFERRED_LAST_DATA" for e in events),
        "known_listings": 0,
        "inferred_listings": sum(e["event_type"] == "LISTED" for e in events),
        "survivorship_status": "MATERIAL_SURVIVORSHIP_LIMITATION",
        "rule": "Official archive presence controls historical availability; event times remain inferred unless Tier A evidence exists.",
    }
    return events, summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--quality", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--historical-end", default="2026-05-31T23:59:59.999999+00:00")
    a = p.parse_args(argv)
    if a.output.exists(): raise FileExistsError(a.output)
    events, summary = build_events(json.loads(a.quality.read_text()), historical_end=a.historical_end)
    a.output.mkdir(parents=True)
    (a.output / "universe_events.json").write_text(json.dumps(events, indent=2, sort_keys=True) + "\n")
    (a.output / "universe_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
