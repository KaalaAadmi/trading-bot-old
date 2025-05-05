# import pandas as pd # Ensure pandas is imported if not already

# def detect_msbs(df, symbol, timeframe, window=20):
#     """
#     Detect Market Structure Breaks (MSBs) in the OHLCV DataFrame.
#     An MSB is confirmed when the *close* price breaks the high/low of a recent window.
#     Includes the price level of the broken structure.
#     """
#     msbs = []
#     if len(df) <= window: # Need enough data for the window + current candle
#         return msbs

#     for i in range(window, len(df)):
#         # Define the window for finding the high/low *before* the current candle
#         highs = df["high"].iloc[i-window:i]
#         lows = df["low"].iloc[i-window:i]

#         # Check for potential breaks on the current candle (index i)
#         # Using close price for break confirmation is generally more robust
#         current_close = df["close"].iloc[i]
#         current_timestamp = df["timestamp"].iloc[i]

#         # Potential Bullish MSB: Current close is above the highest high in the lookback window
#         if not highs.empty: # Ensure highs series is not empty
#             previous_high_level = highs.max()
#             if current_close > previous_high_level:
#                 msbs.append({
#                     "symbol": symbol,
#                     "timeframe": timeframe,
#                     "direction": "bullish",
#                     "timestamp": current_timestamp,
#                     "level": float(previous_high_level) # Add the broken high level
#                 })

#         # Potential Bearish MSB: Current close is below the lowest low in the lookback window
#         if not lows.empty: # Ensure lows series is not empty
#             previous_low_level = lows.min()
#             if current_close < previous_low_level:
#                 msbs.append({
#                     "symbol": symbol,
#                     "timeframe": timeframe,
#                     "direction": "bearish",
#                     "timestamp": current_timestamp,
#                     "level": float(previous_low_level) # Add the broken low level
#                 })

#     # Optional: Add logic here to filter consecutive MSBs if needed
#     # (e.g., only keep the first break in a sequence)

#     return msbs

# agents/technical_analysis/logic/msb_detector.py
import pandas as pd
import numpy as np
from scipy.signal import find_peaks
import logging

logger = logging.getLogger(__name__)

def detect_swing_points(df, order=5, col='close'):
    """
    Detect swing high and low points using scipy.find_peaks.

    Args:
        df (pd.DataFrame): OHLCV DataFrame.
        order (int): How many candles on each side need to be lower/higher for a peak/trough.
        col (str): Column to use for peak/trough detection ('high' for highs, 'low' for lows).

    Returns:
        pd.Index: Index locations of the detected swing points.
    """
    # Ensure the column exists
    if col not in df.columns:
        logger.error(f"Column '{col}' not found in DataFrame for swing point detection.")
        return pd.Index([])

    data = df[col].values
    # find_peaks finds maxima. For lows, we find peaks on the negative series.
    multiplier = 1 if col == 'high' else -1
    try:
        # Prominence can help filter minor peaks; adjust as needed
        peaks, properties = find_peaks(multiplier * data, distance=order, prominence=np.std(data)*0.1) # Example prominence filter
        return df.index[peaks]
    except Exception as e:
        logger.error(f"Error during find_peaks for col '{col}': {e}")
        return pd.Index([])


