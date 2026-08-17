"""Purged, embargoed walk-forward review for phase 5."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.strategy_performance_review import learned_blocked_keys, metrics
from shared.config import config
from shared.database import Database
from shared.schema import require_schema


VOLATILE_PREREGISTERED_AT = datetime(2026, 8, 17, 18, 45, tzinfo=timezone.utc)


def _time(row, field):
    value = row.get(field) or row.get('exit_time')
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _net(row, fee_pct):
    return float(row['gross_return']) - fee_pct


def select_regime(train, fee_pct, minimum_n=30):
    """Select a regime from training only, and only with CI entirely above zero."""
    groups = defaultdict(list)
    for row in train:
        groups[str(row.get('market_condition') or 'unknown')].append(_net(row, fee_pct))
    eligible = []
    for name, values in groups.items():
        result = metrics(values)
        if result['n'] >= minimum_n and result['ci_low'] is not None and result['ci_low'] > 0:
            eligible.append((result['expectancy'], name))
    return max(eligible)[1] if eligible else None


def purged_walk_forward(rows, fee_pct, folds=5, embargo_hours=48, min_cell_n=10):
    ordered = sorted(rows, key=lambda row: (_time(row, 'signal_time'), row.get('id', 0)))
    initial = max(min_cell_n * 2, int(len(ordered) * 0.4))
    remaining = len(ordered) - initial
    if remaining < folds:
        return []
    step = max(1, remaining // folds)
    output = []
    for fold in range(folds):
        start_i = initial + fold * step
        end_i = len(ordered) if fold == folds - 1 else min(len(ordered), start_i + step)
        test = ordered[start_i:end_i]
        test_start = _time(test[0], 'signal_time')
        cutoff = test_start - timedelta(hours=embargo_hours)
        prior = [row for row in ordered[:start_i] if _time(row, 'signal_time') < test_start]
        train = [row for row in prior if _time(row, 'exit_time') < cutoff]
        blocked = learned_blocked_keys(train, fee_pct, min_cell_n)
        learned = [row for row in test if (
            row.get('trade_type'), row.get('macro_state'), row.get('timeframe')) not in blocked]
        selected_regime = select_regime(train, fee_pct)
        regime = [row for row in test if row.get('market_condition') == selected_regime]
        output.append({
            'fold': fold + 1, 'train_n': len(train), 'purged_n': len(prior) - len(train),
            'test_n': len(test), 'blocked_cells': len(blocked),
            'selected_regime': selected_regime,
            'baseline_rows': test, 'learned_rows': learned, 'regime_rows': regime,
            'baseline': metrics([_net(row, fee_pct) for row in test]),
            'learned': metrics([_net(row, fee_pct) for row in learned]),
            'regime': metrics([_net(row, fee_pct) for row in regime]),
        })
    return output


def aggregate_folds(folds, key, fee_pct):
    rows = [row for fold in folds for row in fold[f'{key}_rows']]
    return metrics([_net(row, fee_pct) for row in rows])


def _fmt(result):
    if not result['n']:
        return 'n=0'
    return (f"n={result['n']}, E={result['expectancy']:+.3f}% "
            f"CI=[{result['ci_low']:+.3f},{result['ci_high']:+.3f}], "
            f"PF={result['profit_factor']:.2f}")


async def load_rows():
    records = await Database.fetch("""
        SELECT tr.id,s.signal_time,tr.exit_time,tr.symbol,
               tr.profit_percent AS gross_return,s.trade_type,s.timeframe,
               s.market_condition,s.macro_snapshot
        FROM trade_results tr JOIN signals s ON s.id=tr.signal_id
        WHERE tr.exit_time IS NOT NULL AND tr.profit_percent IS NOT NULL
          AND s.trade_type IS NOT NULL AND tr.exit_time >= $1::text::timestamp
        ORDER BY s.signal_time,tr.id""", config.LEARNING_CLEAN_START)
    rows = []
    for record in records:
        row = dict(record)
        snapshot = row.pop('macro_snapshot') or {}
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        row['macro_state'] = f"usdtd_{snapshot.get('usdtd_trend', 'unknown')}"
        rows.append(row)
    return rows


async def main():
    await Database.connect()
    await require_schema('walk_forward_review')
    try:
        rows = await load_rows()
        folds = purged_walk_forward(rows, config.FEE_ROUNDTRIP_PCT)
        print('# Phase 5 — Purged walk-forward review\n')
        print('| Fold | Train | Purged | Test | Cells blocked | Train-selected regime | Baseline | Learned | Regime |')
        print('|---:|---:|---:|---:|---:|---|---|---|---|')
        for fold in folds:
            print(f"| {fold['fold']} | {fold['train_n']} | {fold['purged_n']} | {fold['test_n']} | "
                  f"{fold['blocked_cells']} | {fold['selected_regime'] or 'none'} | "
                  f"{_fmt(fold['baseline'])} | {_fmt(fold['learned'])} | {_fmt(fold['regime'])} |")
        print('\n## Aggregate OOS')
        for key in ('baseline', 'learned', 'regime'):
            print(f"- {key}: **{_fmt(aggregate_folds(folds, key, config.FEE_ROUNDTRIP_PCT))}**")
        prereg = [row for row in rows if _time(row, 'signal_time') >= VOLATILE_PREREGISTERED_AT]
        volatile = [row for row in prereg if row.get('market_condition') == 'volatile']
        print('\n## Pre-registered volatile gate')
        print(f"- Closed post-registration trades: **{len(prereg)}**")
        print(f"- Volatile trades: **{_fmt(metrics([_net(row, config.FEE_ROUNDTRIP_PCT) for row in volatile]))}**")
    finally:
        await Database.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
