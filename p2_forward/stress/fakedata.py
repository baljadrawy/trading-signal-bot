"""Deterministic synthetic Binance-Spot-like universe for the offline stress harness (no network)."""
import random

N_SYMBOLS = 520                       # > universe_min_usdt_trading (350), like live (~500 USDT pairs)


def symbols():
    return ["BTCUSDT", "ETHUSDT"] + [f"S{i:03d}USDT" for i in range(N_SYMBOLS - 2)]


def exchange_info():
    return {"timezone": "UTC", "symbols": [{"symbol": s, "status": "TRADING", "baseAsset": s[:-4], "quoteAsset": "USDT"}
                                           for s in symbols()]}


def tickers(seed=7):
    rnd = random.Random(seed)
    out = []
    for i, s in enumerate(symbols()):
        if i < 2:
            qv = 2e9 - i * 5e8
        elif i < 63:                                   # 61 above 10 M => Tier 2 = 30, Tier 1 = 31 (as in G3-v6)
            qv = 1.8e9 / (i - 1)
        else:                                          # long tail below the threshold
            qv = 9.5e6 * (0.985 ** (i - 63))
        o = round(rnd.uniform(0.01, 500), 6)
        ch = rnd.uniform(-0.12, 0.12)
        out.append({"symbol": s, "openPrice": f"{o:.8f}", "lastPrice": f"{o * (1 + ch):.8f}",
                    "highPrice": f"{o * 1.15:.8f}", "lowPrice": f"{o * 0.85:.8f}", "volume": f"{qv / o:.8f}",
                    "quoteVolume": f"{qv:.8f}", "openTime": 0, "closeTime": 0, "firstId": 1, "lastId": 2, "count": 3})
    return out


def price(sym):
    return 60000.0 if sym == "BTCUSDT" else 3000.0 if sym == "ETHUSDT" else 1.0 + (hash(sym) % 1000) / 10.0
