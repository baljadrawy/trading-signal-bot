#!/usr/bin/env python3
"""Part 35: SMC Advanced V3 — Imbalance/CHoCH/Discount Discovery (Cycle 37)"""
import asyncio
import asyncpg
import urllib.request, json, time, sys, numpy as np
from datetime import datetime, timezone
from scipy import stats
sys.path.insert(0, '/app')
from shared.logger import setup_logger

logger = setup_logger('part35')
DB_CONFIG = {'host': '172.21.0.2', 'user': 'trading_signal_bot', 'password': '6psgaD1GV2ClGtopvSe5Lm8za', 'database': 'trading_signals'}
FEES_PERCENT = 0.3
KLINES_LOOKBACK = 100

async def fetch_trades():
    conn = await asyncpg.connect(**DB_CONFIG)
    rows = await conn.fetch("""SELECT id, symbol, entry_price, exit_price, exit_time, profit_percent, stop_hit, target_reached, profit_usdt
        FROM trade_results WHERE exit_time >= '2026-05-17'::date ORDER BY exit_time ASC""")
    await conn.close()
    return rows

def fetch_klines_1d(symbol, limit=KLINES_LOOKBACK):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt < 2: time.sleep(2 ** attempt)
    return []

def compute_swing_points(highs, lows, lookback=5):
    points = []
    for i in range(lookback, len(highs) - lookback):
        is_high = highs[i] == max(highs[i-lookback:i+lookback+1])
        is_low = lows[i] == min(lows[i-lookback:i+lookback+1])
        if is_high:
            points.append((i, highs[i], 'high'))
        elif is_low:
            points.append((i, lows[i], 'low'))
    return points

def compute_smc_features(symbol, entry_price, klines):
    if len(klines) < 30: return None
    try:
        opens, highs, lows, closes = np.array([float(k[1]) for k in klines]), np.array([float(k[2]) for k in klines]), np.array([float(k[3]) for k in klines]), np.array([float(k[4]) for k in klines])
        bodies = np.abs(closes - opens)
        features = {}
        
        avg_body_20 = np.mean(bodies[-25:-5]) if len(bodies) >= 25 else None
        has_imbalance_5 = 0.0
        if avg_body_20 and avg_body_20 > 0:
            for i in range(-5, 0):
                if bodies[i] >= 2.0 * avg_body_20 and closes[i] > opens[i]:
                    has_imbalance_5 = 1.0
                    break
        features['imbalance_present'] = has_imbalance_5
        
        recent_high = np.max(highs[-20:])
        recent_low = np.min(lows[-20:])
        swing_range = recent_high - recent_low
        mid_point = recent_low + swing_range * 0.5
        in_discount = 1.0 if entry_price < mid_point else 0.0
        features['in_discount_zone'] = in_discount
        
        swing_points = compute_swing_points(highs, lows, lookback=5)
        bos_up = 0.0
        if len(swing_points) >= 2:
            last_high = next(((idx, p, t) for idx, p, t in reversed(swing_points) if t == 'high'), (None, None, None))
            if last_high[0] is not None:
                bos_up = 1.0 if closes[-1] > last_high[1] else 0.0
        features['choch_bos_up'] = bos_up
        
        avg_body_15 = np.mean(bodies[-20:-5]) if len(bodies) >= 20 else None
        ob_fresh = 0.0
        if avg_body_15 and avg_body_15 > 0:
            for i in range(-1, -min(15, len(bodies)), -1):
                if bodies[i] >= 1.5 * avg_body_15 and closes[i] < opens[i]:
                    ob_fresh = 1.0 if abs(i) <= 10 else 0.0
                    break
        features['ob_fresh'] = ob_fresh
        
        bullish_recent = np.sum([1 for i in range(-3, 0) if closes[i] > opens[i]]) / 3.0
        features['momentum_bullish_ratio'] = bullish_recent
        
        return features
    except Exception as e:
        logger.error(f"Feature error {symbol}: {e}")
        return None

