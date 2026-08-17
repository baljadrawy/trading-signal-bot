"""Phase-6 portfolio analytics from clean closed paper trades."""
from __future__ import annotations

import asyncio
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.strategy_performance_review import metrics
from shared.config import config
from shared.database import Database
from shared.schema import require_schema


def max_drawdown(equity):
    peak = equity[0]
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak if peak else 0.0)
    return worst


def longest_underwater(equity):
    peak, current, longest = equity[0], 0, 0
    for value in equity[1:]:
        if value >= peak:
            peak, current = value, 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return math.nan
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] if lo == hi else ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def portfolio_metrics(daily_pnl, initial_capital):
    equity = [float(initial_capital)]
    returns = []
    for pnl in daily_pnl:
        previous = equity[-1]
        equity.append(previous + float(pnl))
        returns.append(float(pnl) / previous if previous else 0.0)
    mean = statistics.mean(returns) if returns else 0.0
    std = statistics.stdev(returns) if len(returns) > 1 else 0.0
    downside = [value for value in returns if value < 0]
    downside_std = statistics.stdev(downside) if len(downside) > 1 else 0.0
    var_cut = percentile(returns, 0.05)
    tail = [value for value in returns if value <= var_cut]
    return {
        'days': len(returns), 'ending_equity': equity[-1],
        'total_return_pct': (equity[-1] / equity[0] - 1) * 100,
        'max_drawdown_pct': max_drawdown(equity) * 100,
        'underwater_days': longest_underwater(equity),
        'sharpe': mean / std * math.sqrt(365) if std else 0.0,
        'sortino': mean / downside_std * math.sqrt(365) if downside_std else 0.0,
        'var95_pct': -var_cut * 100,
        'cvar95_pct': -statistics.mean(tail) * 100 if tail else 0.0,
        'worst_day_pct': min(returns, default=0.0) * 100,
    }


def stress_remove_best(values, counts=(1, 5, 10)):
    ordered = sorted((float(value) for value in values), reverse=True)
    return {count: metrics(ordered[count:]) for count in counts if len(ordered) > count}


def symbol_concentration(rows, net_field='net_pct'):
    totals = defaultdict(float)
    for row in rows:
        totals[row['symbol']] += float(row[net_field])
    ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    total_positive = sum(max(0.0, value) for _, value in ordered)
    shares = [(max(0.0, value) / total_positive) for _, value in ordered] if total_positive else []
    return {
        'ordered': ordered,
        'top1_positive_share_pct': (shares[0] * 100 if shares else 0.0),
        'top5_positive_share_pct': sum(shares[:5]) * 100,
        'positive_hhi': sum(share * share for share in shares),
    }


def remove_top_symbols(rows, count):
    concentration = symbol_concentration(rows)
    removed = {symbol for symbol, _ in concentration['ordered'][:count]}
    return metrics([row['net_pct'] for row in rows if row['symbol'] not in removed])


def grouped_metrics(rows, field):
    groups = defaultdict(list)
    for row in rows:
        groups[str(row.get(field) or 'unknown')].append(row['net_pct'])
    return sorted(((name, metrics(values)) for name, values in groups.items()),
                  key=lambda item: (-item[1]['n'], item[0]))


def prepare_rows(records, fee_pct, notional):
    rows = []
    for record in records:
        row = dict(record)
        snapshot = row.pop('macro_snapshot') or {}
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        row['macro_state'] = f"usdtd_{snapshot.get('usdtd_trend', 'unknown')}"
        row['net_pct'] = float(row['gross_return']) - fee_pct
        row['net_usdt'] = row['net_pct'] / 100 * notional
        rows.append(row)
    return rows


