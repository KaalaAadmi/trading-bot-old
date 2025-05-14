import numpy as np
import pandas as pd
try:
    import pandas_ta as ta
except ImportError:
    print("Error: pandas_ta library not found. Please install it: pip install pandas_ta")
    ta = None
import logging # Added logging

logger = logging.getLogger(__name__) # Use logger for warnings/errors

def detect_significant_fvgs_atr(df, symbol, timeframe, atr_period=14, atr_multiplier=0.8, min_pct_price=0.003):
    """
    Detect Fair Value Gaps (FVGs) filtering by ATR and minimum percentage of price.
    Requires df to have 'open', 'high', 'low', 'close', 'timestamp' columns.

    Args:
        df (pd.DataFrame): OHLCV DataFrame.
        symbol (str): Trading symbol.
        timeframe (str): Timeframe identifier.
        atr_period (int): Period for ATR calculation.
        atr_multiplier (float): FVG height must be > atr_multiplier * ATR. Tune this value.
        min_pct_price (float): FVG height must be > min_pct_price of the current price.

    Returns:
        list: List of significant FVG dictionaries.
    """
    fvgs = []
    if ta is None:
        logger.error("pandas_ta library is required but not installed.")
        return fvgs

    required_cols = ['open', 'high', 'low', 'close', 'timestamp']
    if not all(col in df.columns for col in required_cols):
        logger.error(f"DataFrame missing required columns. Found: {df.columns.tolist()}. Required: {required_cols}")
        return fvgs

    if len(df) < atr_period + 2: # Need enough data for ATR calculation + FVG pattern (3 candles)
        # logger.warning(f"[{symbol}/{timeframe}] Insufficient data for ATR({atr_period}) + FVG detection: {len(df)} rows")
        return fvgs

    # Calculate ATR using pandas_ta
    atr_col_name = f'ATRr_{atr_period}'
    try:
        # Ensure index is DatetimeIndex for pandas_ta if needed (depends on version/usage)
        # Example: if not isinstance(df.index, pd.DatetimeIndex):
        #     df = df.set_index('timestamp', drop=False) # Keep timestamp column

        df.ta.atr(length=atr_period, append=True)
        if atr_col_name not in df.columns:
            logger.error(f"[{symbol}/{timeframe}] Failed to calculate ATR. Check input data and pandas_ta installation.")
            return fvgs
        # Handle potential NaNs in ATR calculation at the beginning
        df[atr_col_name] = df[atr_col_name].bfill() # Backfill NaNs is generally safer than ffill for volatility

    except Exception as e:
        logger.error(f"[{symbol}/{timeframe}] Error calculating ATR: {e}", exc_info=True)
        return fvgs

    # --- Loop through candles to find FVGs ---
    # range(len(df) - 3, len(df) -1): #Only check last few candles
    for i in range(2, len(df)): # Check historical candles too (adjust range if needed)
        n1 = df.iloc[i-2] # Candle before the gap
        n2 = df.iloc[i-1] # Candle where FVG is formed (timestamp reference)
        n3 = df.iloc[i] # Candle after the gap

        # Use price and ATR from the time the FVG formed (candle n2)
        price_at_formation = n2["close"]
        atr_at_formation = df[atr_col_name].iloc[i-1]

        # Skip if ATR is missing or non-positive
        if pd.isna(atr_at_formation) or atr_at_formation <= 0:
            continue

        fvg_found = False
        direction = None
        fvg_start = None
        fvg_end = None
        fvg_height = 0

        # Bullish FVG: gap between n1 high and n3 low
        if n1["high"] < n3["low"]:
            direction = "bullish"
            fvg_start = n1["high"]
            fvg_end = n3["low"]
            fvg_height = fvg_end - fvg_start
            fvg_found = True

        # Bearish FVG: gap between n3 high and n1 low
        elif n3["high"] < n1["low"]:
            direction = "bearish"
            # Note: FVG range is typically defined high-to-low, but start/end depends on direction logic elsewhere.
            # Let's keep fvg_start as the upper boundary and fvg_end as the lower boundary for consistency?
            # Or follow your original: start=high, end=low for bearish. Let's stick to your convention:
            fvg_start = n3["high"] # Upper boundary
            fvg_end = n1["low"]   # Lower boundary
            fvg_height = fvg_end - fvg_start # This will be negative if following start=high, end=low for bearish
            fvg_height = abs(fvg_height) # Use absolute height for comparison checks
            # Or more simply for bearish: fvg_height = n1["low"] - n3["high"]
            fvg_found = True


        if fvg_found:
            pct_of_price = fvg_height / price_at_formation if price_at_formation > 0 else 0

            # --- Significance Check (using AND logic) ---
            # 1. Height must be significant relative to ATR
            significant_vs_atr = fvg_height > (atr_multiplier * atr_at_formation)

            # 2. Height must meet minimum percentage of price
            significant_vs_price = pct_of_price > min_pct_price

            # Combine conditions: FVG must meet BOTH criteria
            is_significant = significant_vs_atr and significant_vs_price

            if is_significant:
                fvgs.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "direction": direction,
                    # Use original start/end based on direction for consistency with your agent logic
                    "fvg_start": n1["high"] if direction == "bullish" else n3["high"],
                    "fvg_end": n3["low"] if direction == "bullish" else n1["low"],
                    "fvg_height": fvg_height,
                    "formed_at": n2["timestamp"], # Timestamp of candle n2
                    "height": fvg_height, # Absolute height
                    "pct_of_price": pct_of_price,
                    "atr_at_formation": atr_at_formation # Store ATR value for reference/analysis
                })

    # Optional: Clean up added ATR column if df is reused elsewhere, but often not necessary
    # df.drop(columns=[atr_col_name], inplace=True, errors='ignore')

    return fvgs