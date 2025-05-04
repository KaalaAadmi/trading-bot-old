import pandas as pd
from datetime import time

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

def is_order_block_nearby(df, idx, direction, ob_window=10):
    """Stub: Check if an order block is nearby (optional, can be expanded)."""
    # For now, just check if a large candle body is present in the last ob_window candles
    # This is a placeholder for more advanced OB detection
    recent = df.iloc[max(0, idx-ob_window):idx]
    if direction == "bullish":
        return any((row["close"] - row["open"]) > (row["high"] - row["low"]) * 0.6 for _, row in recent.iterrows())
    else:
        return any((row["open"] - row["close"]) > (row["high"] - row["low"]) * 0.6 for _, row in recent.iterrows())

def validate_signal(fvg, msb, liquidity, df, idx):
    """
    Validate if a trade signal meets confluence criteria:
    - FVG inversion confirmed
    - MSB present in same direction
    - At least one confluence: volume spike, session, or OB
    """
    if not fvg or not msb:
        return False, "Missing FVG or MSB"
    direction = fvg["direction"]
    ts = df["timestamp"].iloc[idx]
    confluences = []
    if is_volume_spike(df, idx):
        confluences.append("volume_spike")
    if is_session_time(ts):
        confluences.append("session")
    if is_order_block_nearby(df, idx, direction):
        confluences.append("order_block")
    if confluences:
        return True, confluences
    return False, "No confluence found"