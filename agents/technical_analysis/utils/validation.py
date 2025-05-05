import pandas as pd
from datetime import time
import logging

logger = logging.getLogger(__name__)

def is_volume_spike(df, idx, spike_factor=2.0, window=20):
    """Check if the current candle's volume is a spike compared to rolling average."""
    if idx < window:
        return False
    avg_vol = df["volume"].iloc[idx-window:idx].mean()
    return df["volume"].iloc[idx] > avg_vol * spike_factor

def is_session_time(ts, sessions=None):
    """Check if the timestamp falls within a valid session (e.g., London/NY)."""
    # Default: London 08:00-11:00 UTC, NY 13:30-16:00 UTC
    if sessions is None:
        sessions = [
            (time(8, 0), time(11, 0)),   # London
            (time(13, 30), time(16, 0)), # NY
        ]
    t = ts.time()
    return any(start <= t <= end for start, end in sessions)

# def is_order_block_nearby(df, idx, direction, ob_window=10):
#     """Stub: Check if an order block is nearby (optional, can be expanded)."""
#     # For now, just check if a large candle body is present in the last ob_window candles
#     # This is a placeholder for more advanced OB detection
#     recent = df.iloc[max(0, idx-ob_window):idx]
#     if direction == "bullish":
#         return any((row["close"] - row["open"]) > (row["high"] - row["low"]) * 0.6 for _, row in recent.iterrows())
#     else:
#         return any((row["open"] - row["close"]) > (row["high"] - row["low"]) * 0.6 for _, row in recent.iterrows())

# def validate_signal(fvg, msb, liquidity, df, idx):
#     """
#     Validate if a trade signal meets confluence criteria:
#     - FVG inversion confirmed
#     - MSB present in same direction
#     - At least one confluence: volume spike, session, or OB
#     """
#     if not fvg or not msb:
#         return False, "Missing FVG or MSB"
#     direction = fvg["direction"]
#     ts = df["timestamp"].iloc[idx]
#     confluences = []
#     if is_volume_spike(df, idx):
#         confluences.append("volume_spike")
#     if is_session_time(ts):
#         confluences.append("session")
#     if is_order_block_nearby(df, idx, direction):
#         confluences.append("order_block")
#     if confluences:
#         return True, confluences
#     return False, "No confluence found"

def find_order_block(df, msb_candle_idx, msb_direction, lookback=15):
    """
    Attempts to identify an Order Block (OB) preceding an MSB.
    Definition: Last opposing candle before the start of the impulse leg causing MSB.

    Args:
        df (pd.DataFrame): LTF DataFrame.
        msb_candle_idx (int): Index of the candle that confirmed the MSB.
        msb_direction (str): 'bullish' or 'bearish' direction of the MSB.
        lookback (int): How many candles to look back from MSB for the impulse/OB.

    Returns:
        dict: Dictionary representing the OB candle (iloc data), or None if not found.
    """
    if msb_candle_idx < 1: # Need at least one candle before MSB
        return None

    start_scan_idx = max(0, msb_candle_idx - lookback)
    scan_df = df.iloc[start_scan_idx:msb_candle_idx] # Look at candles BEFORE the MSB confirmation

    if scan_df.empty:
        return None

    # Find the last candle opposing the MSB direction within the scan window
    ob = None
    if msb_direction == 'bullish': # Look for the last bearish candle (close < open)
        opposing_candles = scan_df[scan_df['close'] < scan_df['open']]
        if not opposing_candles.empty:
            ob = opposing_candles.iloc[-1] # Last bearish candle
    elif msb_direction == 'bearish': # Look for the last bullish candle (close > open)
        opposing_candles = scan_df[scan_df['close'] > scan_df['open']]
        if not opposing_candles.empty:
            ob = opposing_candles.iloc[-1] # Last bullish candle

    # Basic validation: Was the MSB level close to the OB's range? (Optional refinement)
    # More complex: Did the impulse leg originate clearly after this OB?

    return ob.to_dict() if ob is not None else None


# Modified validate_signal to use the new OB detection
def validate_signal(fvg, msb, df, idx): # Removed unused 'liquidity' argument
    """
    Validate if a trade signal meets confluence criteria.
    Now includes a check for a preceding Order Block.
    """
    if not fvg or not msb:
        logger.warning("Validation failed: Missing FVG or MSB.")
        return False, ["Missing FVG or MSB"] # Return reason

    # Determine the TRADE direction (opposite of FVG for inverse strategy)
    # Note: MSB direction should ALIGN with trade direction
    if fvg["direction"] == "bullish":
        trade_direction = "bearish"
    elif fvg["direction"] == "bearish":
        trade_direction = "bullish"
    else:
         logger.error(f"Invalid FVG direction: {fvg.get('direction')}")
         return False, ["Invalid FVG direction"]

    # Ensure MSB direction matches the required trade direction
    if msb['direction'] != trade_direction:
         logger.warning(f"Validation failed: MSB direction ({msb['direction']}) mismatch with required trade direction ({trade_direction}) for FVG {fvg.get('id')}")
         return False, ["MSB direction mismatch"]

    ts = df["timestamp"].iloc[idx] # Timestamp of the inversion candle
    msb_confirm_idx = df.index[df['timestamp'] == msb['timestamp']].tolist()
    if not msb_confirm_idx:
         logger.error(f"Could not find MSB confirmation index for timestamp {msb['timestamp']}")
         return False, ["MSB index not found"]
    msb_confirm_idx = msb_confirm_idx[0]

    confluences = []
    # Check Volume Spike at the inversion candle index 'idx'
    if is_volume_spike(df, idx):
        confluences.append("volume_spike")
    # Check Session Time at the inversion candle timestamp 'ts'
    if is_session_time(ts):
        confluences.append("session")
    # Check for Order Block preceding the MSB confirmation candle
    order_block = find_order_block(df, msb_confirm_idx, msb['direction'])
    if order_block:
        confluences.append("order_block")
        # Optionally log OB details: logger.info(f"Found potential OB: {order_block}")

    # Strategy requires MSB + *at least one* confluence factor
    if confluences:
        logger.info(f"Signal validated for FVG {fvg.get('id')} with confluences: {confluences}")
        return True, confluences

    logger.info(f"Signal validation failed for FVG {fvg.get('id')}: No confluence factors found.")
    return False, ["No confluence found"]

# IMPORTANT: Update the call in technical_analysis_agent.py:
# OLD: is_valid, confluences = validate_signal(fvg, msb, valid_liquidity, ltf_df, idx)
# NEW: is_valid, confluences = validate_signal(fvg, msb, ltf_df, idx) # Removed valid_liquidity