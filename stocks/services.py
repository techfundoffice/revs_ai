"""
API services for fetching real-time stock data from various sources.
"""

import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class AlphaVantageService:
    """Service class for interacting with Alpha Vantage API."""

    def __init__(self):
        self.api_key = settings.ALPHA_VANTAGE_API_KEY
        self.base_url = settings.ALPHA_VANTAGE_BASE_URL
        self.session = requests.Session()

        if not self.api_key:
            logger.warning("Alpha Vantage API key not configured")

    def _make_request(self, params: dict[str, Any]) -> dict | None:
        """Make a request to Alpha Vantage API with rate limiting."""
        if not self.api_key:
            logger.error("Alpha Vantage API key not configured")
            return None

        params["apikey"] = self.api_key

        try:
            response = self.session.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            # Check for API errors
            if "Error Message" in data:
                logger.error("Alpha Vantage API error: %s", data["Error Message"])
                return None

            if "Note" in data:
                logger.warning("Alpha Vantage API note: %s", data["Note"])
                # Rate limit hit, wait and retry once
                time.sleep(60)
                return None

        except requests.exceptions.RequestException:
            logger.exception("Request error")
            return None

        except ValueError:
            logger.exception("JSON decode error")
            return None
        return data

    def get_quote(self, symbol: str) -> dict | None:
        """Get real-time quote for a symbol."""
        params = {"function": "GLOBAL_QUOTE", "symbol": symbol}

        data = self._make_request(params)
        if not data or "Global Quote" not in data:
            return None

        quote = data["Global Quote"]

        try:
            return {
                "symbol": quote.get("01. symbol", symbol),
                "open_price": Decimal(quote.get("02. open", "0")),
                "high_price": Decimal(quote.get("03. high", "0")),
                "low_price": Decimal(quote.get("04. low", "0")),
                "close_price": Decimal(quote.get("05. price", "0")),
                "volume": int(quote.get("06. volume", "0")),
                "latest_trading_day": quote.get("07. latest trading day", ""),
                "previous_close": Decimal(quote.get("08. previous close", "0")),
                "change": Decimal(quote.get("09. change", "0")),
                "change_percent": quote.get("10. change percent", "0%").replace(
                    "%", ""
                ),
            }
        except (ValueError, TypeError):
            logger.exception("Error parsing quote data for %s", symbol)
            return None

    def get_daily_data(
        self, symbol: str, outputsize: str = "compact"
    ) -> list[dict] | None:
        """Get daily time series data for a symbol."""
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": outputsize,
        }

        data = self._make_request(params)
        if not data or "Time Series (Daily)" not in data:
            return None

        time_series = data["Time Series (Daily)"]
        result = []

        for date_str, values in time_series.items():
            try:
                result.append(
                    {
                        "date": timezone.make_aware(
                            datetime.strptime(date_str, "%Y-%m-%d").astimezone()
                        ).date(),
                        "open_price": Decimal(values["1. open"]),
                        "high_price": Decimal(values["2. high"]),
                        "low_price": Decimal(values["3. low"]),
                        "close_price": Decimal(values["4. close"]),
                        "volume": int(values["5. volume"]),
                    }
                )
            except (ValueError, KeyError):
                continue

        return result

    def get_intraday_data(
        self, symbol: str, interval: str = "1min", outputsize: str = "compact"
    ) -> list[dict] | None:
        """Get intraday time series data for a symbol."""
        params = {
            "function": "TIME_SERIES_INTRADAY",
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
        }

        data = self._make_request(params)
        time_series_key = f"Time Series ({interval})"

        if not data or time_series_key not in data:
            return None

        time_series = data[time_series_key]
        result = []

        for timestamp_str, values in time_series.items():
            try:
                # Parse timestamp
                timestamp = timezone.make_aware(
                    datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").astimezone()
                )

                result.append(
                    {
                        "timestamp": timestamp,
                        "interval": interval,
                        "open_price": Decimal(values["1. open"]),
                        "high_price": Decimal(values["2. high"]),
                        "low_price": Decimal(values["3. low"]),
                        "close_price": Decimal(values["4. close"]),
                        "volume": int(values["5. volume"]),
                    }
                )
            except (ValueError, KeyError):
                continue

        return result

    def search_symbols(self, keywords: str) -> list[dict] | None:
        """Search for symbols matching keywords."""
        params = {"function": "SYMBOL_SEARCH", "keywords": keywords}

        data = self._make_request(params)
        if not data or "bestMatches" not in data:
            return None

        result = []
        for match in data["bestMatches"]:
            try:
                result.append(
                    {
                        "symbol": match.get("1. symbol", ""),
                        "name": match.get("2. name", ""),
                        "type": match.get("3. type", ""),
                        "region": match.get("4. region", ""),
                        "market_open": match.get("5. marketOpen", ""),
                        "market_close": match.get("6. marketClose", ""),
                        "timezone": match.get("7. timezone", ""),
                        "currency": match.get("8. currency", ""),
                        "match_score": float(match.get("9. matchScore", "0")),
                    }
                )
            except (ValueError, KeyError):
                logger.exception("Error parsing search result")
                continue

        return result

    def get_company_overview(self, symbol: str) -> dict | None:
        """Get company overview data."""
        params = {"function": "OVERVIEW", "symbol": symbol}

        data = self._make_request(params)
        if not data or "Symbol" not in data:
            return None

        try:
            return {
                "symbol": data.get("Symbol", ""),
                "name": data.get("Name", ""),
                "description": data.get("Description", ""),
                "exchange": data.get("Exchange", ""),
                "currency": data.get("Currency", ""),
                "country": data.get("Country", ""),
                "sector": data.get("Sector", ""),
                "industry": data.get("Industry", ""),
                "market_cap": data.get("MarketCapitalization", ""),
                "pe_ratio": data.get("PERatio", ""),
                "peg_ratio": data.get("PEGRatio", ""),
                "book_value": data.get("BookValue", ""),
                "dividend_per_share": data.get("DividendPerShare", ""),
                "dividend_yield": data.get("DividendYield", ""),
                "eps": data.get("EPS", ""),
                "revenue_per_share_ttm": data.get("RevenuePerShareTTM", ""),
                "profit_margin": data.get("ProfitMargin", ""),
                "operating_margin_ttm": data.get("OperatingMarginTTM", ""),
                "return_on_assets_ttm": data.get("ReturnOnAssetsTTM", ""),
                "return_on_equity_ttm": data.get("ReturnOnEquityTTM", ""),
                "revenue_ttm": data.get("RevenueTTM", ""),
                "gross_profit_ttm": data.get("GrossProfitTTM", ""),
                "diluted_eps_ttm": data.get("DilutedEPSTTM", ""),
                "quarterly_earnings_growth_yoy": data.get(
                    "QuarterlyEarningsGrowthYOY", ""
                ),
                "quarterly_revenue_growth_yoy": data.get(
                    "QuarterlyRevenueGrowthYOY", ""
                ),
                "analyst_target_price": data.get("AnalystTargetPrice", ""),
                "trailing_pe": data.get("TrailingPE", ""),
                "forward_pe": data.get("ForwardPE", ""),
                "price_to_sales_ratio_ttm": data.get("PriceToSalesRatioTTM", ""),
                "price_to_book_ratio": data.get("PriceToBookRatio", ""),
                "ev_to_revenue": data.get("EVToRevenue", ""),
                "ev_to_ebitda": data.get("EVToEBITDA", ""),
                "beta": data.get("Beta", ""),
                "52_week_high": data.get("52WeekHigh", ""),
                "52_week_low": data.get("52WeekLow", ""),
                "50_day_moving_average": data.get("50DayMovingAverage", ""),
                "200_day_moving_average": data.get("200DayMovingAverage", ""),
                "shares_outstanding": data.get("SharesOutstanding", ""),
                "dividend_date": data.get("DividendDate", ""),
                "ex_dividend_date": data.get("ExDividendDate", ""),
            }
        except (ValueError, KeyError):
            logger.exception("Error parsing company overview for %s", symbol)
            return None

    def get_top_gainers_losers(self) -> dict | None:
        """Get top gainers, losers, and most active stocks."""
        params = {"function": "TOP_GAINERS_LOSERS"}

        data = self._make_request(params)
        if not data:
            return None

        try:
            result = {
                "metadata": data.get("metadata", {}),
                "last_updated": data.get("last_updated", ""),
                "top_gainers": [],
                "top_losers": [],
                "most_actively_traded": [],
            }

            # Process top gainers
            for item in data.get("top_gainers", []):
                result["top_gainers"].append(
                    {
                        "ticker": item.get("ticker", ""),
                        "price": Decimal(item.get("price", "0")),
                        "change_amount": Decimal(item.get("change_amount", "0")),
                        "change_percentage": item.get(
                            "change_percentage", "0%"
                        ).replace("%", ""),
                        "volume": int(item.get("volume", "0")),
                    }
                )

            # Process top losers
            for item in data.get("top_losers", []):
                result["top_losers"].append(
                    {
                        "ticker": item.get("ticker", ""),
                        "price": Decimal(item.get("price", "0")),
                        "change_amount": Decimal(item.get("change_amount", "0")),
                        "change_percentage": item.get(
                            "change_percentage", "0%"
                        ).replace("%", ""),
                        "volume": int(item.get("volume", "0")),
                    }
                )

            # Process most actively traded
            for item in data.get("most_actively_traded", []):
                result["most_actively_traded"].append(
                    {
                        "ticker": item.get("ticker", ""),
                        "price": Decimal(item.get("price", "0")),
                        "change_amount": Decimal(item.get("change_amount", "0")),
                        "change_percentage": item.get(
                            "change_percentage", "0%"
                        ).replace("%", ""),
                        "volume": int(item.get("volume", "0")),
                    }
                )

        except (ValueError, KeyError):
            logger.exception("Error parsing top gainers/losers data")
            return None
        return result


# Yahoo Finance has been replaced with Massive.com.  ``YahooFinanceService``
# is kept as a back-compat alias so any imports of the class name continue
# to work; new callers should import ``MassiveFinanceService`` directly from
# ``stocks.providers.massive``.
from .providers.massive import MassiveFinanceService

YahooFinanceService = MassiveFinanceService


# Singleton instances
alpha_vantage_service = AlphaVantageService()
yahoo_finance_service = MassiveFinanceService()
