"""Descriptive replay metrics; these never assert an edge."""
from __future__ import annotations
import statistics


def trade_metrics(trades: list[dict]) -> dict:
    values = [float(t["net_pct"]) for t in trades if not t.get("intrabar_ambiguous")]
    wins = [v for v in values if v > 0]; losses = [v for v in values if v <= 0]
    pos, neg = sum(wins), -sum(losses)
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0
    return {"trade_count": len(values), "ambiguous_excluded": len(trades) - len(values),
            "net_expectancy": statistics.mean(values) if values else 0.0,
            "gross_expectancy": statistics.mean([float(t["gross_pct"]) for t in trades]) if trades else 0.0,
            "profit_factor": pos / neg if neg else None,
            "win_rate": len(wins) / len(values) * 100 if values else 0.0,
            "avg_win": avg_win, "avg_loss": avg_loss,
            "payoff_ratio": avg_win / abs(avg_loss) if avg_loss else None,
            "median_trade": statistics.median(values) if values else 0.0,
            "average_holding_hours": statistics.mean([float(t.get("duration_h", 0)) for t in trades]) if trades else 0.0}
