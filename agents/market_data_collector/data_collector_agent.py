import logging
import pandas as pd
import yfinance as yf
from sqlalchemy.ext.asyncio import create_async_engine
from core.redis_bus.redis_stream import RedisStream
from core.config.config_loader import load_settings
import json
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential
from prometheus_client import Counter, Histogram, start_http_server
from asyncio import Semaphore
from sqlalchemy.sql import text
from datetime import datetime, time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import agents.common.utils as common

# Initialize logger
logger = logging.getLogger("agents.data_collector")

# Prometheus metrics
FETCH_DURATION = Histogram("fetch_duration_seconds", "Time taken to fetch OHLCV data")
FETCH_ERRORS = Counter("fetch_errors_total", "Total number of fetch errors")
PROCESSED_ASSETS = Counter("processed_assets_total", "Total number of processed assets")

class DataCollectorAgent:
    def __init__(self, settings_path=None):
        # Load settings
        if settings_path:
            self.settings = load_settings(settings_path=settings_path)
        else:
            self.settings = load_settings()

        # Initialize Redis Streams
        self.redis_stream = RedisStream()
        self.filtered_assets_channel = self.redis_stream.get_channel("market_research")  # Fetch the channel for filtered assets
        self.raw_data_channel = self.redis_stream.get_channel("data_collector")  # Fetch the channel for publishing raw data

        if not self.raw_data_channel:
            raise ValueError("Redis channel for 'data_collector' is not defined in settings.yaml.")

        # Initialize database connection
        db_config = self.settings["database"]
        self.db_engine = create_async_engine(
            f"postgresql+asyncpg://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['db']}",
            pool_size=10,
            max_overflow=5
        )

        # Load timeframes and history settings
        self.timeframes = self.settings["timeframes"]
        self.history = self.settings["history"]

        # Track filtered assets
        self.filtered_assets = []

        # Track failed assets
        self.failed_assets = []

        # Start Prometheus metrics server
        start_http_server(8000)

        self._semaphore = None  # Placeholder
        self._loop = None  # Track the loop this agent is tied to
        
        # Exchange rate for usd/eur
        self.exchange_rate = common.get_usd_to_eur_rate()


    @property
    def semaphore(self):
        """Ensure semaphore is used within the correct event loop."""
        current_loop = asyncio.get_running_loop()
        if self._semaphore is None:
            raise RuntimeError("Semaphore is not initialized. Call 'start' method first.")
        if current_loop != self._loop:
            raise RuntimeError("Semaphore is bound to a different event loop.")
        return self._semaphore

    async def subscribe_to_filtered_assets(self):
        """Subscribe to the market_research_signals stream."""
        logger.info("Subscribing to stream '%s' for filtered assets.", self.filtered_assets_channel)
        self.redis_stream.subscribe(
            self.filtered_assets_channel,
            self.process_filtered_assets,
            consumer_group="data_collector_group",
            consumer_name="data_collector_consumer"
        )

    async def process_filtered_assets(self, message):
        """Process the filtered assets message."""
        self.failed_assets = []
        try:
            logger.info("Received message on stream '%s': %s", self.filtered_assets_channel, message)
            filtered_assets = json.loads(message.get("filtered_assets", "[]"))
            if not filtered_assets:
                logger.warning("No filtered assets found in the message.")
                return

            # Update the in-memory list of filtered assets
            self.filtered_assets = filtered_assets

            # Fetch and store OHLCV data for all assets concurrently with a semaphore
            ltf_tasks = [asyncio.create_task(self.process_ohlcv(asset, "ltf")) for asset in filtered_assets]
            htf_tasks = [asyncio.create_task(self.process_ohlcv(asset, "htf")) for asset in filtered_assets]

            await asyncio.gather(*ltf_tasks, *htf_tasks)

            if self.failed_assets:
                logger.warning("🚫 The following assets failed to fetch data:")
                for asset, timeframe in self.failed_assets:
                    logger.warning(" - %s (%s)", asset, timeframe)
            else:
                logger.info("✅ All assets successfully fetched for both timeframes.")

            logger.info("Processed filtered assets: %s", filtered_assets)
        except Exception as e:
            logger.error("Error processing filtered assets: %s", str(e))

    async def process_ohlcv(self, asset, timeframe_key):
        """Fetch and store OHLCV data for a given asset and timeframe."""
        async with self.semaphore:
            try:
                timeframe = self.timeframes[timeframe_key]
                lookback_days = self.history[f"{timeframe_key}_lookback_days"]

                # Get the last fetched timestamp
                last_fetched = await self.get_last_fetched_timestamp(asset, timeframe)

                logger.info("Fetching %s data for asset '%s' after %s...", timeframe_key, asset, last_fetched)
                df = self.fetch_ohlcv(asset, timeframe, lookback_days, last_fetched)
                if df is None or df.empty:
                    logger.warning("❌ No data fetched for asset '%s' (%s).", asset, timeframe)
                    self.failed_assets.append((asset, timeframe))
                    return  # Skip further steps
                if df is not None:
                    logger.info("Fetched %d rows of '%s' data for asset '%s'.", len(df), timeframe, asset)
                if df is None or df.empty:
                    logger.warning("No data fetched for asset '%s' with timeframe '%s'.", asset, timeframe)

                if df is not None and not df.empty:
                    await self.store_data(asset, timeframe, df)
                    if len(df) < 10:  # tweak this threshold as needed
                        logger.warning("⚠️ Very few rows (%d) for asset '%s' (%s). Might be incomplete.", len(df), asset, timeframe)

                    await self.publish_raw_data_event(asset, timeframe, df)
                    await self.update_last_fetched_timestamp(asset, timeframe, str(df["timestamp"].iloc[-1]))
                    PROCESSED_ASSETS.inc()
                else:
                    logger.error("⚠️ No data returned for asset '%s' (%s).", asset, timeframe)

            except Exception as e:
                logger.error("Error processing OHLCV data for asset '%s': %s", asset, str(e))

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    @FETCH_DURATION.time()
    def fetch_ohlcv(self, asset, timeframe, lookback_days, last_fetched=None):
        """Fetch OHLCV data using yfinance."""
        try:
            ticker = yf.Ticker(asset)
            # rate = common.get_usd_to_eur_rate()
            if last_fetched:
                # Fetch data starting from the last fetched timestamp
                start_date = last_fetched.strftime("%Y-%m-%d")
                logger.info("Fetching data for asset '%s' from %s for timeframe '%s'...", asset, start_date, timeframe)
                df = ticker.history(start=start_date, interval=timeframe)
            else:
                # Fetch the entire lookback period
                logger.info("Fetching %d days of '%s' data for asset '%s'...", lookback_days, timeframe, asset)
                df = ticker.history(period=f"{lookback_days}d", interval=timeframe)

            if df.empty:
                logger.warning("No data found for asset '%s' with timeframe '%s'.", asset, timeframe)
                return None
            
            # Reset the index and rename columns
            df.reset_index(inplace=True)
            df.rename(columns={"Datetime": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
            df[["open", "high", "low", "close"]] *= self.exchange_rate
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            df["symbol"] = asset
            df["timeframe"] = timeframe

            logger.info("Fetched %d rows of '%s' data for asset '%s'.", len(df), timeframe, asset)
            return df
        except Exception as e:
            FETCH_ERRORS.inc()
            logger.error("Error fetching OHLCV data for asset '%s': %s", asset, str(e))
            return None

    async def store_data(self, asset, timeframe, df):
        try:
            async with self.db_engine.begin() as conn:
                inserted = 0
                for _, row in df.iterrows():
                    result = await conn.execute(
                        text("""
                            INSERT INTO ohlcv_data (symbol, timeframe, timestamp, open, high, low, close, volume)
                            VALUES (:symbol, :timeframe, :timestamp, :open, :high, :low, :close, :volume)
                            ON CONFLICT (symbol, timestamp, timeframe) DO NOTHING
                        """),
                        {
                            "symbol": asset,
                            "timeframe": timeframe,
                            "timestamp": row["timestamp"],
                            "open": row["open"],
                            "high": row["high"],
                            "low": row["low"],
                            "close": row["close"],
                            "volume": row["volume"],
                        }
                    )
                    if result.rowcount == 1:
                        inserted += 1
            logger.info("Inserted %d rows of '%s' data for asset '%s'.", inserted, timeframe, asset)
        except Exception as e:
            logger.error("Error storing OHLCV data for asset '%s': %s", asset, str(e))
            raise # Re-raise the exception for further handling

    async def publish_raw_data_event(self, asset, timeframe, df):
        """Publish a raw data event to the Redis Stream."""
        try:
            if not self.raw_data_channel:
                raise ValueError("Redis channel for 'data_collector' is not defined.")

            start_time = str(df["timestamp"].iloc[0])
            end_time = str(df["timestamp"].iloc[-1])
            message = {
                "ticker": asset,
                "timeframe": timeframe,
                "new_data": "true",  # Convert boolean to string
                "range": f"[{start_time}, {end_time}]"  # Convert list to string
            }
            self.redis_stream.publish(self.raw_data_channel, message)
            logger.info("Published raw data event to stream '%s': %s", self.raw_data_channel, message)
        except Exception as e:
            logger.error("Error publishing raw data event for asset '%s': %s", asset, str(e))

    async def get_last_fetched_timestamp(self, asset, timeframe):
        """Retrieve the last fetched timestamp for a given asset and timeframe from Redis."""
        try:
            key = f"last_fetched:{asset}:{timeframe}"
            timestamp = self.redis_stream.redis.get(key)
            if timestamp:
                logger.info("Last fetched timestamp for asset '%s' with timeframe '%s': %s", asset, timeframe, timestamp)
                return datetime.fromisoformat(timestamp)
            else:
                logger.warning("No previous data found for asset '%s' with timeframe '%s'. Fetching from the beginning of the lookback period.", asset, timeframe)
                return None
        except Exception as e:
            logger.error("Error retrieving last fetched timestamp for asset '%s' with timeframe '%s': %s", asset, timeframe, str(e))
            return None

    async def update_last_fetched_timestamp(self, asset, timeframe, timestamp):
        """Update the last fetched timestamp for a given asset and timeframe in Redis."""
        try:
            # Ensure timestamp is a datetime object
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp)
            elif not isinstance(timestamp, datetime):
                raise ValueError("Invalid timestamp format. Must be a datetime object or ISO 8601 string.")

            key = f"last_fetched:{asset}:{timeframe}"
            self.redis_stream.redis.set(key, timestamp.isoformat(), ex=86400)
            logger.info("Updated last fetched timestamp for asset '%s' with timeframe '%s': %s", asset, timeframe, timestamp)
        except Exception as e:
            logger.error("Error updating last fetched timestamp for asset '%s' with timeframe '%s': %s", asset, timeframe, str(e))
            raise  # Re-raise the exception for further handling

    async def start(self):
        """Start the Data Collector Agent."""
        logger.info("Starting the Data Collector Agent...")

        # Initialize the semaphore in the correct event loop
        # self._semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent tasks
        self._loop = asyncio.get_running_loop()
        self._semaphore = asyncio.Semaphore(5)

        # Subscribe to the filtered assets channel
        await self.subscribe_to_filtered_assets()

        # Perform the initial data fetch
        # Wait until filtered assets are received
        while not self.filtered_assets:
            logger.info("Waiting for filtered assets...")
            await asyncio.sleep(1)

        # Now fetch live data
        logger.info("Performing initial data fetch...")
        await self.fetch_live_data()

        # Schedule periodic fetching of LTF and HTF data
        scheduler = AsyncIOScheduler()
        htf_interval = self.history["htf_interval_minutes"]  # Use interval from settings
        ltf_interval = self.history["ltf_interval_minutes"]  # Use interval from settings

        scheduler.add_job(self.fetch_htf_data, "interval", minutes=htf_interval, id="htf_fetch_job")
        scheduler.add_job(self.fetch_ltf_data, "interval", minutes=ltf_interval, id="ltf_fetch_job")

        scheduler.start()
        logger.info("Scheduled LTF and HTF data fetching jobs.")

    async def fetch_live_data(self):
        """Fetch live data for all tracked assets periodically."""
        if not self.filtered_assets:
            logger.warning("No filtered assets to fetch live data for.")
            return

        logger.info("Fetching live data for tracked assets: %s", self.filtered_assets)

        # Fetch HTF data
        htf_tasks = [asyncio.create_task(self.process_ohlcv(asset, "htf")) for asset in self.filtered_assets]
        await asyncio.gather(*htf_tasks)
        
        # Fetch LTF data
        ltf_tasks = [asyncio.create_task(self.process_ohlcv(asset, "ltf")) for asset in self.filtered_assets]
        await asyncio.gather(*ltf_tasks)

        logger.info("✅ Finished fetching data for %d assets. Check logs for assets with missing or partial data.", len(self.filtered_assets))


    async def fetch_ltf_data(self):
        """Fetch LTF data for all tracked assets."""
        if common.is_weekend_or_holiday():
            # Fetch only crypto data
            assets = [asset for asset in self.filtered_assets if asset.endswith("-USD")]
        elif common.is_market_open():
            # Fetch stock data during market hours
            assets = [asset for asset in self.filtered_assets if not asset.endswith("-USD")]
        else:
            logger.info("Market is closed. Skipping LTF data fetch.")
            return

        logger.info("Fetching LTF data for tracked assets...")
        tasks = [asyncio.create_task(self.process_ohlcv(asset, "ltf")) for asset in assets]
        await asyncio.gather(*tasks)


    async def fetch_htf_data(self):
        """Fetch HTF data for all tracked assets."""
        if common.is_weekend_or_holiday():
            # Fetch only crypto data
            assets = [asset for asset in self.filtered_assets if asset.endswith("-USD")]
        elif common.is_market_open():
            # Fetch stock data during market hours
            assets = [asset for asset in self.filtered_assets if not asset.endswith("-USD")]
        else:
            logger.info("Market is closed. Skipping HTF data fetch.")
            return

        logger.info("Fetching HTF data for tracked assets...")
        tasks = [asyncio.create_task(self.process_ohlcv(asset, "htf")) for asset in assets]
        await asyncio.gather(*tasks)