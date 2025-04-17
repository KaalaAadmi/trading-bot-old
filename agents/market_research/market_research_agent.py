import logging
import pandas as pd
import requests
from core.redis_bus.redis_stream import RedisStream
from core.config.config_loader import load_settings
from sqlalchemy import create_engine
import os
import json
import yfinance as yf
import time

# Initialize logger
logger = logging.getLogger("agents.market_research")

class MarketResearchAgent:
    def __init__(self, settings_path=None):
        # Load settings
        if settings_path:
            self.settings = load_settings(settings_path=settings_path)
        else:
            self.settings = load_settings()

        # Initialize Redis Streams
        self.redis_stream = RedisStream()
        self.ticker_updates_channel = self.redis_stream.get_channel("ticker_updater")  # Subscribe to ticker_updates_channel
        self.market_research_signals_channel = self.redis_stream.get_channel("market_research")  # Publish to market_research_signals

        # Initialize database connection
        db_config = self.settings["database"]
        self.db_engine = create_engine(
            f"postgresql://{db_config['user']}:{db_config['password']}@{db_config['host']}:{db_config['port']}/{db_config['db']}"
        )

    def subscribe_to_ticker_updates(self):
        """Subscribe to the ticker update completion stream."""
        logger.info("Subscribing to stream '%s' for ticker updates.", self.ticker_updates_channel)
        self.redis_stream.subscribe(self.ticker_updates_channel, self.run_on_message)
        time.sleep(1)  # Ensure the subscription is active before messages are published
        
    def run_on_message(self, message):
        """Run the Market Research Agent when a message is received."""
        logger.info("Received message on stream '%s': %s", self.ticker_updates_channel, message)
        self.run()

    def fetch_assets(self):
        """Fetch a list of assets to screen from the tickers.json file."""
        try:
            ticker_file_path = self.settings["tickers"]["file_path"]
            if not os.path.exists(ticker_file_path):
                logger.error("Ticker file not found at %s. Ensure TickerUpdaterAgent has run.", ticker_file_path)
                return []

            with open(ticker_file_path, "r") as file:
                tickers = json.load(file)
                logger.info("Loaded tickers from %s: %s", ticker_file_path, tickers)

                # Combine sp500 and coin50 tickers
                return tickers.get("sp500", []) + tickers.get("coin50", [])
        except Exception as e:
            logger.error("Failed to load tickers from file: %s", str(e))
            return []

    def fetch_ohlcv(self, asset, convert_to_eur=True):
        """Fetch OHLCV data for a given asset using yfinance."""
        try:
            logger.debug("Fetching OHLCV data for ticker: %s", asset)
            ticker = yf.Ticker(asset)
            df = ticker.history(period="30d", interval="1d")  # Fetch 30 days of daily data

            # If no data is returned, try fetching 1 day of data
            if df.empty:
                logger.warning("No data found for asset '%s' with 30d period. Trying 1d period...", asset)
                df = ticker.history(period="1d", interval="1d")

            # If still no data, log and return None
            if df.empty:
                logger.warning("No data found for asset '%s' after trying 1d period.", asset)
                return None

            # Format the DataFrame
            logger.debug("Raw OHLCV data for %s: %s", asset, df)
            df.reset_index(inplace=True)
            df.rename(columns={"Date": "timestamp", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]

            # Convert prices to EUR if required
            if convert_to_eur:
                exchange_rate = self.get_usd_to_eur_rate()
                df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]] * exchange_rate
                logger.info("Converted prices for %s to EUR using exchange rate: %.4f", asset, exchange_rate)

            # Calculate daily returns
            df["daily_returns"] = (df["close"] - df["open"]) / df["open"]

            logger.info("Fetched OHLCV data for asset: %s", asset)
            return df
        except Exception as e:
            logger.error("Error fetching OHLCV for asset '%s': %s", asset, str(e))
            return None

    def get_usd_to_eur_rate(self):
        """Fetch the current USD to EUR exchange rate."""
        try:
            ticker = yf.Ticker("EUR=X")  # EUR/USD exchange rate
            df = ticker.history(period="1d", interval="1d")
            if not df.empty:
                exchange_rate = 1 / df["Close"].iloc[-1]  # Convert USD to EUR
                logger.info("Fetched USD to EUR exchange rate: %.4f", exchange_rate)
                return exchange_rate
            else:
                logger.error("Failed to fetch USD to EUR exchange rate. Defaulting to 1.0.")
                return 1.0  # Default to no conversion if rate is unavailable
        except Exception as e:
            logger.error("Error fetching USD to EUR exchange rate: %s", str(e))
            return 1.0  # Default to no conversion if an error occurs
    
    def filter_assets(self, ohlcv_data, coin50, sp500):
        """Apply filters to identify assets with unmitigated FVGs and imbalance."""
        filtered_assets = []
        config = self.settings["agents"]["market_research"]

        # Extract thresholds from the configuration
        volume_threshold_stocks = config["volume_threshold"]["stocks"]
        volume_threshold_crypto = config["volume_threshold"]["crypto"]
        volatility_threshold = config["volatility_threshold"]
        # price_change_threshold = config["price_change_threshold"]  # Commented out for now
        # min_price_stocks = config["min_price"]["stocks"]  # Commented out for now
        # min_price_crypto = config["min_price"]["crypto"]  # Commented out for now

        for asset, df in ohlcv_data.items():
            if len(df) < 5:  # Ensure there are enough data points for the rolling window
                logger.warning("Insufficient data for asset '%s'. Skipping...", asset)
                continue

            try:
                # Calculate average volume (Liquidity Filter)
                avg_volume = df["volume"].tail(5).mean()
                is_liquid = (
                    avg_volume > volume_threshold_crypto
                    if asset in coin50
                    else avg_volume > volume_threshold_stocks
                )

                # Calculate daily returns and volatility (Volatility Filter)
                volatility = df["daily_returns"].tail(14).std()
                is_volatile = volatility > volatility_threshold
                # Calculate recent price movement (Momentum Filter) - Commented out for now
                # recent_change = (df["price"].iloc[-1] - df["price"].iloc[-5]) / df["price"].iloc[-5]
                # has_momentum = abs(recent_change) > price_change_threshold

                # Check minimum price (Price Filter) - Commented out for now
                # last_price = df["price"].iloc[-1]
                # is_valid_price = (
                #     last_price > min_price_crypto
                #     if asset in self.settings["tickers"]["coin50"]
                #     else last_price > min_price_stocks
                # )

                # Apply only liquidity and volatility filters for now
                # print(f"{asset}: Vol={avg_volume:.0f}, Volatility={volatility:.4f}")
                logger.info(
                    "Asset: %s, Avg Volume: %.0f, Volatility: %.4f",
                    asset, avg_volume, volatility
                )

                # Apply only liquidity and volatility filters for now
                if is_liquid and is_volatile:
                    filtered_assets.append(asset)
            except Exception as e:
                logger.error("Error filtering asset '%s': %s", asset, str(e))

        logger.info("Filtered %d assets based on liquidity and volatility criteria.", len(filtered_assets))
        return filtered_assets

    def store_data(self, asset, df):
        """Store OHLCV data in TimescaleDB."""
        df.to_sql("ohlcv_data", self.db_engine, if_exists="append", index=False)
        logger.info("Stored OHLCV data for asset: %s", asset)

    def run(self):
        """Run the Market Research Agent."""
        logger.info("Starting Market Research Agent...")
        assets = self.fetch_assets()
        coin50 = [ticker for ticker in assets if ticker.endswith("-EUR")]
        sp500 = [ticker for ticker in assets if not ticker.endswith("-EUR")]

        ohlcv_data = {
            asset: self.fetch_ohlcv(asset) for asset in assets
            if self.fetch_ohlcv(asset) is not None  # Skip assets with missing data
        }
        filtered_assets = self.filter_assets(ohlcv_data, coin50, sp500)
        
        # Publish the filtered assets as a list to the market_research_signals stream
        self.redis_stream.publish(self.market_research_signals_channel, {"filtered_assets": json.dumps(filtered_assets)})
        logger.info("Published filtered assets to stream '%s': %s", self.market_research_signals_channel, filtered_assets)
        
        logger.info("Market Research Agent processing completed. Filtered %d assets for next steps.", len(filtered_assets))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = MarketResearchAgent()
    agent.run()