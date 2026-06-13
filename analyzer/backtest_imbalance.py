"""
اختبار Imbalance Candle بسيط:
تعريف: جسم الشمعة (|close-open|) >= 2 × MA_20 للأجسام السابقة + اتجاه صاعد (close > open)
هدف: هل نسبة الرابحين الذين بدأوا من شمعة Imbalance أعلى من الخاسرين؟
مصدر البيانات: /app/research/cache/ict_ohlc/{SYMBOL}_1h_ohlc.pkl
"""
import pickle
import pandas as pd
import warnings
import os
import csv

warnings.filterwarnings('ignore')

OHLC_DIR = "/app/research/cache/ict_ohlc"
TRADES_CSV = "/app/trades50.csv"
TRADE_AMOUNT = 50.0

# Load trades
trades = []
with open(TRADES_CSV) as f:
    reader = csv.DictReader(f)
    for row in reader:
        trades.append(row)

print(f"Total trades: {len(trades)}")

def load_ohlcv(symbol):
    path = os.path.join(OHLC_DIR, f"{symbol}_1h_ohlc.pkl")
    if not os.path.exists(path):
        return None
    with open(path, 'rb') as f:
        data = pickle.load(f)
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        df = pd.DataFrame(data)
        df.rename(columns={'t': 'time', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close'}, inplace=True)
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col])
        return df.sort_values('time').reset_index(drop=True)
    elif isinstance(data, pd.DataFrame):
        return data.sort_values('time').reset_index(drop=True)
    return None

def has_imbalance_at_entry(symbol, entry_price):
    """
    التحقق إذا كانت أقرب شمعة 1h قبل إشارة الدخول تعتبر Imbalance
    """
    df = load_ohlcv(symbol)
    if df is None or len(df) < 25:
        return None

    df['body'] = abs(df['close'] - df['open'])
    df['body_ma20'] = df['body'].rolling(20, min_periods=5).mean().shift(1)

    entry_f = float(entry_price)

    # ابحث عن آخر شمعة تحتوي entry_price ضمن نطاق high/low
    mask = (df['low'] <= entry_f * 1.01) & (df['high'] >= entry_f * 0.99)
    matched = df[mask]

    if len(matched) == 0:
        # fallback: آخر شمعة مكتملة
        candle = df.iloc[-2] if len(df) >= 2 else None
        if candle is None:
            return None
    else:
        candle = matched.iloc[-1]

    idx = candle.name
    if idx < 5:
        return None

    body_ma = candle['body_ma20']
    body = candle['body']
    is_bullish = candle['close'] > candle['open']

    if pd.isna(body_ma) or body_ma == 0:
        return None

    is_imbalance = (body >= 2 * body_ma) and is_bullish
    return is_imbalance

# Run analysis
imbalance_wins = 0
imbalance_losses = 0
no_imbalance_wins = 0
no_imbalance_losses = 0
no_data = 0

for trade in trades:
    symbol = trade['symbol']
    entry = trade['entry_price']
    result = trade['result']

    imb = has_imbalance_at_entry(symbol, entry)

    if imb is None:
        no_data += 1
        continue

    if result == 'WIN':
        if imb:
            imbalance_wins += 1
        else:
            no_imbalance_wins += 1
    else:
        if imb:
            imbalance_losses += 1
        else:
            no_imbalance_losses += 1

total_wins = imbalance_wins + no_imbalance_wins
total_losses = imbalance_losses + no_imbalance_losses
total_imbalance = imbalance_wins + imbalance_losses
total_no_imbalance = no_imbalance_wins + no_imbalance_losses

print(f"\n=== IMBALANCE CANDLE ANALYSIS (n={total_wins+total_losses}) ===")
print(f"No data (symbol not in cache): {no_data}")
print(f"Total wins: {total_wins}, Total losses: {total_losses}")

print(f"\nImbalance trades: {total_imbalance}")
print(f"  Wins: {imbalance_wins}, Losses: {imbalance_losses}")
if total_imbalance > 0:
    print(f"  WR: {imbalance_wins/total_imbalance:.3f}")

print(f"\nNo-Imbalance trades: {total_no_imbalance}")
print(f"  Wins: {no_imbalance_wins}, Losses: {no_imbalance_losses}")
if total_no_imbalance > 0:
    print(f"  WR: {no_imbalance_wins/total_no_imbalance:.3f}")

if total_wins > 0 and total_losses > 0:
    pct_imb_wins = imbalance_wins / total_wins if total_wins > 0 else 0
    pct_imb_losses = imbalance_losses / total_losses if total_losses > 0 else 0
    print(f"\nKey ratio:")
    print(f"  Imbalance in WINS: {pct_imb_wins:.3f} ({imbalance_wins}/{total_wins})")
    print(f"  Imbalance in LOSSES: {pct_imb_losses:.3f} ({imbalance_losses}/{total_losses})")
    diff = pct_imb_wins - pct_imb_losses
    print(f"  Difference: {diff:+.3f}")
    print(f"  Edge signal: {'POSSIBLE (>20%)' if diff >= 0.20 else 'NO (<20%)'}")
