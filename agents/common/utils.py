import requests
import holidays
from datetime import datetime, time
import yfinance as yf
import logging
from decimal import Decimal
import pandas as pd
import json

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

def convert_decimals(obj):
    if isinstance(obj, list):
        return json.dumps([convert_decimals(i) for i in obj])
        # return json.dumps(obj)
    elif isinstance(obj, dict):
        return {k: convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)
    elif hasattr(obj, 'isoformat'):  # Handles pandas.Timestamp, datetime, etc.
        return obj.isoformat()
    elif obj is None:
        return "null"
    else:
        return obj

def db_fvg_to_logic_fvg(db_fvg):
    direction = db_fvg["direction"]
    high = float(db_fvg["high"]) if isinstance(db_fvg["high"], Decimal) else db_fvg["high"]
    low = float(db_fvg["low"]) if isinstance(db_fvg["low"], Decimal) else db_fvg["low"]
    return {
        "id": db_fvg["id"],
        "symbol": db_fvg["symbol"],
        "timeframe": db_fvg["timeframe"],
        "direction": direction,
        "fvg_start": high if direction == "bullish" else low,
        "fvg_end": low if direction == "bullish" else high,
        "formed_at": db_fvg["formed_at"],
        "height": float(db_fvg.get("fvg_height", 0)) if db_fvg.get("fvg_height") is not None else None,
        "pct_of_price": float(db_fvg.get("pct_of_price", 0)) if db_fvg.get("pct_of_price") is not None else None,
        "avg_height": float(db_fvg.get("avg_height", 0)) if db_fvg.get("avg_height") is not None else None,
        # ...other fields as needed
    }
