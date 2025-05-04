import numpy as np

def detect_fvgs(df, symbol, timeframe):
    """Detect Fair Value Gaps (FVGs) in the OHLCV DataFrame, with filtering."""
    fvgs = []
    if len(df) < 32:
        return fvgs  # Not enough data for 30-candle avg
    avg_height = abs(np.mean(df["open"].iloc[-31:-1] - df["close"].iloc[-31:-1]))
    current_price = df["close"].iloc[-1]
    for i in range(2, len(df)):
        n1 = df.iloc[i-2]
        n2 = df.iloc[i-1]
        n3 = df.iloc[i]
        # Bullish FVG: gap between n1 high and n3 low
        if n1["high"] < n3["low"]:
            fvg_height = n3["low"] - n1["high"]
            pct_of_price = fvg_height / current_price
            valid = (
                pct_of_price > 0.005 and
                fvg_height > 1.5 * avg_height
            )
            if valid:
                fvgs.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "direction": "bullish",
                    "fvg_start": n1["high"],
                    "fvg_end": n3["low"],
                    "formed_at": n2["timestamp"],
                    "height": fvg_height,
                    "pct_of_price": pct_of_price,
                    "avg_height": avg_height
                })
        # Bearish FVG: gap between n3 high and n1 low
        if n3["high"] < n1["low"]:
            fvg_height = n1["low"] - n3["high"]
            pct_of_price = fvg_height / current_price
            valid = (
                pct_of_price > 0.005 or
                fvg_height > 1.5 * avg_height
            )
            if valid:
                fvgs.append({
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "direction": "bearish",
                    "fvg_start": n3["high"],
                    "fvg_end": n1["low"],
                    "formed_at": n2["timestamp"],
                    "height": fvg_height,
                    "pct_of_price": pct_of_price,
                    "avg_height": avg_height
                })
    return fvgs