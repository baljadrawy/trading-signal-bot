"""Leakage-safe phase-9 performance review for closed live/paper trades."""
import asyncio
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.config import config
from shared.database import Database
from shared.schema import require_schema


def metrics(returns):
    values = [float(value) for value in returns if value is not None and math.isfinite(float(value))]
    if not values:
        return {'n': 0, 'win_rate': None, 'expectancy': None, 'ci_low': None, 'ci_high': None, 'profit_factor': None,
                'max_drawdown': None, 'total_return': 0.0}
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    mean = sum(values) / len(values)
    margin = 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) >= 2 else math.inf
    return {
        'n': len(values),
        'win_rate': sum(value > 0 for value in values) / len(values) * 100,
        'expectancy': mean,
        'ci_low': mean - margin,
        'ci_high': mean + margin,
        'profit_factor': gross_profit / gross_loss if gross_loss else (math.inf if gross_profit else None),
        'max_drawdown': drawdown,
        'total_return': sum(values),
    }


def segment(rows, field, fee_pct, minimum_n=1):
    groups = defaultdict(list)
    for row in rows:
        groups[str(row.get(field) or 'unknown')].append(float(row['gross_return']) - fee_pct)
    return sorted(((key, metrics(values)) for key, values in groups.items() if len(values) >= minimum_n),
                  key=lambda item: (-item[1]['n'], item[0]))


def _cell_key(row):
    return row.get('trade_type'), row.get('macro_state'), row.get('timeframe')


def learned_blocked_keys(train, fee_pct, min_cell_n, threshold=0.0, confidence_z=1.96):
    groups = defaultdict(list)
    for row in train:
        groups[_cell_key(row)].append(float(row['gross_return']) - fee_pct)
    blocked = set()
    for key, values in groups.items():
        if None in key or len(values) < min_cell_n:
            continue
        mean = sum(values) / len(values)
        margin = confidence_z * statistics.stdev(values) / math.sqrt(len(values)) if len(values) >= 2 else math.inf
        if mean + margin <= threshold:
            blocked.add(key)
    return blocked


