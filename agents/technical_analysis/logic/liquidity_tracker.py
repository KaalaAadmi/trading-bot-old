# import logging

# logger = logging.getLogger("agents.technical_analysis.liquidity_tracker")

# def detect_liquidity(df, symbol, timeframe, window=20):
#     """Detect liquidity zones (swing highs/lows, equal highs/lows)."""
#     liquidity = []
#     if len(df) < 3:
#         logger.warning("Insufficient data for liquidity detection: %s rows", len(df))
#         return []
#     for i in range(1, len(df) - 1):
#         if df["high"].iloc[i] > df["high"].iloc[i - 1] and df["high"].iloc[i] > df["high"].iloc[i + 1]:
#             liquidity.append({
#                 "type": "sell-side",
#                 "level": df["high"].iloc[i],
#                 "formed_at": df["timestamp"].iloc[i]
#             })
#         if df["low"].iloc[i] < df["low"].iloc[i - 1] and df["low"].iloc[i] < df["low"].iloc[i + 1]:
#             liquidity.append({
#                 "type": "buy-side",
#                 "level": df["low"].iloc[i],
#                 "formed_at": df["timestamp"].iloc[i]
#             })
#     # logger.info("Detected liquidity levels for %s (%s): %s", symbol, timeframe, liquidity)
#     return liquidity

# agents/technical_analysis/logic/liquidity_tracker.py
import pandas as pd
import numpy as np
from .msb_detector import detect_swing_points # Reuse swing point logic
import logging

logger = logging.getLogger(__name__)

def detect_liquidity_swing(df, symbol, timeframe, swing_order=5, tolerance_factor=0.001):
    """
    Detect liquidity pools based on significant swing points and equal highs/lows.

    Args:
        df (pd.DataFrame): OHLCV DataFrame.
        symbol (str): Trading symbol.
        timeframe (str): Timeframe identifier.
        swing_order (int): Order for swing point detection.
        tolerance_factor (float): Tolerance (as % of price) for considering levels "equal".

    Returns:
        list: List of liquidity pool dictionaries.
    """
    liquidity_pools = []
    required_cols = ['open', 'high', 'low', 'close', 'timestamp']
    if not all(col in df.columns for col in required_cols):
        logger.error(f"[{symbol}/{timeframe}] DataFrame missing required columns for liquidity detection.")
        return liquidity_pools
    if len(df) < swing_order * 2 + 1:
        return liquidity_pools

    # Detect swing highs and lows
    swing_high_indices = detect_swing_points(df, order=swing_order, col='high')
    swing_low_indices = detect_swing_points(df, order=swing_order, col='low')

    swing_highs = df.loc[swing_high_indices, ['timestamp', 'high']].rename(columns={'high': 'level'})
    swing_lows = df.loc[swing_low_indices, ['timestamp', 'low']].rename(columns={'low': 'level'})

    # 1. Add individual significant swings as liquidity
    for idx, row in swing_highs.iterrows():
        liquidity_pools.append({
            "symbol": symbol, "timeframe": timeframe,
            "type": "sell-side", "level": float(row['level']),
            "formed_at": row['timestamp'], "significance": "significant_swing",
            "touches": 1
        })
    for idx, row in swing_lows.iterrows():
         liquidity_pools.append({
            "symbol": symbol, "timeframe": timeframe,
            "type": "buy-side", "level": float(row['level']),
            "formed_at": row['timestamp'], "significance": "significant_swing",
            "touches": 1
        })

    # 2. Detect Equal Highs/Lows (simple clustering approach)
    swing_highs = swing_highs.sort_values(by='level')
    swing_lows = swing_lows.sort_values(by='level')

    processed_indices_high = set()
    for i in range(len(swing_highs)):
        if i in processed_indices_high:
            continue
        current_level = swing_highs.iloc[i]['level']
        current_ts = swing_highs.iloc[i]['timestamp']
        tolerance = current_level * tolerance_factor
        # Find other highs within tolerance
        cluster_indices = swing_highs[abs(swing_highs['level'] - current_level) <= tolerance].index
        if len(cluster_indices) > 1: # Found equal highs
            cluster_levels = swing_highs.loc[cluster_indices, 'level']
            avg_level = cluster_levels.mean()
            last_touch_ts = swing_highs.loc[cluster_indices, 'timestamp'].max()
            liquidity_pools.append({
                "symbol": symbol, "timeframe": timeframe,
                "type": "sell-side", "level": float(avg_level),
                "formed_at": last_touch_ts, # Timestamp of the last touch forming the pool
                "significance": "equal_highs",
                "touches": len(cluster_indices)
            })
            processed_indices_high.update(cluster_indices) # Mark these as processed

    processed_indices_low = set()
    for i in range(len(swing_lows)):
        if i in processed_indices_low:
            continue
        current_level = swing_lows.iloc[i]['level']
        current_ts = swing_lows.iloc[i]['timestamp']
        tolerance = current_level * tolerance_factor
        cluster_indices = swing_lows[abs(swing_lows['level'] - current_level) <= tolerance].index
        if len(cluster_indices) > 1:
            cluster_levels = swing_lows.loc[cluster_indices, 'level']
            avg_level = cluster_levels.mean()
            last_touch_ts = swing_lows.loc[cluster_indices, 'timestamp'].max()
            liquidity_pools.append({
                "symbol": symbol, "timeframe": timeframe,
                "type": "buy-side", "level": float(avg_level),
                "formed_at": last_touch_ts,
                "significance": "equal_lows",
                "touches": len(cluster_indices)
            })
            processed_indices_low.update(cluster_indices)

    # Remove duplicates (preferring equal highs/lows if a swing falls into that cluster)
    # This is simplified; more robust duplicate handling might be needed.
    final_liquidity = []
    levels_seen = set()
    # Prioritize keeping 'equal' levels
    liquidity_pools.sort(key=lambda x: 0 if 'equal' in x['significance'] else 1)
    for pool in liquidity_pools:
        # Use a tolerance check again for adding to final list
        is_duplicate = False
        for seen_level, seen_type in levels_seen:
             if pool['type'] == seen_type and abs(pool['level'] - seen_level) <= (pool['level'] * tolerance_factor * 2): # Wider tolerance for filtering
                 is_duplicate = True
                 break
        if not is_duplicate:
             final_liquidity.append(pool)
             levels_seen.add((pool['level'], pool['type']))


    logger.info(f"[{symbol}/{timeframe}] Detected {len(final_liquidity)} liquidity pools using swing points.")
    return final_liquidity


# IMPORTANT: Replace the call in technical_analysis_agent.py:
# OLD: liquidity = detect_liquidity(ltf_df, ticker, ltf)
# NEW: liquidity = detect_liquidity_swing(ltf_df, ticker, ltf, swing_order=5, tolerance_factor=0.001) # Adjust params