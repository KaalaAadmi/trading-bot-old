import requests
import json
import logging
import os
import yfinance as yf
import pandas as pd
from io import StringIO
from core.config.config_loader import load_settings
from core.redis_bus.redis_stream import RedisStream

# Initialize logger
logger = logging.getLogger("agents.ticker_updater")

class TickerUpdaterAgent:
    def __init__(self, output_path=None):
        settings = load_settings()
        self.output_path = output_path or settings["tickers"]["file_path"]
        self.redis_stream = RedisStream()  # Initialize Redis Streams
        self.channel = self.redis_stream.get_channel("ticker_updater")  # Fetch stream name from settings.yaml
        logger.info("Initialized TickerUpdaterAgent with stream '%s'.", self.channel)
        
    def fetch_sp500_tickers(self):
        """Fetch the S&P500 ticker list from Wikipedia."""
        try:
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            response = requests.get(url)
            response.raise_for_status()
            tables = pd.read_html(StringIO(response.text))  # Wrap in StringIO
            sp500_table = tables[0]  # The first table contains the S&P500 tickers
            tickers = sp500_table["Symbol"].tolist()
            logger.info("Fetched %d S&P500 tickers from Wikipedia.", len(tickers))
            return tickers
        except Exception as e:
            logger.error("Failed to fetch S&P500 tickers: %s", str(e))
            return []

    def fetch_coin50_tickers(self):
        """Fetch the Coin50 ticker list sorted by trading volume."""
        try:
            url = "https://api.coingecko.com/api/v3/coins/markets"
            params = {"vs_currency": "eur", "order": "volume_desc", "per_page": 50, "page": 1}
            response = requests.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            # Append "-EUR" to each symbol
            tickers = [f"{coin['symbol'].upper()}-EUR" for coin in data]
            logger.info("Fetched %d Coin50 tickers sorted by volume.", len(tickers))
            return tickers
        except Exception as e:
            logger.error("Failed to fetch Coin50 tickers: %s", str(e))
            return []

    def update_tickers(self):
        """Fetch and update the ticker list."""
        try:
            sp500_tickers = self.fetch_sp500_tickers()
            coin50_tickers = self.fetch_coin50_tickers()

            # Combine and save the tickers
            tickers = {"sp500": sp500_tickers, "coin50": coin50_tickers}
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)  # Ensure directory exists
            with open(self.output_path, "w") as file:
                json.dump(tickers, file, indent=4)
            logger.info("Updated tickers and saved to %s.", self.output_path)

            # Publish a message to notify completion
            self.redis_stream.publish(self.channel, {"message": "Ticker update completed."})
            logger.info("Published completion message to stream '%s'.", self.channel)
        except Exception as e:
            logger.error("Failed to update tickers: %s", str(e))