"""Canonical market / instrument identity (P2-C delta C: multi-asset READINESS only).

Owner scope (2026-10-04): Crypto is the ONLY market authorized for implementation, research execution and Paper.
This module names the identity fields a future market adapter would have to fill so the research core does not
grow new Binance/crypto coupling. It deliberately contains exactly ONE concrete market (Binance spot, 24/7 UTC
calendar). It is NOT an equity/futures/forex adapter, has no session or corporate-action logic, and any other
market is refused (``UnsupportedMarket``).

Canonical identity:
  market     = (asset_class, venue, product, calendar_id)
  instrument = market + instrument_id + symbol + base/quote/settlement currency
  instrument_id = "<asset_class>:<venue>:<product>:<symbol>"   e.g. "crypto:binance:spot:BTCUSDT"
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .reader import DAY_MS, PRODUCTION_CALENDAR


class UnsupportedMarket(ValueError):
    pass


@dataclass(frozen=True)
class Calendar:
    calendar_id: str
    timezone: str
    sessions: str             # "continuous" = no sessions, no holidays, no closes
    day_boundary: str         # the research "day" (seal/day-close unit) boundary
    day_ms: int
    dataset_calendar: dict    # the collector dataset.json calendar this calendar corresponds to


@dataclass(frozen=True)
class Market:
    asset_class: str
    venue: str
    product: str
    calendar_id: str

    @property
    def market_id(self) -> str:
        return f"{self.asset_class}:{self.venue}:{self.product}"


@dataclass(frozen=True)
class Instrument:
    asset_class: str
    venue: str
    product: str
    instrument_id: str
    symbol: str
    base_currency: str
    quote_currency: str
    settlement_currency: str
    calendar_id: str

    def as_dict(self) -> dict:
        return asdict(self)


CRYPTO_24X7_UTC = Calendar(calendar_id="crypto-24x7-utc", timezone="UTC", sessions="continuous",
                           day_boundary="00:00:00Z", day_ms=DAY_MS, dataset_calendar=dict(PRODUCTION_CALENDAR))
BINANCE_SPOT = Market(asset_class="crypto", venue="binance", product="spot", calendar_id=CRYPTO_24X7_UTC.calendar_id)

# The only authorized market. Adding an entry here is a governance change (docs/p2/ROADMAP_AND_RESEARCH_GOVERNANCE.md),
# not a code change: P4 multi-asset expansion is gated behind the Crypto Success Gate.
SUPPORTED_MARKETS = {BINANCE_SPOT.market_id: BINANCE_SPOT}
CALENDARS = {CRYPTO_24X7_UTC.calendar_id: CRYPTO_24X7_UTC}

# Quote assets recognised when splitting a Binance spot symbol (longest match first). A symbol that does not end in
# one of them is refused rather than guessed.
BINANCE_QUOTES = ("FDUSD", "USDT", "USDC", "TUSD", "BUSD", "BTC", "ETH", "BNB", "EUR", "TRY")
_SYMBOL = re.compile(r"^[A-Z0-9]{2,30}$")


def require_supported_market(m) -> Market:
    """Return the Market for ``m`` (Market or market dict) or raise ``UnsupportedMarket``."""
    if isinstance(m, dict):
        try:
            m = Market(asset_class=m["asset_class"], venue=m["venue"], product=m["product"],
                       calendar_id=m.get("calendar_id", CRYPTO_24X7_UTC.calendar_id))
        except (KeyError, TypeError):
            raise UnsupportedMarket(f"incomplete market identity: {m!r}") from None
    if not isinstance(m, Market) or SUPPORTED_MARKETS.get(m.market_id) != m:
        raise UnsupportedMarket(f"market not authorized (crypto Binance spot only): {m!r}")
    return m


def binance_spot_instrument(symbol: str) -> Instrument:
    """Canonical identity of a Binance spot symbol (e.g. BTCUSDT -> base BTC, quote/settlement USDT)."""
    if not isinstance(symbol, str) or not _SYMBOL.match(symbol):
        raise ValueError(f"invalid Binance spot symbol: {symbol!r}")
    for q in BINANCE_QUOTES:
        if symbol.endswith(q) and len(symbol) > len(q):
            m = BINANCE_SPOT
            return Instrument(asset_class=m.asset_class, venue=m.venue, product=m.product,
                              instrument_id=f"{m.market_id}:{symbol}", symbol=symbol, base_currency=symbol[:-len(q)],
                              quote_currency=q, settlement_currency=q, calendar_id=m.calendar_id)
    raise ValueError(f"unknown quote asset for Binance spot symbol: {symbol!r}")


def calendar_for(market) -> Calendar:
    return CALENDARS[require_supported_market(market).calendar_id]
