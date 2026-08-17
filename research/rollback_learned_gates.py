"""Rollback one applied learning run. Usage: python research/rollback_learned_gates.py RUN_ID"""
import asyncio
import json
from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.config import config
from shared.database import Database
from shared.schema import require_schema


def _timestamp(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


async def rollback(run_id: int) -> int:
    await Database.connect()
    await require_schema('gate_rollback')
    try:
        async with Database.acquire() as conn:
            async with conn.transaction():
                source = await conn.fetchrow(
                    "SELECT * FROM learning_runs WHERE id=$1 AND status='applied' FOR UPDATE", run_id)
                if not source:
                    raise ValueError(f'applied learning run {run_id} not found')
                history = await conn.fetch(
                    "SELECT * FROM learned_gate_history WHERE learning_run_id=$1 ORDER BY id DESC", run_id)
                rollback_id = await conn.fetchval(
                    """INSERT INTO learning_runs(strategy_version,status,parameters)
                       VALUES($1,'validating',$2::jsonb) RETURNING id""",
                    config.APP_VERSION, json.dumps({'rollback_of': run_id}))
                for row in history:
                    old = row['old_value']
                    if isinstance(old, str):
                        old = json.loads(old)
                    new = row['new_value']
                    if isinstance(new, str):
                        new = json.loads(new)
                    if old:
                        await conn.execute(
                            """INSERT INTO learned_gates
                                   (trade_type,macro_state,timeframe,n,wr,expectancy,weight,
                                    ci_low,ci_high,sample_start,sample_end,
                                    strategy_version,learning_run_id,updated_at)
                               VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,NOW())
                               ON CONFLICT(trade_type,macro_state,timeframe) DO UPDATE
                               SET n=$4,wr=$5,expectancy=$6,weight=$7,ci_low=$8,ci_high=$9,
                                   sample_start=$10,sample_end=$11,strategy_version=$12,
                                   learning_run_id=$13,updated_at=NOW()""",
                            row['trade_type'], row['macro_state'], row['timeframe'], old['n'],
                            old['wr'], old['expectancy'], old['weight'],
                            old.get('ci_low'), old.get('ci_high'), _timestamp(old.get('sample_start')),
                            _timestamp(old.get('sample_end')), old.get('strategy_version', 'legacy'), rollback_id)
                    else:
                        await conn.execute(
                            "DELETE FROM learned_gates WHERE trade_type=$1 AND macro_state=$2 AND timeframe=$3",
                            row['trade_type'], row['macro_state'], row['timeframe'])
                    await conn.execute(
                        """INSERT INTO learned_gate_history
                               (learning_run_id,action,trade_type,macro_state,timeframe,
                                old_value,new_value,strategy_version)
                           VALUES($1,'rollback',$2,$3,$4,$5::jsonb,$6::jsonb,$7)""",
                        rollback_id, row['trade_type'], row['macro_state'], row['timeframe'],
                        json.dumps(new, default=str) if new else None,
                        json.dumps(old, default=str) if old else None, config.APP_VERSION)
                await conn.execute(
                    "UPDATE learning_runs SET status='rolled_back',completed_at=NOW() WHERE id=$1", run_id)
                await conn.execute(
                    "UPDATE learning_runs SET status='applied',completed_at=NOW() WHERE id=$1", rollback_id)
                return rollback_id
    finally:
        await Database.disconnect()


if __name__ == '__main__':
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit('usage: python research/rollback_learned_gates.py RUN_ID')
    print(asyncio.run(rollback(int(sys.argv[1]))))