def walk_forward(rows, fee_pct, min_cell_n=10, folds=5):
    ordered = sorted(rows, key=lambda row: (row['exit_time'], row.get('id', 0)))
    n = len(ordered)
    initial = max(min_cell_n * 2, int(n * 0.4))
    if n - initial < folds:
        return []
    step = max(1, (n - initial) // folds)
    output = []
    for fold in range(folds):
        test_start = initial + fold * step
        test_end = n if fold == folds - 1 else min(n, test_start + step)
        train, test = ordered[:test_start], ordered[test_start:test_end]
        blocked = learned_blocked_keys(train, fee_pct, min_cell_n)
        accepted = [row for row in test if _cell_key(row) not in blocked]
        output.append({'fold': fold + 1, 'train_n': len(train), 'test_n': len(test),
                       'blocked_cells': len(blocked), 'coverage_pct': len(accepted) / len(test) * 100,
                       'baseline': metrics([float(r['gross_return']) - fee_pct for r in test]),
                       'learned': metrics([float(r['gross_return']) - fee_pct for r in accepted])})
    return output


def _fmt(value, digits=2):
    if value is None:
        return '—'
    if value == math.inf:
        return '∞'
    return f'{value:.{digits}f}'


def entry_hypothesis_verdict(trade_type, result):
    """Conservative promotion gate; uncertainty or weak economics means NO-GO."""
    minimum_win_rate = 55.0 if trade_type == 'reversion' else 35.0
    passed = (
        result['n'] >= 100
        and result['ci_low'] is not None and result['ci_low'] > 0
        and result['profit_factor'] is not None and result['profit_factor'] >= 1.5
        and result['win_rate'] is not None and result['win_rate'] >= minimum_win_rate
    )
    return 'GO' if passed else 'NO-GO'


def render_report(rows, fee_pct, strategy_version):
    net = [float(row['gross_return']) - fee_pct for row in rows]
    gross = metrics([row['gross_return'] for row in rows])
    overall = metrics(net)
    lines = [
        '# Phase 9 — Strategy performance review', '',
        f'- Strategy version: `{strategy_version}`',
        f'- Closed trades: **{len(rows)}**',
        f'- Cost model: **{fee_pct:.2f}% per round trip** (fees + modeled slippage)',
        '- Return unit: percentage points per equal-sized trade; drawdown is cumulative percentage points.',
        '', '## Overall', '',
        '| Basis | n | Win rate | Expectancy | Profit factor | Max drawdown | Total |',
        '|---|---:|---:|---:|---:|---:|---:|',
        f"| Gross | {gross['n']} | {_fmt(gross['win_rate'])}% | {_fmt(gross['expectancy'],3)}% | {_fmt(gross['profit_factor'])} | {_fmt(gross['max_drawdown'])}% | {_fmt(gross['total_return'])}% |",
        f"| Net | {overall['n']} | {_fmt(overall['win_rate'])}% | {_fmt(overall['expectancy'],3)}% | {_fmt(overall['profit_factor'])} | {_fmt(overall['max_drawdown'])}% | {_fmt(overall['total_return'])}% |",
    ]
    for field, title, minimum in [('trade_type', 'Trade type', 1), ('timeframe', 'Timeframe', 1),
                                   ('market_condition', 'Market condition', 1),
                                   ('macro_state', 'Macro state', 1), ('symbol', 'Pair (n≥5)', 5)]:
        lines += ['', f'## {title}', '',
                  '| Segment | n | Win rate | Net expectancy | PF | Max drawdown |',
                  '|---|---:|---:|---:|---:|---:|']
        items = segment(rows, field, fee_pct, minimum)
        if field == 'symbol':
            items = items[:25]
        for key, result in items:
            lines.append(f"| {key} | {result['n']} | {_fmt(result['win_rate'])}% | {_fmt(result['expectancy'],3)}% | {_fmt(result['profit_factor'])} | {_fmt(result['max_drawdown'])}% |")

    lines += ['', '## Entry hypothesis gate', '',
              'Promotion requires n≥100, net expectancy 95% CI entirely above zero, PF≥1.5, '
              'and win rate ≥55% for reversion or ≥35% for momentum.', '',
              '| Hypothesis | n | Net E (95% CI) | PF | Win rate | Verdict |',
              '|---|---:|---:|---:|---:|---|']
    for key, result in segment(rows, 'trade_type', fee_pct):
        lines.append(
            f"| {key} | {result['n']} | {_fmt(result['expectancy'],3)}% "
            f"[{_fmt(result['ci_low'],3)}, {_fmt(result['ci_high'],3)}] | "
            f"{_fmt(result['profit_factor'])} | {_fmt(result['win_rate'])}% | "
            f"**{entry_hypothesis_verdict(key, result)}** |")

    folds = walk_forward(rows, fee_pct)
    lines += ['', '## Expanding walk-forward: learned gates vs fixed baseline', '',
              'Each fold learns blocked `(trade_type × macro_state × timeframe)` cells from prior trades only. '
              'The fixed baseline accepts every test trade.', '',
              '| Fold | Train | Test | Blocked cells | Coverage | Baseline E/PF | Learned E/PF |',
              '|---:|---:|---:|---:|---:|---:|---:|']
    for fold in folds:
        baseline, learned = fold['baseline'], fold['learned']
        lines.append(
            f"| {fold['fold']} | {fold['train_n']} | {fold['test_n']} | {fold['blocked_cells']} | "
            f"{fold['coverage_pct']:.1f}% | {_fmt(baseline['expectancy'],3)}% / {_fmt(baseline['profit_factor'])} | "
            f"{_fmt(learned['expectancy'],3)}% / {_fmt(learned['profit_factor'])} |")
    if folds:
        # The table is authoritative; summary compares fold-level means to avoid re-fitting.
        base_mean = sum(f['baseline']['expectancy'] for f in folds) / len(folds)
        learned_valid = [f['learned']['expectancy'] for f in folds if f['learned']['expectancy'] is not None]
        learned_mean = sum(learned_valid) / len(learned_valid) if learned_valid else None
        profitable = sum((f['learned']['expectancy'] or 0) > 0 for f in folds)
        lines += ['', f'- Mean fold baseline expectancy: **{base_mean:+.3f}%**.',
                  f'- Mean fold learned expectancy: **{_fmt(learned_mean,3)}%**.',
                  f'- Profitable learned test folds: **{profitable}/{len(folds)}**.']
    lines += ['', '## Interpretation limits', '',
              '- This is an observational review of trades selected by the running bot, not the raw market universe.',
              '- The walk-forward prevents future-result leakage, but cannot reconstruct opportunities the historical policy never selected.',
              '- No gate or trading parameter is changed by this report.', '']
    return '\n'.join(lines)
async def main():
    await Database.connect()
    await require_schema('strategy_performance_review')
    try:
        records = await Database.fetch("""
            SELECT tr.id,tr.exit_time,tr.symbol,tr.profit_percent AS gross_return,
                   s.trade_type,s.timeframe,s.market_condition,s.macro_snapshot
            FROM trade_results tr JOIN signals s ON s.id=tr.signal_id
            WHERE tr.exit_time IS NOT NULL AND tr.profit_percent IS NOT NULL
              AND s.trade_type IS NOT NULL AND tr.exit_time >= $1::text::timestamp
            ORDER BY tr.exit_time,tr.id""", config.LEARNING_CLEAN_START)
        rows = []
        for record in records:
            row = dict(record)
            snapshot = row.pop('macro_snapshot') or {}
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)
            row['macro_state'] = f"usdtd_{snapshot.get('usdtd_trend', 'unknown')}"
            rows.append(row)
        print(render_report(rows, config.FEE_ROUNDTRIP_PCT, config.APP_VERSION))
    finally:
        await Database.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
