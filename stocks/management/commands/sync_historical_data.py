"""
Management command to sync historical stock data from Yahoo Finance.
This command fetches daily historical data for all active stocks in the database.
"""

import logging
import time
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from stocks.models import Stock, StockPrice

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync historical stock data from Yahoo Finance for all active stocks"

    def add_arguments(self, parser):
        parser.add_argument(
            "--symbols",
            type=str,
            help="Comma-separated list of stock symbols to sync (e.g., AAPL,GOOGL,MSFT). If not provided, syncs all active stocks.",
        )
        parser.add_argument(
            "--period",
            type=str,
            choices=[
                "1d",
                "5d",
                "1mo",
                "3mo",
                "6mo",
                "1y",
                "2y",
                "5y",
                "10y",
                "ytd",
                "max",
            ],
            default="10y",
            help="Period of historical data to fetch (default: 1y)",
        )
        parser.add_argument(
            "--interval",
            type=str,
            choices=["1d", "5d", "1wk", "1mo", "3mo"],
            default="1d",
            help="Data interval (default: 1d for daily)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=5,
            help="Number of stocks to process in each batch (default: 5)",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=1.0,
            help="Delay between batches in seconds (default: 1.0)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force update even if historical data already exists",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without actually updating data",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            help="Start date for historical data (YYYY-MM-DD format). Overrides --period.",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            help="End date for historical data (YYYY-MM-DD format). Defaults to today.",
        )

    def handle(self, *args, **options):
        start_time = timezone.now()
        self.stdout.write(f"Starting historical data sync at {start_time}")

        # Determine which stocks to sync
        if options["symbols"]:
            symbols = [s.strip().upper() for s in options["symbols"].split(",")]
            stocks = Stock.objects.filter(symbol__in=symbols, is_active=True)

            # Check if all symbols exist
            found_symbols = set(stocks.values_list("symbol", flat=True))
            missing_symbols = set(symbols) - found_symbols
            if missing_symbols:
                self.stdout.write(
                    self.style.WARNING(
                        f"Symbols not found in database: {', '.join(missing_symbols)}"
                    )
                )
        else:
            stocks = Stock.objects.filter(is_active=True)

        if not stocks.exists():
            msg = "No active stocks found to sync"
            raise CommandError(msg)

        total_stocks = stocks.count()
        self.stdout.write(f"Found {total_stocks} active stocks to sync")

        # Parse date parameters
        start_date = None
        end_date = None

        if options["start_date"]:
            try:
                start_date = datetime.strptime(options["start_date"], "%Y-%m-%d").date()  # noqa: DTZ007
            except ValueError as err:
                msg = "Invalid start date format. Use YYYY-MM-DD."
                raise CommandError(msg) from err

        if options["end_date"]:
            try:
                end_date = datetime.strptime(options["end_date"], "%Y-%m-%d").date()  # noqa: DTZ007
            except ValueError as err:
                msg = "Invalid end date format. Use YYYY-MM-DD."
                raise CommandError(msg) from err
        else:
            end_date = timezone.now().date()

        # Check if we should skip stocks that already have historical data
        if not options["force"]:
            stocks_with_data = (
                StockPrice.objects.filter(interval=options["interval"])
                .values_list("stock__symbol", flat=True)
                .distinct()
            )

            if stocks_with_data:
                self.stdout.write(
                    f"Skipping {len(stocks_with_data)} stocks that already have historical data. Use --force to override."
                )
                stocks = stocks.exclude(symbol__in=stocks_with_data)

        if not stocks.exists():
            self.stdout.write(
                self.style.SUCCESS("All stocks already have historical data")
            )
            return

        # Process stocks in batches
        batch_size = options["batch_size"]
        delay = options["delay"]
        interval = options["interval"]
        period = options["period"]

        success_count = 0
        error_count = 0
        total_records = 0

        # Process in batches to avoid overwhelming the API
        stock_list = list(stocks)
        for i in range(0, len(stock_list), batch_size):
            batch = stock_list[i : i + batch_size]
            batch_symbols = [stock.symbol for stock in batch]

            self.stdout.write(
                f"Processing batch {i // batch_size + 1}: {', '.join(batch_symbols)}"
            )

            if options["dry_run"]:
                self.stdout.write(
                    f"[DRY RUN] Would fetch {interval} historical data for: {', '.join(batch_symbols)}"
                )
                success_count += len(batch)
                continue

            # Process each stock in the batch
            for stock in batch:
                try:
                    records_created = self._sync_stock_historical_data(
                        stock,
                        period=period,
                        interval=interval,
                        start_date=start_date,
                        end_date=end_date,
                    )

                    if records_created > 0:
                        success_count += 1
                        total_records += records_created
                        self.stdout.write(
                            f"✓ {stock.symbol}: {records_created} historical records"
                        )
                    else:
                        error_count += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"✗ {stock.symbol}: No historical data received"
                            )
                        )

                except Exception as e:
                    error_count += 1
                    logger.exception("Error processing %s", stock.symbol)
                    self.stdout.write(self.style.ERROR(f"✗ {stock.symbol}: {e!s}"))

            # Add delay between batches to be respectful to the API
            if i + batch_size < len(stock_list) and delay > 0:
                time.sleep(delay)

        # Summary
        end_time = timezone.now()
        duration = end_time - start_time

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(f"Historical data sync completed in {duration}")
        self.stdout.write(f"Successfully processed: {success_count}")
        self.stdout.write(f"Errors: {error_count}")
        self.stdout.write(f"Total stocks: {success_count + error_count}")
        self.stdout.write(f"Total historical records created: {total_records}")

        if error_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"Completed with {error_count} errors. Check logs for details."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("All stocks processed successfully!"))

    def _sync_stock_historical_data(
        self, stock, period="1y", interval="1d", start_date=None, end_date=None
    ):
        """Sync historical data for a single stock."""
        try:
            # Fetch historical bars from Massive
            from stocks.providers.massive import massive_finance_service

            bars = massive_finance_service.get_historical_bars(
                stock.symbol,
                interval=interval,
                period=period,
                start=start_date,
                end=end_date,
            )

            if not bars:
                logger.warning(
                    f"No historical data found for symbol: {stock.symbol}"
                )
                return 0

            records_created = 0

            with transaction.atomic():
                # Delete existing data for this stock and interval if force updating
                StockPrice.objects.filter(stock=stock, interval=interval).delete()

                # Create historical price records
                historical_prices = []
                for bar in bars:
                    # Skip if any required price data is missing
                    if (
                        bar["open"] <= 0
                        or bar["high"] <= 0
                        or bar["low"] <= 0
                        or bar["close"] <= 0
                    ):
                        continue

                    historical_prices.append(
                        StockPrice(
                            stock=stock,
                            date=bar["date"],
                            timestamp=bar["timestamp"],
                            interval=interval,
                            open_price=bar["open"],
                            high_price=bar["high"],
                            low_price=bar["low"],
                            close_price=bar["close"],
                            adjusted_close=bar["adj_close"],
                            volume=bar["volume"],
                        )
                    )

                # Bulk create for efficiency
                if historical_prices:
                    StockPrice.objects.bulk_create(historical_prices, batch_size=1000)
                    records_created = len(historical_prices)

        except Exception:
            logger.exception("Error syncing historical data for %s", stock.symbol)
            raise
        return records_created