def detect_msbs_swing(df, symbol, timeframe, swing_order=5):
    """
    Detect Market Structure Breaks (MSBs) based on significant swing points.
    MSB confirmed when price CLOSES beyond the last relevant confirmed swing point.
    """
    msbs = []
    required_cols = ['open', 'high', 'low', 'close', 'timestamp']
    if not all(col in df.columns for col in required_cols):
        logger.error(f"[{symbol}/{timeframe}] DataFrame missing required columns for MSB detection.")
        return msbs
    if len(df) < swing_order * 2 + 1: # Need enough data for swing points
        return msbs

    # Detect swing highs and lows
    swing_high_indices = detect_swing_points(df, order=swing_order, col='high')
    swing_low_indices = detect_swing_points(df, order=swing_order, col='low')

    # Convert indices to timestamps for easier comparison, store level
    swing_highs = df.loc[swing_high_indices, ['timestamp', 'high']].rename(columns={'high': 'level'}).to_dict('records')
    swing_lows = df.loc[swing_low_indices, ['timestamp', 'low']].rename(columns={'low': 'level'}).to_dict('records')

    # Sort swings by timestamp
    swing_highs.sort(key=lambda x: x['timestamp'])
    swing_lows.sort(key=lambda x: x['timestamp'])

    last_confirmed_sh = None
    last_confirmed_sl = None

    # --- Iterate through candles to check for breaks of confirmed swings ---
    # We need a concept of 'confirmed' swings (e.g., price moved away significantly after forming)
    # For simplicity here, we'll consider the *most recent* swing high/low before the current candle
    # A more robust approach would track sequences of higher highs/lows etc.

    for i in range(swing_order, len(df)): # Start after first potential swing
        current_candle = df.iloc[i]
        current_close = current_candle["close"]
        current_ts = current_candle["timestamp"]

        # Find the most recent swing high *before* the current candle
        relevant_sh = None
        for sh in reversed(swing_highs):
            if sh['timestamp'] < current_ts:
                relevant_sh = sh
                break

        # Find the most recent swing low *before* the current candle
        relevant_sl = None
        for sl in reversed(swing_lows):
            if sl['timestamp'] < current_ts:
                relevant_sl = sl
                break

        # Check for Bullish MSB (close breaks above relevant Swing High)
        if relevant_sh and current_close > relevant_sh['level']:
            # Avoid duplicate signals if price stays above for multiple candles
            # Check if the *previous* MSB signal was also bullish and broke the same level
            is_new_break = True
            if msbs:
                last_msb = msbs[-1]
                if last_msb['direction'] == 'bullish' and last_msb['broken_level'] == relevant_sh['level']:
                     is_new_break = False # Not a new break of this specific level

            if is_new_break:
                msbs.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "direction": "bullish",
                    "timestamp": current_ts, # Timestamp of the breaking candle
                    "level": float(current_close), # Level of the close that broke structure
                    "broken_level": float(relevant_sh['level']), # The actual swing level that was broken
                    "broken_level_ts": relevant_sh['timestamp'] # Timestamp of the swing point broken
                })

        # Check for Bearish MSB (close breaks below relevant Swing Low)
        if relevant_sl and current_close < relevant_sl['level']:
            # Avoid duplicate signals
            is_new_break = True
            if msbs:
                last_msb = msbs[-1]
                if last_msb['direction'] == 'bearish' and last_msb['broken_level'] == relevant_sl['level']:
                    is_new_break = False

            if is_new_break:
                msbs.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "direction": "bearish",
                    "timestamp": current_ts,
                    "level": float(current_close),
                    "broken_level": float(relevant_sl['level']),
                    "broken_level_ts": relevant_sl['timestamp']
                })

    # Note: This simplified version doesn't differentiate internal/external structure.
    # It focuses on breaking the *most recent* swing high/low.
    logger.info(f"[{symbol}/{timeframe}] Detected {len(msbs)} MSBs using swing points (order={swing_order}).")
    return msbs

# IMPORTANT: Replace the call in technical_analysis_agent.py:
# OLD: msbs = detect_msbs(ltf_df, ticker, ltf)
# NEW: msbs = detect_msbs_swing(ltf_df, ticker, ltf, swing_order=5) # Adjust swing_order as needed

# ALSO IMPORTANT: The agent code now needs to use `m["broken_level"]` where it previously used `m["level"]`
# for checking if the break happened within the FVG price range.
# The 'level' key in the new MSB dict now refers to the closing price of the breaking candle.
# CHANGE THIS LINE in process_new_data:
# OLD: (fvg["fvg_start"] - buffer) <= m["level"] <= (fvg["fvg_end"] + buffer)),
# NEW: (fvg["fvg_start"] - buffer) <= m["broken_level"] <= (fvg["fvg_end"] + buffer)),