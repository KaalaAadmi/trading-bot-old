import logging

logger = logging.getLogger("agents.technical_analysis.liquidity_tracker")

def detect_liquidity(df, symbol, timeframe, window=20):
    """Detect liquidity zones (swing highs/lows, equal highs/lows)."""
    liquidity = []
    # for i in range(window, len(df)):
    #     window_highs = df["high"].iloc[i-window:i]
    #     window_lows = df["low"].iloc[i-window:i]
    #     if df["high"].iloc[i] == window_highs.max():
    #         liquidity.append({
    #             "symbol": symbol,
    #             "timeframe": timeframe,
    #             "type": "sell-side",
    #             "level": df["high"].iloc[i],
    #             "formed_at": df["timestamp"].iloc[i]
    #         })
    #     if df["low"].iloc[i] == window_lows.min():
    #         liquidity.append({
    #             "symbol": symbol,
    #             "timeframe": timeframe,
    #             "type": "buy-side",
    #             "level": df["low"].iloc[i],
    #             "formed_at": df["timestamp"].iloc[i]
    #         })
    if len(df) < 3:
        logger.warning("Insufficient data for liquidity detection: %s rows", len(df))
        return []
    for i in range(1, len(df) - 1):
        if df["high"].iloc[i] > df["high"].iloc[i - 1] and df["high"].iloc[i] > df["high"].iloc[i + 1]:
            liquidity.append({
                "type": "sell-side",
                "level": df["high"].iloc[i],
                "formed_at": df["timestamp"].iloc[i]
            })
        if df["low"].iloc[i] < df["low"].iloc[i - 1] and df["low"].iloc[i] < df["low"].iloc[i + 1]:
            liquidity.append({
                "type": "buy-side",
                "level": df["low"].iloc[i],
                "formed_at": df["timestamp"].iloc[i]
            })
    # logger.info("Detected liquidity levels for %s (%s): %s", symbol, timeframe, liquidity)
    return liquidity