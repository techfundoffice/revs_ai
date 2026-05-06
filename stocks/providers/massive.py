"""Massive.com REST adapter exposing the Yahoo-Finance-shaped surface revs_ai
relies on (intraday OHLC, current quote with bid/ask, batch quotes,
daily price history, basic ticker reference data).

Each method returns the same dict shape the previous ``YahooFinanceService``
did, so call sites in ``stocks/tasks.py`` and the management commands work
unchanged.

Configuration
-------------
``settings.MASSIVE_API_KEY`` (or ``MASSIVE_API_KEY`` env var as fallback)
holds the user's Massive API key.  Optional:

- ``settings.MASSIVE_API_BASE_URL`` (default ``https://api.massive.com``)
- ``settings.MASSIVE_HTTP_TIMEOUT`` (default 15 seconds)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Interval translation: yfinance-style strings -> Massive multiplier+timespan
# ----------------------------------------------------------------------
_INTERVAL_MAP: dict[str, tuple[int, str]] = {
    "1m": (1, "minute"),
    "2m": (2, "minute"),
    "5m": (5, "minute"),
    "15m": (15, "minute"),
    "30m": (30, "minute"),
    "60m": (1, "hour"),
    "90m": (90, "minute"),
    "1h": (1, "hour"),
    "1d": (1, "day"),
    "5d": (5, "day"),
    "1wk": (1, "week"),
    "1mo": (1, "month"),
    "3mo": (3, "month"),
}


def _massive_interval(interval: str) -> tuple[int, str]:
    """Translate a yfinance interval string to (multiplier, timespan)."""
    key = (interval or "1d").lower()
    if key not in _INTERVAL_MAP:
        logger.warning("Unknown interval %r, defaulting to 1d", interval)
        return (1, "day")
    return _INTERVAL_MAP[key]


# ----------------------------------------------------------------------
# Period translation: yfinance "1d", "5d", "1mo", "1y", "max" -> date range
# ----------------------------------------------------------------------
_PERIOD_DAYS: dict[str, int] = {
    "1d": 1,
    "5d": 5,
    "1mo": 31,
    "3mo": 93,
    "6mo": 186,
    "1y": 366,
    "2y": 732,
    "5y": 1830,
    "10y": 3660,
    "ytd": 0,  # special-cased
    "max": 365 * 20,
}


def _period_to_range(period: str) -> tuple[date, date]:
    today = dj_timezone.now().date()
    key = (period or "1d").lower()
    if key == "ytd":
        return (date(today.year, 1, 1), today)
    days = _PERIOD_DAYS.get(key, 1)
    return (today - timedelta(days=days), today)


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------
class MassiveFinanceService:
    """Massive.com REST client, drop-in replacement for YahooFinanceService."""

    def __init__(self) -> None:
        self.api_key: str = getattr(
            settings, "MASSIVE_API_KEY", "") or os.environ.get("MASSIVE_API_KEY", "")
        self.base_url: str = (
            getattr(settings, "MASSIVE_API_BASE_URL", "https://api.massive.com")
            or "https://api.massive.com"
        ).rstrip("/")
        self.timeout: float = float(getattr(settings, "MASSIVE_HTTP_TIMEOUT", 15.0))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "revs_ai/massive-adapter"})

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict | None:
        if not self.api_key:
            logger.error("MASSIVE_API_KEY is not configured")
            return None
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(
                url, params=params or {}, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException:
            logger.exception("Massive request failed: %s", path)
            return None

    # ------------------------------------------------------------------
    # Yahoo-shaped public API
    # ------------------------------------------------------------------
    def get_intraday_data(
        self, symbol: str, interval: str = "5m", period: str = "1d"
    ) -> dict | None:
        """OHLC bars at *interval* over the lookback *period*."""
        multiplier, timespan = _massive_interval(interval)
        from_date, to_date = _period_to_range(period)
        path = (
            f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/"
            f"{from_date.isoformat()}/{to_date.isoformat()}"
        )
        payload = self._get(path, params={"adjusted": "true", "sort": "asc", "limit": 50000})
        if not payload:
            return None
        results = payload.get("results") or []
        if not results:
            logger.warning("No intraday data found for symbol: %s", symbol)
            return None

        data = []
        for bar in results:
            ts_ms = bar.get("t")
            if ts_ms is None:
                continue
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            data.append(
                {
                    "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "open": float(bar.get("o", 0.0)),
                    "high": float(bar.get("h", 0.0)),
                    "low": float(bar.get("l", 0.0)),
                    "close": float(bar.get("c", 0.0)),
                    "volume": int(bar.get("v", 0) or 0),
                }
            )

        return {
            "symbol": symbol,
            "interval": interval,
            "data": data,
            "last_updated": dj_timezone.now().isoformat(),
        }

    def get_current_price(self, symbol: str) -> dict | None:
        """Latest price + change vs prev close, from a single snapshot call."""
        snap = self._snapshot_single(symbol)
        if not snap:
            return None
        return self._snapshot_to_price(symbol, snap)

    def get_stock_info(self, symbol: str) -> dict | None:
        """Reference data: name, sector (SIC), exchange, market cap, currency."""
        payload = self._get(f"/v3/reference/tickers/{symbol}")
        if not payload:
            return None
        info = payload.get("results") or {}
        if not info:
            return None
        return {
            "symbol": symbol,
            "name": info.get("name", ""),
            "sector": info.get("sic_description", ""),
            "industry": info.get("type", ""),
            "exchange": info.get("primary_exchange", ""),
            "market_cap": info.get("market_cap"),
            "description": info.get("description", ""),
            "currency": (info.get("currency_name") or "USD").upper(),
        }

    def get_multiple_current_prices(self, symbols: list[str]) -> dict[str, dict | None]:
        snaps = self._snapshot_multi(symbols)
        return {
            sym: (self._snapshot_to_price(sym, snaps.get(sym)) if snaps.get(sym) else None)
            for sym in symbols
        }

    def get_multiple_current_quotes(self, symbols: list[str]) -> dict[str, dict | None]:
        snaps = self._snapshot_multi(symbols)
        return {
            sym: (self._snapshot_to_quote(sym, snaps.get(sym)) if snaps.get(sym) else None)
            for sym in symbols
        }

    def get_current_quote(self, symbol: str) -> dict | None:
        snap = self._snapshot_single(symbol)
        if not snap:
            return None
        return self._snapshot_to_quote(symbol, snap)

    def get_daily_price(self, symbol: str, period: str = "1d") -> list[dict] | None:
        from_date, to_date = _period_to_range(period)
        path = (
            f"/v2/aggs/ticker/{symbol}/range/1/day/"
            f"{from_date.isoformat()}/{to_date.isoformat()}"
        )
        payload = self._get(path, params={"adjusted": "true", "sort": "asc", "limit": 50000})
        if not payload:
            return None
        results = payload.get("results") or []
        if not results:
            logger.warning("No daily price data found for symbol: %s", symbol)
            return None

        out: list[dict] = []
        for bar in results:
            ts_ms = bar.get("t")
            if ts_ms is None:
                continue
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
            close = float(bar.get("c", 0.0))
            out.append(
                {
                    "date": dt.isoformat(),
                    "open": float(bar.get("o", 0.0)),
                    "high": float(bar.get("h", 0.0)),
                    "low": float(bar.get("l", 0.0)),
                    "close": close,
                    "adj_close": close,  # Massive aggregates already adjusted on demand
                    "volume": int(bar.get("v", 0) or 0),
                }
            )
        return out

    # ------------------------------------------------------------------
    # New: bars with timestamps, used by sync_historical_data
    # ------------------------------------------------------------------
    def get_historical_bars(
        self,
        symbol: str,
        interval: str = "1d",
        period: str = "1y",
        start: date | None = None,
        end: date | None = None,
    ) -> list[dict] | None:
        """Aggregate bars with both ``date`` and tz-aware ``timestamp`` fields.

        Used by ``sync_historical_data`` to persist ``StockPrice`` rows.
        """
        multiplier, timespan = _massive_interval(interval)
        if start and end:
            from_date, to_date = start, end
        else:
            from_date, to_date = _period_to_range(period)
        path = (
            f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/"
            f"{from_date.isoformat()}/{to_date.isoformat()}"
        )
        payload = self._get(path, params={"adjusted": "true", "sort": "asc", "limit": 50000})
        if not payload:
            return None
        results = payload.get("results") or []
        out: list[dict] = []
        for bar in results:
            ts_ms = bar.get("t")
            if ts_ms is None:
                continue
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            close = float(bar.get("c", 0.0))
            out.append(
                {
                    "date": dt.date(),
                    "timestamp": dt,
                    "open": float(bar.get("o", 0.0)),
                    "high": float(bar.get("h", 0.0)),
                    "low": float(bar.get("l", 0.0)),
                    "close": close,
                    "adj_close": close,
                    "volume": int(bar.get("v", 0) or 0),
                }
            )
        return out

    # ------------------------------------------------------------------
    # Snapshot helpers
    # ------------------------------------------------------------------
    def _snapshot_single(self, symbol: str) -> dict | None:
        payload = self._get(
            f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}"
        )
        if not payload:
            return None
        return payload.get("ticker")

    def _snapshot_multi(self, symbols: list[str]) -> dict[str, dict | None]:
        if not symbols:
            return {}
        # Massive caps multi-snapshot at ~250 tickers per call; chunk.
        chunk_size = 200
        out: dict[str, dict | None] = {s: None for s in symbols}
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i : i + chunk_size]
            payload = self._get(
                "/v2/snapshot/locale/us/markets/stocks/tickers",
                params={"tickers": ",".join(chunk)},
            )
            if not payload:
                continue
            for snap in payload.get("tickers", []) or []:
                sym = snap.get("ticker")
                if sym:
                    out[sym] = snap
        return out

    @staticmethod
    def _snapshot_to_price(symbol: str, snap: dict | None) -> dict | None:
        if not snap:
            return None
        day = snap.get("day") or {}
        prev = snap.get("prevDay") or {}
        last_trade = snap.get("lastTrade") or {}
        last_quote = snap.get("lastQuote") or {}

        price = float(last_trade.get("p") or day.get("c") or 0.0)
        prev_close = float(prev.get("c") or 0.0)
        ts_ns = last_trade.get("t") or last_quote.get("t") or snap.get("updated")
        timestamp_str = MassiveFinanceService._format_ts(ts_ns)

        change = price - prev_close
        change_percent = (change / prev_close * 100) if prev_close > 0 else 0.0

        return {
            "symbol": symbol,
            "price": price,
            "open": float(day.get("o") or 0.0),
            "high": float(day.get("h") or 0.0),
            "low": float(day.get("l") or 0.0),
            "volume": int(day.get("v") or 0),
            "timestamp": timestamp_str,
            "previous_close": prev_close,
            "change": change,
            "change_percent": change_percent,
        }

    @staticmethod
    def _snapshot_to_quote(symbol: str, snap: dict | None) -> dict | None:
        if not snap:
            return None
        day = snap.get("day") or {}
        last_trade = snap.get("lastTrade") or {}
        last_quote = snap.get("lastQuote") or {}

        price = float(last_trade.get("p") or day.get("c") or 0.0)
        if price <= 0:
            return None
        ts_ns = last_trade.get("t") or last_quote.get("t") or snap.get("updated")
        timestamp_str = MassiveFinanceService._format_ts(ts_ns)

        return {
            "symbol": symbol,
            "price": price,
            "volume": int(day.get("v") or 0),
            "bid": float(last_quote["p"]) if last_quote.get("p") else None,
            "ask": float(last_quote["P"]) if last_quote.get("P") else None,
            "bid_size": int(last_quote["s"]) if last_quote.get("s") else None,
            "ask_size": int(last_quote["S"]) if last_quote.get("S") else None,
            "timestamp": timestamp_str,
        }

    @staticmethod
    def _format_ts(ts: Any) -> str:
        """Format Massive timestamps (ns/ms epoch) as 'YYYY-MM-DD HH:MM:SS' UTC."""
        if ts is None:
            return dj_timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            return dj_timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        # Heuristic: ns vs ms vs s based on magnitude
        if ts > 1e15:
            seconds = ts / 1e9
        elif ts > 1e11:
            seconds = ts / 1e3
        else:
            seconds = float(ts)
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )


# Singleton — imported by stocks/services.py and re-exported for callers
massive_finance_service = MassiveFinanceService()
