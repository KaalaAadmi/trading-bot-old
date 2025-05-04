import logging
import asyncio

from core.config.config_loader import load_settings
from core.redis_bus.redis_stream import RedisStream
from sqlalchemy.ext.asyncio import create_async_engine
from agents.technical_analysis.utils.data_loader import load_ohlcv_window
from agents.technical_analysis.logic.fvg_detector import detect_fvgs
from sqlalchemy.sql import text
from agents.technical_analysis.logic.liquidity_tracker import detect_liquidity
import numpy as np
from agents.technical_analysis.logic.msb_detector import detect_msbs
import json
from agents.common.utils import convert_decimals, db_fvg_to_logic_fvg


logger=logging.getLogger("agents.technical_analysis")

class TechnicalAnalysisAgent:
    def __init__(self, settings_path=None):
        self.settings = load_settings(settings_path)
        self.redis_stream = RedisStream()
        self.data_channel = self.redis_stream.get_channel("data_collector")
        self.signal_channel = self.redis_stream.get_channel("technical_analysis")
        db_cfg = self.settings["database"]
        self.db_engine = create_async_engine(
            f"postgresql+asyncpg://{db_cfg['user']}:{db_cfg['password']}@{db_cfg['host']}:{db_cfg['port']}/{db_cfg['db']}"
        )
        self.timeframes = self.settings["timeframes"]
        self.history = self.settings["history"]
        self._semaphore = None  # Placeholder
        self._loop = None  # Track the loop this agent is tied to

    @property
    def semaphore(self):
        """Ensure semaphore is used within the correct event loop."""
        current_loop = asyncio.get_running_loop()
        if self._semaphore is None:
            raise RuntimeError("Semaphore is not initialized. Call 'start' method first.")
        if current_loop != self._loop:
            raise RuntimeError("Semaphore is bound to a different event loop.")
        return self._semaphore
    
    async def start(self):
        """Start the agent and initialize the semaphore."""
        logger.info("Starting Technical Analysis Agent...")
        
        # Initialize the semaphore on the correct event loop
        self._loop = asyncio.get_running_loop()
        self._semaphore = asyncio.Semaphore(10)
        
        self.redis_stream.subscribe(self.data_channel,self.process_new_data,consumer_group="ta_group",consumer_name="ta_consumer")
        
        # Keep the agent running
        while True:
            await asyncio.sleep(1)
    
    async def process_new_data(self,message):
        """Process new data from the data collector agent."""
        try:
            logger.info("Received new data: %s", message)
            ticker = message["ticker"]
            
            # Detect and persist new HTF FVGs
            htf=self.timeframes["htf"]
            htf_lookback=self.history["htf_lookback_days"]
            htf_df=await load_ohlcv_window(self.db_engine,ticker,htf,htf_lookback)
            if htf_df is None or htf_df.empty:
                logger.warning("No data found for %s on %s", ticker, htf)
                return
            
            htf_fvgs=await detect_fvgs(htf_df,ticker,htf)
            await self.persist_new_fvgs(ticker,htf,htf_fvgs)
            
            # Load LTF data for further processing
            ltf=self.timeframes["ltf"]
            ltf_lookback=self.history["ltf_lookback_days"]
            ltf_df=await load_ohlcv_window(self.db_engine,ticker,ltf,ltf_lookback)
            if ltf_df is None or ltf_df.empty:
                logger.warning("No data found for %s on %s", ticker, ltf)
                return
            
            # Detect liquidity levels
            liquidity=await detect_liquidity(ltf_df,ticker,ltf)
            # Validate liquidity levels
            valid_liquidity = []
            for liq in liquidity:
                if not isinstance(liq, dict) or "level" not in liq or "type" not in liq:
                    logger.warning("Skipping invalid liquidity: %s", liq)
                    continue
                if not isinstance(liq["level"], (float, int, np.float64)):
                    continue
                liq["level"] = float(liq["level"])
                valid_liquidity.append(liq)

            if not valid_liquidity:
                logger.warning("No valid liquidity levels found for %s", ticker)
                return
            
            liquidity = valid_liquidity
            
            # Check if liquidity was tapped
            for liq in valid_liquidity:
                ltf_after_formed = ltf_df[ltf_df["timestamp"] > liq["formed_at"]]
                if ltf_after_formed.empty:
                    liq.update({"tapped": False, "tap_time": None})
                    continue

                if liq["type"] == "sell-side" and ltf_after_formed["high"].max() >= liq["level"]:
                    liq.update({"tapped": True, "tap_time": ltf_after_formed["timestamp"].iloc[-1]})
                elif liq["type"] == "buy-side" and ltf_after_formed["low"].min() <= liq["level"]:
                    liq.update({"tapped": True, "tap_time": ltf_after_formed["timestamp"].iloc[-1]})
                else:
                    liq.update({"tapped": False, "tap_time": None})

            await self.persist_liquidity(ticker, ltf, valid_liquidity)
            
            # Process pending FVGs
            pending_fvgs=await self.get_pending_fvgs(ticker, ltf)
            msbs=detect_msbs(ltf_df,ticker,ltf)
            logger.info("Detected MSBs: %s", msbs)
            for fvg in pending_fvgs:
                # Filter LTF data within HTF FVG boundaries and after FVG formation
                ltf_inside_fvg = ltf_df[
                    (ltf_df["low"] >= fvg["fvg_start"]) &
                    (ltf_df["high"] <= fvg["fvg_end"]) &
                    (ltf_df["timestamp"] >= fvg["formed_at"])  # Ensure LTF candles are after FVG formation
                ]

                if ltf_inside_fvg.empty:
                    logger.warning("No LTF candles inside FVG %s (%s) after its formation", fvg["id"], fvg["timeframe"])
                    return  # Skip this FVG
                
                for idx in ltf_inside_fvg.index:
                    if self.is_inversion(ltf_df,idx,fvg):
                        current_price=ltf_df["close"].iloc[:-1]
                        buffer=0.005*current_price
                        candle_buffer=10
                        current_idx=ltf_df["timestamp"].iloc[idx]
                        start_idx,end_idx=max(0,current_idx-candle_buffer),min(len(ltf_df)-1,current_idx+candle_buffer)
                        start_ts,end_ts=ltf_df["timestamp"].iloc[start_idx],ltf_df["timestamp"].iloc[end_idx]
                        
                        msb=next(
                            (msb for m in msbs if m["direction"]!=fvg["direction"])
                        )
            
            
        except Exception as e:
            logger.error("Error processing new data: %s", e)
            return 
        
    async def persist_new_fvgs(self, symbol, timeframe, fvgs):
        async with self.db_engine.begin() as conn:
            for fvg in fvgs:
                # Only insert if not already present (by unique formed_at, high, low, direction)
                result = await conn.execute(
                    text("""
                        SELECT id FROM tracked_fvgs
                        WHERE symbol=:symbol AND timeframe=:timeframe AND direction=:direction
                        AND high=:high AND low=:low AND formed_at=:formed_at
                    """),
                    {
                        "symbol": symbol, "timeframe": timeframe, "direction": fvg["direction"],
                        "high": fvg["fvg_start"], "low": fvg["fvg_end"], "formed_at": fvg["formed_at"]
                    }
                )
                if not result.fetchone():
                    await conn.execute(
                        text("""
                            INSERT INTO tracked_fvgs
                            (symbol, timeframe, direction, high, low, formed_at, status, confirmed, msb_confirmed, fvg_height, pct_of_price, avg_height, last_checked)
                            VALUES (:symbol, :timeframe, :direction, :high, :low, :formed_at, 'pending', FALSE, FALSE, :fvg_height, :pct_of_price, :avg_height, NOW())
                        """),
                        {
                            "symbol": symbol, "timeframe": timeframe, "direction": fvg["direction"],
                            "high": fvg["fvg_start"], "low": fvg["fvg_end"], "formed_at": fvg["formed_at"],
                            "fvg_height": fvg.get("height"), "pct_of_price": fvg.get("pct_of_price"), "avg_height": fvg.get("avg_height")
                        }
                    )

    async def persist_liquidity(self, symbol, timeframe, liquidity):
        async with self.db_engine.begin() as conn:
            for liq in liquidity:
                # logger.info("Persisting liq
                # uidity: %s", liq)
                if not isinstance(liq, dict):
                    logger.warning("Malformed liquidity entry (not a dict): %s", liq)
                    continue
                if "level" not in liq or "formed_at" not in liq:
                    logger.warning("Skipping liquidity without level or formed_at: %s", liq)
                    continue
                # Only insert if not already present (by formed_at, level, type)
                result = await conn.execute(
                    text("""
                        SELECT id FROM tracked_liquidity
                        WHERE symbol=:symbol AND timeframe=:timeframe AND type=:type
                        AND level=:level AND formed_at=:formed_at
                    """),
                    {
                        "symbol": symbol, "timeframe": timeframe, "type": liq["type"],
                        "level": liq["level"], "formed_at": liq["formed_at"]
                    }
                )
                if not result.fetchone():
                    await conn.execute(
                        text("""
                            INSERT INTO tracked_liquidity
                            (symbol, timeframe, type, level, formed_at, tapped, equal_highs, metadata)
                            VALUES (:symbol, :timeframe, :type, :level, :formed_at, FALSE, :equal_highs, :metadata)
                        """),
                        {
                            "symbol": symbol, "timeframe": timeframe, "type": liq["type"],
                            "level": liq["level"], "formed_at": liq["formed_at"],
                            "equal_highs": liq.get("equal_highs", False), "metadata": json.dumps(convert_decimals(liq))
                        }
                    )

    async def get_pending_fvgs(self, symbol, timeframe):
        async with self.db_engine.connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT * FROM tracked_fvgs
                    WHERE symbol=:symbol AND timeframe=:timeframe AND status='pending'
                """),
                {"symbol": symbol, "timeframe": timeframe}
            )
            rows = result.mappings().all()
            # Convert SQLAlchemy Row objects to dicts
            return [db_fvg_to_logic_fvg(convert_decimals(row)) for row in rows]