async def run():
    logger.info(f"Part 35: SMC Advanced V3 | {datetime.now(timezone.utc).isoformat()}")
    trades = await fetch_trades()
    logger.info(f"Loaded {len(trades)} trades")
    
    trades_with_features = []
    symbols_seen = set()
    for trade in trades:
        symbol = trade['symbol']
        entry_price = float(trade['entry_price'])
        result = 1.0 if trade['profit_percent'] > 0 else 0.0
        if symbol not in symbols_seen:
            klines = fetch_klines_1d(symbol)
            symbols_seen.add(symbol)
            time.sleep(0.1)
        if klines:
            features = compute_smc_features(symbol, entry_price, klines)
            if features:
                rec = {'trade_id': trade['id'], 'symbol': symbol, 'entry_price': entry_price, 'result': result, 'profit_pct_net': float(trade['profit_percent']) - FEES_PERCENT, **features}
                trades_with_features.append(rec)
    
    logger.info(f"Features computed for {len(trades_with_features)} trades")
    
    n = len(trades_with_features)
    window_size = n // 5
    feature_names = [k for k in trades_with_features[0].keys() if k not in ['trade_id', 'symbol', 'entry_price', 'result', 'profit_pct_net']]
    
    logger.info(f"Testing {len(feature_names)} features: {feature_names}")
    
    results_by_feature = {name: {'ic': [], 'e_adj': [], 'n': []} for name in feature_names}
    
    for wf_idx in range(5):
        train_end = (wf_idx + 1) * window_size
        test_end = min((wf_idx + 2) * window_size, n)
        if test_end <= train_end: test_end = n
        
        test_data = trades_with_features[train_end:test_end]
        logger.info(f"WF {wf_idx+1}: test_size={len(test_data)}")
        
        for fname in feature_names:
            try:
                fvals = np.array([t.get(fname, 0.0) for t in test_data])
                results = np.array([t['result'] for t in test_data])
                if np.std(fvals) == 0 or len(results) < 3:
                    results_by_feature[fname]['ic'].append(0.0)
                    results_by_feature[fname]['e_adj'].append(0.0)
                    continue
                ic, _ = stats.spearmanr(fvals, results)
                if np.isnan(ic): ic = 0.0
                e_adj = np.mean([t['profit_pct_net'] for t in test_data])
                results_by_feature[fname]['ic'].append(ic)
                results_by_feature[fname]['e_adj'].append(e_adj)
            except:
                results_by_feature[fname]['ic'].append(0.0)
                results_by_feature[fname]['e_adj'].append(0.0)
    
    logger.info(f"\n{'Feature':<30} {'IC Mean':<12} {'E_Adj':<12} {'IC Stable':<10}")
    logger.info("─" * 70)
    
    best_features = []
    for fname in feature_names:
        ic_mean = np.mean(results_by_feature[fname]['ic'])
        ic_std = np.std(results_by_feature[fname]['ic'])
        e_adj = np.mean(results_by_feature[fname]['e_adj'])
        ic_stable = ic_std / abs(ic_mean) if ic_mean != 0 else 999
        is_strong = abs(ic_mean) > 0.05 and ic_stable < 1.0 and e_adj > -1.0
        marker = "★" if is_strong else " "
        logger.info(f"{fname:<30} {ic_mean:>11.4f} {e_adj:>11.4f} {ic_stable:>9.2f} {marker}")
        if is_strong:
            best_features.append((fname, ic_mean, e_adj))
    
    logger.info(f"\nEdges found: {len(best_features)}")
    for fname, ic, e in sorted(best_features, key=lambda x: abs(x[1]), reverse=True):
        logger.info(f"  ★ {fname}: IC={ic:.4f}, E_adj={e:.4f}%")
    
    logger.info(f"\nFinal: {len(best_features)} feature(s) show edge after fees")

if __name__ == '__main__':
    asyncio.run(run())