async def load_rows():
    return await Database.fetch("""
        SELECT tr.id,tr.exit_time,tr.symbol,tr.profit_percent AS gross_return,
               s.trade_type,s.timeframe,s.market_condition,s.macro_snapshot
        FROM trade_results tr JOIN signals s ON s.id=tr.signal_id
        WHERE tr.exit_time IS NOT NULL AND tr.profit_percent IS NOT NULL
          AND s.trade_type IS NOT NULL AND tr.exit_time >= $1::text::timestamp
        ORDER BY tr.exit_time,tr.id""", config.LEARNING_CLEAN_START)


def render(rows, initial_capital):
    by_day = defaultdict(float)
    for row in rows:
        by_day[row['exit_time'].date()] += row['net_usdt']
    daily = [by_day[day] for day in sorted(by_day)]
    portfolio = portfolio_metrics(daily, initial_capital)
    trade = metrics([row['net_pct'] for row in rows])
    concentration = symbol_concentration(rows)
    lines = ['# Phase 6 — Portfolio analytics', '',
             f"- Initial capacity capital: **${initial_capital:.2f}**",
             f"- Clean trades: **{len(rows)}** over **{portfolio['days']}** exit days",
             f"- Ending equity: **${portfolio['ending_equity']:.2f}** ({portfolio['total_return_pct']:+.2f}%)",
             f"- Max drawdown: **{portfolio['max_drawdown_pct']:.2f}%**; longest underwater: **{portfolio['underwater_days']} exit-days**",
             f"- Daily Sharpe/Sortino (365): **{portfolio['sharpe']:.2f} / {portfolio['sortino']:.2f}**",
             f"- Daily VaR95/CVaR95: **{portfolio['var95_pct']:.2f}% / {portfolio['cvar95_pct']:.2f}%**",
             f"- Worst exit-day: **{portfolio['worst_day_pct']:.2f}%** of capacity capital",
             f"- Trade expectancy/PF: **{trade['expectancy']:+.3f}% / {trade['profit_factor']:.2f}**",
             '', '## Concentration stress', '',
             f"- Top symbol share of positive contribution: **{concentration['top1_positive_share_pct']:.1f}%**",
             f"- Top 5 symbols share: **{concentration['top5_positive_share_pct']:.1f}%**",
             f"- Positive-contribution HHI: **{concentration['positive_hhi']:.3f}**"]
    for count, result in stress_remove_best([row['net_pct'] for row in rows]).items():
        lines.append(f"- Remove best {count} trades: n={result['n']}, E={result['expectancy']:+.3f}%, PF={result['profit_factor']:.2f}")
    for count in (1, 3, 5):
        result = remove_top_symbols(rows, count)
        lines.append(f"- Remove top {count} symbols: n={result['n']}, E={result['expectancy']:+.3f}%, PF={result['profit_factor']:.2f}")
    for field, title in (('trade_type', 'Trade type'), ('timeframe', 'Timeframe'),
                         ('market_condition', 'Market condition'), ('macro_state', 'Macro state')):
        lines += ['', f'## {title}', '', '| Segment | n | E | PF | Win rate |', '|---|---:|---:|---:|---:|']
        for name, result in grouped_metrics(rows, field):
            lines.append(f"| {name} | {result['n']} | {result['expectancy']:+.3f}% | {result['profit_factor']:.2f} | {result['win_rate']:.1f}% |")
    lines += ['', '## Top/bottom symbol contributions', '', '| Symbol | Net contribution (pp) |', '|---|---:|']
    ordered = concentration['ordered']
    for symbol, value in ordered[:10] + ordered[-10:]:
        lines.append(f'| {symbol} | {value:+.3f} |')
    return '\n'.join(lines), portfolio, trade


async def main():
    await Database.connect()
    await require_schema('portfolio_review')
    try:
        rows = prepare_rows(await load_rows(), config.FEE_ROUNDTRIP_PCT, config.TRADE_AMOUNT_USDT)
        capital = config.TRADE_AMOUNT_USDT * max(1, config.MAX_OPEN_TRADES)
        print(render(rows, capital)[0])
    finally:
        await Database.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
