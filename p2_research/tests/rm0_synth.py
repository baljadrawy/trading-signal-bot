"""Synthetic in-memory RiskMarkets for P2-RM0 tests (no real data, no W3, no Paper)."""
from __future__ import annotations

import math
import random

from p2_research import instrument as IN
from p2_research.execution.market_state import ForwardMarketState
from p2_research.risk.market import RiskMarket
from p2_research.tests.synth import ms

BAR = 900_000
T0 = ms("2026-10-05T01:00:00Z")                 # run start / first bar open (after W3)
T = ms("2026-10-06T12:06:30Z")                  # snapshot time (grid point), 35 h of history
BOOT = "cd" * 16
STALE = {"book_t0": 120_000, "book_t12_dead": 600_000, "book_t12_suspect": 120_000, "depth": 2_000,
         "depth_by_tier": {"t0": 2_000, "t1": 180_000, "t2": 15_000}, "market": 10_000}
RUN = {"boot_id": BOOT, "boot8": BOOT[:8], "ws_start_ms": T0, "end_ms": None, "stale_ms": STALE,
       "cadence_ms": {"t0_book": 1000, "t0_depth": 1000, "t1_book": 10000, "t1_depth": 60000}}
CAD = {0: (1000, 1000), 1: (10000, 60000), 2: (2000, 5000)}       # tier -> (book cadence, depth cadence)
TIERS = {"BTCUSDT": 0, "ETHUSDT": 0, "AAAUSDT": 1, "BBBUSDT": 1, "CCCUSDT": 1, "DDDUSDT": 2, "EEEUSDT": 2,
         "FFFUSDT": 2, "GGGUSDT": 2, "HHHUSDT": 2, "IIIUSDT": 2}


def last_open(t):
    return ((t - BAR) // BAR) * BAR


def factor_paths(syms, n_bars, seed=7, betas=None, idio=None, btc_sigma=0.002, spike=None):
    """Closes per symbol for bars 0..n_bars-1: r_i = beta_i * r_btc + idio_i * e_i (deterministic RNG)."""
    rng = random.Random(seed)
    betas, idio = betas or {}, idio or {}
    closes = {s: [100.0 + 10 * i] for i, s in enumerate(syms)}
    for k in range(1, n_bars):
        rb = rng.gauss(0, btc_sigma)
        for s in syms:
            e = rng.gauss(0, 1)
            if s == "BTCUSDT":
                r = rb
            else:
                r = betas.get(s, 0.8) * rb + idio.get(s, 0.002) * e
            if spike and s in spike and k >= n_bars - spike[s][0]:
                r *= spike[s][1]
            closes[s].append(closes[s][-1] * math.exp(r))
    return closes


def candles_from(closes, start_open=T0, avail_lag=60_000, missing=(), cs=()):
    out = {}
    for s, cl in closes.items():
        lst = []
        for k, c in enumerate(cl):
            o = start_open + k * BAR
            if (s, o) in missing:
                continue
            prev = cl[k - 1] if k else c
            lst.append((o, prev, max(prev, c) * 1.0005, min(prev, c) * 0.9995, c, 10.0, o + BAR - 1, 1000.0,
                        o + BAR - 1 + 1 + avail_lag, (s, o) in cs))
        out[(s, "15m")] = lst
    return out


def book_rec(t_obs, sample, bid, ask, tier, cad, bq=10.0, aq=10.0):
    return (t_obs, sample, t_obs, bid, ask, bq, aq, sample, False, False, tier, cad, BOOT[:8])


def depth_rec(t_obs, sample, bid0, ask0, tier, cad, n=10, qty=5.0, step_frac=0.0002):
    bids = tuple((bid0 * (1 - i * step_frac), qty) for i in range(n))
    asks = tuple((ask0 * (1 + i * step_frac), qty) for i in range(n))
    return (t_obs, sample, t_obs, bids, asks, n, sample, False, False, tier, cad, BOOT[:8])


def make_market(t=T, tiers=None, closes=None, n_bars=None, spread_frac=0.0001, depth_qty=None, book_age=None,
                depth_age=None, drop_book=(), drop_depth=(), extra_epochs=(), health_state="HEALTHY",
                missing=(), cs=(), seed=7, betas=None, idio=None, spike=None, candle_extra=None):
    tiers = dict(TIERS if tiers is None else tiers)
    if closes is None:
        n_bars = n_bars or (last_open(t) - T0) // BAR + 1
        closes = factor_paths(sorted(tiers), n_bars, seed=seed, betas=betas, idio=idio, spike=spike)
    candles = candles_from(closes, missing=missing, cs=cs)
    if candle_extra:
        for k, v in candle_extra.items():
            candles[k] = sorted(candles.get(k, []) + list(v), key=lambda c: c[0])
    book, depth = [], []
    depth_qty = depth_qty or {}
    for s, tier in sorted(tiers.items()):
        bc, dc = CAD[tier]
        px = closes[s][-1] if s in closes else 100.0
        bid, ask = px * (1 - spread_frac), px * (1 + spread_frac)
        if s not in drop_book:
            for j in range(3):
                smp = (t // bc) * bc - j * bc
                age = (book_age or {}).get(s)
                obs = smp - 50 if age is None else t - age
                book.append((s, book_rec(min(obs, smp), smp, bid, ask, tier, bc)))
        if s not in drop_depth:
            for j in range(3):
                smp = (t // dc) * dc - j * dc
                age = (depth_age or {}).get(s)
                obs = smp - 50 if age is None else t - age
                depth.append((s, depth_rec(min(obs, smp), smp, bid, ask, tier, dc, qty=depth_qty.get(s, 5.0))))
    epochs = [{"effective_from_ms": T0, "available_at_ms": T0, "universe_id": "u-synth-1", "kind": "ws_start",
               "boot8": BOOT[:8], "tiers": tiers}] + list(extra_epochs)
    health = [(t - 30_000, health_state, frozenset(), ())]
    S = ForwardMarketState.from_records(book=book, depth=depth, runs=[RUN], health=health, epochs=epochs,
                                        meta={"source_kind": "synthetic-rm0", "dataset_id": "synthetic-rm0"})
    return RiskMarket(S, candles)


def position(sym, notional, t=T, side="long", px=None, prov_class="SYNTHETIC_FIXTURE", **over):
    ins = IN.binance_spot_instrument(sym)
    px = px or 100.0
    d = {"asset_class": ins.asset_class, "venue": ins.venue, "product": ins.product, "instrument_id": ins.instrument_id,
         "symbol": sym, "quote_currency": ins.quote_currency, "side": side, "quantity": notional / px,
         "reference_price": px, "notional": float(notional), "decision_time_ms": t, "reference_time_ms": t - 1000,
         "provenance": {"class": prov_class, "source": "unit-test"}}
    d.update(over)
    return d
