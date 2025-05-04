import pandas as pd # Ensure pandas is imported if not already

def detect_msbs(df, symbol, timeframe, window=20):
    """
    Detect Market Structure Breaks (MSBs) in the OHLCV DataFrame.
    An MSB is confirmed when the *close* price breaks the high/low of a recent window.
    Includes the price level of the broken structure.
    """
    msbs = []
    if len(df) <= window: # Need enough data for the window + current candle
        return msbs

    for i in range(window, len(df)):
        # Define the window for finding the high/low *before* the current candle
        highs = df["high"].iloc[i-window:i]
        lows = df["low"].iloc[i-window:i]

        # Check for potential breaks on the current candle (index i)
        # Using close price for break confirmation is generally more robust
        current_close = df["close"].iloc[i]
        current_timestamp = df["timestamp"].iloc[i]

        # Potential Bullish MSB: Current close is above the highest high in the lookback window
        if not highs.empty: # Ensure highs series is not empty
            previous_high_level = highs.max()
            if current_close > previous_high_level:
                msbs.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "direction": "bullish",
                    "timestamp": current_timestamp,
                    "level": float(previous_high_level) # Add the broken high level
                })

        # Potential Bearish MSB: Current close is below the lowest low in the lookback window
        if not lows.empty: # Ensure lows series is not empty
            previous_low_level = lows.min()
            if current_close < previous_low_level:
                msbs.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "direction": "bearish",
                    "timestamp": current_timestamp,
                    "level": float(previous_low_level) # Add the broken low level
                })

    # Optional: Add logic here to filter consecutive MSBs if needed
    # (e.g., only keep the first break in a sequence)

    return msbs