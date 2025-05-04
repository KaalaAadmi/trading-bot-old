import pandas as pd
from sqlalchemy.sql import text
from agents.common.utils import convert_decimals, db_fvg_to_logic_fvg

async def load_ohlcv_window(db_engine, symbol, timeframe, lookback_days):
    """Load a window of OHLCV data for a symbol/timeframe from TimescaleDB."""
    async with db_engine.connect() as conn:
        # Build the interval string in Python
        interval_str = f"{int(lookback_days)} days"
        result = await conn.execute(
            text(f"""
                SELECT timestamp, open, high, low, close, volume
                FROM ohlcv_data
                WHERE symbol = :symbol AND timeframe = :timeframe
                  AND timestamp >= NOW() - INTERVAL '{interval_str}'
                ORDER BY timestamp ASC
            """),
            {"symbol": symbol, "timeframe": timeframe}
        )
        rows = result.fetchall()
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = df[col].astype(float)
        return df