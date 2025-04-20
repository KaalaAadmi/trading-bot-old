import requests
import holidays
from datetime import datetime, time
import yfinance as yf
import logging

logger = logging.getLogger("agents.common.utils")

def is_public_holiday():
    us_holidays = holidays.US()  # Use IN() for India, or combine both if needed
    today = datetime.now().date()
    return today in us_holidays

def is_weekend_or_holiday():
    today = datetime.now().date()
    return today.weekday() >= 5 or is_public_holiday()

def is_market_open():
    now = datetime.now().time()
    market_open = time(9, 15)  # Example: 9:15 AM
    market_close = time(16, 15)  # Example: 4:15 PM
    return market_open <= now <= market_close

# def get_usd_to_eur_rate():
#     response = requests.get("https://api.exchangerate.host/latest?base=USD&symbols=EUR")
#     rate = response.json()["rates"]["EUR"]
#     return rate

def get_usd_to_eur_rate():
    """Fetch the current USD to EUR exchange rate."""
    try:
        ticker = yf.Ticker("EUR=X")  # USD/EUR exchange rate
        df = ticker.history(period="1d", interval="1d")
        if not df.empty:
            exchange_rate = df["Close"].iloc[-1]  
            logger.info("Fetched USD to EUR exchange rate: %.4f", exchange_rate)
            return exchange_rate
        else:
            logger.error("Failed to fetch USD to EUR exchange rate. Defaulting to 1.0.")
            return 1.0  # Default to no conversion if rate is unavailable
    except Exception as e:
        logger.error("Error fetching USD to EUR exchange rate: %s", str(e))
        return 1.0  # Default to no conversion if an error occurs
    