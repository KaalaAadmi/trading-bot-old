import logging
import asyncio
import json
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import numpy as np

from core.config.config_loader import load_settings
from core.redis_bus.redis_stream import RedisStream
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql import text
from agents.common.utils import convert_decimals, db_fvg_to_logic_fvg
from agents.technical_analysis.utils.data_loader import load_ohlcv_window
from agents.technical_analysis.logic.fvg_detector import detect_fvgs
from agents.technical_analysis.logic.msb_detector import detect_msbs
from agents.technical_analysis.logic.liquidity_tracker import detect_liquidity
from agents.technical_analysis.utils.validation import validate_signal

logger = logging.getLogger("agents.technical_analysis")

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
        logger.info("Starting Technical Analysis Agent...")
        
        # Initialize the semaphore in the correct event loop
        self._loop = asyncio.get_running_loop()
        self._semaphore = asyncio.Semaphore(5)
        
        self.redis_stream.subscribe(
            self.data_channel,
            self.process_new_data,
            consumer_group="ta_group",
            consumer_name="ta_consumer"
        )
        # Keep the agent running
        while True:
            await asyncio.sleep(1)

    async def process_new_data(self, message):
        try:
            logger.info("Received new data event: %s", message)
            ticker = message["ticker"]
            
            trade_direction=""
            
            # 1. Detect and persist new HTF FVGs
            htf = self.timeframes["htf"]
            htf_lookback = self.history["htf_lookback_days"]
            htf_df = await load_ohlcv_window(self.db_engine, ticker, htf, htf_lookback)
            if htf_df is None or htf_df.empty:
                logger.warning("No HTF data for %s", ticker)
                return

            htf_fvgs = detect_fvgs(htf_df, ticker, htf)
            await self.persist_new_fvgs(ticker, htf, htf_fvgs)
            
            # 2. Load LTF data
            ltf = self.timeframes["ltf"]
            ltf_lookback = self.history["ltf_lookback_days"]
            ltf_df = await load_ohlcv_window(self.db_engine, ticker, ltf, ltf_lookback)
            if ltf_df is None or ltf_df.empty:
                logger.warning("No LTF data for %s", ticker)
                return

            # 3. Detect liquidity levels
            liquidity = detect_liquidity(ltf_df, ticker, ltf)

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
            pending_fvgs = await self.get_pending_fvgs(ticker, htf)
            msbs = detect_msbs(ltf_df, ticker, ltf)
            logger.info("MSBs detected: %s", msbs)

            for fvg in pending_fvgs:
                # ltf_in_fvg = ltf_df[(ltf_df["low"] < fvg["fvg_end"]) & (ltf_df["high"] > fvg["fvg_start"])]
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
                    if self.is_inversion(ltf_df, idx, fvg):
                        current_price = ltf_df["close"].iloc[idx]
                        buffer = 0.005 * current_price
                        candle_buffer = 10
                        current_ts = ltf_df["timestamp"].iloc[idx]
                        current_idx = ltf_df.index[ltf_df["timestamp"] == current_ts][0]
                        start_idx, end_idx = max(0, current_idx - candle_buffer), min(len(ltf_df) - 1, current_idx + candle_buffer)
                        start_ts, end_ts = ltf_df["timestamp"].iloc[start_idx], ltf_df["timestamp"].iloc[end_idx]

                        msb = next(
                            (m for m in msbs if m["direction"] != fvg["direction"] and start_ts <= m["timestamp"] <= end_ts and
                            (fvg["fvg_start"] - buffer) <= m["level"] <= (fvg["fvg_end"] + buffer)),
                            None
                        )
                        if msb:
                            is_valid, confluences = validate_signal(fvg, msb, valid_liquidity, ltf_df, idx)
                            if not is_valid:
                                continue
                            liq_target = self.get_nearest_liquidity(valid_liquidity, fvg)
                            if not liq_target:
                                continue

                            target_price = liq_target["level"]
                            stop_loss = self.get_stop_loss(fvg)
                            rr = self.get_rr(ltf_df, idx, fvg, liq_target)
                            if rr is None or rr < 1.0:
                                continue
                            if rr > 10.0:
                                # --- Determine the TRADE direction (Inverse of FVG direction) ---
                                if fvg["direction"] == "bullish":
                                    trade_direction = "bearish" # Inverted bullish FVG -> Sell signal
                                elif fvg["direction"] == "bearish":
                                    trade_direction = "bullish" # Inverted bearish FVG -> Buy signal
                                else:
                                    # Handle unexpected FVG direction
                                    logger.error("Invalid FVG direction '%s' found for FVG %s.", fvg.get("direction"), fvg.get('id', 'N/A'))
                                    continue # Skip this FVG
                                target_price = self.calculate_adjusted_target(current_price, stop_loss, trade_direction, max_rr=10.0)
                                rr = 10.0

                            signal = {
                                "ticker": ticker,
                                "timeframe": ltf,
                                "direction": trade_direction.upper() if trade_direction != "" else ("bearish" if fvg["direction"] == "bullish" else "bullish"),
                                "reason": f"Inverse FVG + MSB + {','.join(confluences)}",
                                "fvg_id": fvg["id"],
                                "fvg":convert_decimals(fvg),
                                "liquidity_target": float(target_price),
                                "stop_loss": float(stop_loss),
                                "rr": float(rr),
                            }
                            await self.persist_signal(signal)
                            self.redis_stream.publish(self.signal_channel, signal)
                            # --- START NEW CODE ---
                            # 1. Ensure all values within the signal are serializable (handles Decimals, Timestamps etc.)
                            serializable_signal = convert_decimals(signal)

                            # 2. Convert the entire serializable dictionary to a JSON string
                            signal_json = json.dumps(serializable_signal)

                            # 3. Publish the JSON string as the value for a specific field in the stream message
                            #    (e.g., using a key like 'signal_data')
                            # self.redis_stream.publish(self.signal_channel, {"signal_data": signal_json})
                            # --- END NEW CODE ---
                            await self.update_fvg_status(fvg["id"], "filled", ltf_df["timestamp"].iloc[idx], confluences, msb)
                            logger.info("Published trade signal: %s", signal_json)
                    break  # Only one signal per FVG
        except Exception as e:
            logger.error("Error in process_new_data: %s", str(e))



    # async def process_new_data(self, message):
    #     try:
    #         logger.info("Received new data event: %s", message)
    #         ticker = message["ticker"]

    #         # 1. Detect and persist new HTF FVGs
    #         htf = self.timeframes["htf"]
    #         htf_lookback = self.history["htf_lookback_days"]
    #         htf_df = await load_ohlcv_window(self.db_engine, ticker, htf, htf_lookback)
    #         if htf_df is None or htf_df.empty:
    #             logger.warning("No HTF data for %s", ticker)
    #             return
    #         htf_fvgs = detect_fvgs(htf_df, ticker, htf)
    #         await self.persist_new_fvgs(ticker, htf, htf_fvgs)

    #         # 2. Load LTF data
    #         ltf = self.timeframes["ltf"]
    #         ltf_lookback = self.history["ltf_lookback_days"]
    #         ltf_df = await load_ohlcv_window(self.db_engine, ticker, ltf, ltf_lookback)
    #         if ltf_df is None or ltf_df.empty:
    #             logger.warning("No LTF data for %s", ticker)
    #             return
            
    #         # 3. Detect liquidity levels
    #         liquidity = detect_liquidity(ltf_df, ticker, ltf)
    #         # liquidity = [l for l in liquidity if "level" in l and "type" in l and isinstance(l["level"], (float, int, np.float64))]
    #         logger.info("Liquidity levels: %s", liquidity)
    #         # Validate liquidity levels
    #         valid_liquidity = []
    #         for liq in liquidity:
    #             if not isinstance(liq, dict):
    #                 logger.warning("Malformed liquidity entry (not a dict): %s", liq)
    #                 continue
    #             if "level" not in liq or "type" not in liq:
    #                 logger.warning("Skipping liquidity without 'level' or 'type': %s", liq)
    #                 continue
    #             if not isinstance(liq["level"], (float, int, np.float64)):
    #                 logger.warning("Skipping liquidity with invalid 'level' type: %s", liq)
    #                 continue
    #             valid_liquidity.append(liq)

    #         # Log the validated liquidity levels
    #         logger.info("Validated liquidity levels: %s", valid_liquidity)

    #         if not valid_liquidity:
    #             logger.warning("No valid liquidity levels found for %s", ticker)
    #             return

    #         # Convert np.float64 to standard float
    #         for liq in valid_liquidity:
    #             liq["level"] = float(liq["level"])

    #         # Use validated liquidity for further processing
    #         liquidity = valid_liquidity
    #         # Convert np.float64 to standard float
    #         for liq in valid_liquidity:
    #             if not isinstance(liq, dict):
    #                 logger.warning("Malformed liquidity entry (not a dict): %s", liq)
    #                 continue
    #             if "level" not in liq or "formed_at" not in liq:
    #                 logger.warning("Skipping liquidity without level or formed_at: %s", liq)
    #                 continue
    #             liq["level"] = float(liq["level"])
                
    #         # 4. Check for tapped liquidity levels
    #         for liq in liquidity:
    #             if not isinstance(liq, dict):
    #                 logger.warning("Malformed liquidity entry (not a dict): %s", liq)
    #                 continue
    #             if "level" not in liq or "formed_at" not in liq:
    #                 logger.warning("Skipping liquidity without level or formed_at: %s", liq)
    #                 continue
    #             if "level" not in liq or "formed_at" not in liq:
    #                 logger.warning("Skipping liquidity without level or formed_at: %s", liq)
    #                 continue
    #             ltf_after_formed = ltf_df[ltf_df["timestamp"] > liq["formed_at"]]
    #             if ltf_after_formed.empty:
    #                 logger.warning("No price data after formed_at for liquidity level: %s", liq)
    #                 liq["tapped"] = False
    #                 liq["tap_time"] = None
    #                 continue

    #             if liq["type"] == "sell-side" and ltf_after_formed["high"].max() >= liq["level"]:
    #                 liq["tapped"] = True
    #                 liq["tap_time"] = ltf_after_formed["timestamp"].iloc[-1]
    #             elif liq["type"] == "buy-side" and ltf_after_formed["low"].min() <= liq["level"]:
    #                 liq["tapped"] = True
    #                 liq["tap_time"] = ltf_after_formed["timestamp"].iloc[-1]
    #             else:
    #                 liq["tapped"] = False
    #                 liq["tap_time"] = None

    #         await self.persist_liquidity(ticker, ltf, liquidity)

    #         # 5. Process pending FVGs
    #         pending_fvgs = [fvg for fvg in await self.get_pending_fvgs(ticker, htf)]
    #         msbs = detect_msbs(ltf_df, ticker, ltf)
    #         logger.info("MSBs detected: %s", msbs)
    #         for fvg in pending_fvgs:
    #             logger.info("Checking MSBs for FVG: %s", fvg)
    #             # expiry_days = 5
    #             # fvg_age = datetime.now(timezone.utc) - fvg["formed_at"]
    #             # if fvg_age > timedelta(days=expiry_days):
    #             #     await self.mark_fvg_as_expired(self.db_engine,fvg["id"])  # ← you’ll write this DB update function
    #             #     logger.info(f"Expired FVG {fvg['id']} after {expiry_days} days.")
    #             #     continue  # skip processing this FVG
                
    #             # Filter LTF data within HTF FVG boundaries
    #             ltf_in_fvg = ltf_df[(ltf_df["low"] < fvg["fvg_end"]) & (ltf_df["high"] > fvg["fvg_start"])]

    #             ltf_inside_fvg = ltf_df[
    #             (ltf_df["low"] >= fvg["fvg_start"]) & (ltf_df["high"] <= fvg["fvg_end"])
    #             ]
    #             if ltf_inside_fvg.empty:
    #                 logger.warning("No LTF candles inside FVG %s (%s)", fvg["symbol"], fvg["timeframe"])
    #                 logger.warning("Skipping FVG %s due to no LTF candles", fvg["id"])
    #                 continue  # Skip this FVG
    #             if not liquidity:
    #                 logger.warning("No liquidity levels for %s (%s), skipping FVG %s",
    #                             fvg["symbol"], fvg["timeframe"], fvg["id"])
    #                 continue
                
    #             for idx in ltf_in_fvg.index:
    #                 if self.is_inversion(ltf_df, idx, fvg):
    #                     # Validate MSB within FVG boundaries
    #                     current_price = ltf_df["close"].iloc[idx]
    #                     buffer = 0.005 * current_price  # 0.2%
    #                     candle_buffer = 10  # Number of candles to check for MSB

    #                     # Get current LTF index timestamp
    #                     current_ts = ltf_df["timestamp"].iloc[idx]

    #                     # Find index of current_ts in the DataFrame
    #                     current_idx_list = ltf_df.index[ltf_df["timestamp"] == current_ts].tolist()
    #                     if not current_idx_list:
    #                         logger.warning("Timestamp %s not found in LTF dataframe index.", current_ts)
    #                         continue  # or handle gracefully
    #                     current_idx = current_idx_list[0]

    #                     # Define start and end range for MSB check
    #                     start_idx = max(0, current_idx - candle_buffer)
    #                     end_idx = min(len(ltf_df) - 1, current_idx + candle_buffer)
    #                     start_ts = ltf_df["timestamp"].iloc[start_idx]
    #                     end_ts = ltf_df["timestamp"].iloc[end_idx]

    #                     # Find MSB in same direction within this time window and price range
    #                     msb = next(
    #                         (m for m in msbs if m["direction"] != fvg["direction"]
    #                         and start_ts <= m["timestamp"] <= end_ts
    #                         and ((fvg["fvg_start"] - buffer) <= m["level"] <= (fvg["fvg_end"] + buffer))),
    #                         None
    #                     )
    #                     if not msb:
    #                         logger.info(
    #                             "No valid MSB found for FVG %s (%s). MSBs: %s, Start TS: %s, End TS: %s, Buffer: %s",
    #                             fvg["symbol"], fvg["timeframe"], msbs, start_ts, end_ts, buffer
    #                         )
    #                     if msb:
    #                         # Validate signal with confluences
    #                         logger.info("Valid MSB found for FVG %s (%s): %s", fvg["symbol"], fvg["timeframe"], msb)
    #                         is_valid, confluences = validate_signal(fvg, msb, liquidity, ltf_df, idx)
    #                         if is_valid:
    #                             # Filter liquidity levels based on FVG position
    #                             liq_target = self.get_nearest_liquidity(valid_liquidity, fvg)
    #                             if not liq_target:
    #                                 logger.warning("No liquidity target found for FVG: %s", fvg)
    #                                 continue

    #                             target_price = liq_target["level"]
    #                             # CONFIRM WITH CHATGPT
    #                             # target_price = liq_target["level"] if liq_target else None
    #                             stop_loss = self.get_stop_loss(fvg)
    #                             rr=self.get_rr(ltf_df, idx, fvg, liq_target) if self.get_rr(ltf_df, idx, fvg, liq_target) is not None else None
    #                             if rr < 1.0:
    #                                 logger.info("Skipping trade with too low RR: %.2f", rr)
    #                                 continue
    #                             elif rr > 10.0:
    #                                 logger.info("Adjusting target to cap RR at 10 (was %.2f)", rr)
    #                                 # stop_loss=self.get_stop_loss(fvg)
    #                                 # Find next liquidity level closer to entry that gives RR ≈ 10
    #                                 adjusted_target = self.calculate_adjusted_target(current_price, stop_loss, max_rr=10.0)
    #                                 target_price = adjusted_target
    #                                 rr = 10.0
                                
    #                             signal = {
    #                                 "ticker": ticker,
    #                                 "timeframe": ltf,
    #                                 "direction": fvg["direction"].upper(),
    #                                 "reason": f"Inverse FVG + MSB + {','.join(confluences)}",
    #                                 "fvg_id": fvg["id"],
    #                                 "liquidity_target": float(target_price) if target_price else None,
    #                                 "stop_loss": float(stop_loss) ,
    #                                 "rr": float(rr) ,
    #                             }
    #                             await self.persist_signal(signal)
    #                             self.redis_stream.publish(self.signal_channel, signal)
    #                             await self.update_fvg_status(fvg["id"], "filled", ltf_df["timestamp"].iloc[idx], confluences, msb)
    #                             logger.info("Published trade signal: %s", signal)
    #                     else:
    #                         logger.info(
    #                             "Skipping FVG %s (%s) because no valid MSB was found nearby. Formed at %s.",
    #                             fvg["symbol"], fvg["timeframe"], fvg["formed_at"]
    #                         )
    #                         continue
    #                     break  # Only one signal per FVG per run
    #     except Exception as e:
    #         logger.error("Error in process_new_data: %s", str(e))

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

    async def update_fvg_status(self, fvg_id, status, inversion_time, confluences, msb):
        async with self.db_engine.begin() as conn:
            metadata = {"confluences": confluences, "msb": msb}
            metadata = convert_decimals(metadata)  # Ensure all values are serializable
            metadata_json = json.dumps(metadata)  # Serialize to JSON string
            await conn.execute(
                text("""
                    UPDATE tracked_fvgs
                    SET status=:status, confirmed=TRUE, msb_confirmed=TRUE,
                        inversion_time=:inversion_time, signal_emitted_at=NOW(),
                        metadata=:metadata, last_checked=NOW()
                    WHERE id=:id
                """),
                {
                    "id": fvg_id,
                    "status": status,
                    "inversion_time": inversion_time, # inversion_time.isoformat() if hasattr(inversion_time, 'isoformat') else inversion_time,
                    "metadata": metadata_json,  # Pass serialized JSON string
                }
            )
            
            # logger.info("Metadata before publishing in update_fvg_status: %s", metadata)
            # for k, v in metadata.items():
            #     logger.info("Metadata key: %s, value: %s (%s)", k, v, type(v))

    async def persist_signal(self, signal):
        async with self.db_engine.begin() as conn:
            # Check if the signal already exists
            result = await conn.execute(
                text("""
                    SELECT id FROM technical_analysis_signals
                    WHERE symbol=:symbol AND timeframe=:timeframe AND fvg_id=:fvg_id
                      AND status='pending'
                """),
                {
                    "symbol": signal["ticker"],
                    "timeframe": signal["timeframe"],
                    "fvg_id": signal["fvg_id"]
                }
            )
            existing_signal = result.fetchone()

            if existing_signal:
                # Update the existing signal
                await conn.execute(
                    text("""
                        UPDATE technical_analysis_signals
                        SET direction=:direction, liquidity_target=:liquidity_target,
                            stop_loss=:stop_loss, rr=:rr, reason=:reason,
                            updated_at=NOW()
                        WHERE id=:id
                    """),
                    {
                        "id": existing_signal["id"],
                        "direction": signal["direction"],
                        "liquidity_target": signal["liquidity_target"],
                        "stop_loss": signal["stop_loss"],
                        "rr": signal["rr"],
                        "reason": signal["reason"]
                    }
                )
            else:
                # Insert a new signal
                await conn.execute(
                    text("""
                        INSERT INTO technical_analysis_signals
                        (symbol, timeframe, direction, fvg_id, liquidity_target,
                         stop_loss, rr, reason, status)
                        VALUES (:symbol, :timeframe, :direction, :fvg_id,
                                :liquidity_target, :stop_loss, :rr, :reason, 'pending')
                    """),
                    {
                        "symbol": signal["ticker"],
                        "timeframe": signal["timeframe"],
                        "direction": signal["direction"],
                        "fvg_id": signal["fvg_id"],
                        "liquidity_target": signal["liquidity_target"],
                        "stop_loss": signal["stop_loss"],
                        "rr": signal["rr"],
                        "reason": signal["reason"]
                    }
                )

    def is_inversion(self, ltf_df, idx, fvg):
        direction = fvg["direction"]
        close = ltf_df["close"].iloc[idx]
        if direction == "bullish" and close < fvg["fvg_end"]:
            return True
        if direction == "bearish" and close > fvg["fvg_start"]:
            return True
        return False

    def get_nearest_liquidity(self, liquidity, fvg):
        direction = fvg["direction"]
        # Filter only liquidity entries that have level and type
        candidates = [l for l in liquidity if l.get("level") is not None and l.get("type") is not None]
        
        if direction == "bullish":
            candidates = [l for l in candidates if l.get("type") == "sell-side" and not l.get("tapped")]
        else:
            candidates = [l for l in candidates if l.get("type") == "buy-side" and not l.get("tapped")]

        if not candidates:
            logger.warning("No valid liquidity candidates found for FVG: %s", fvg)
            return None

        return min(candidates, key=lambda l: abs(l["level"] - (fvg["fvg_end"] if direction == "bullish" else fvg["fvg_start"])))

    def get_stop_loss(self, fvg):
        # SL just below/above the FVG depending on direction
        if fvg["direction"] == "bullish":
            return fvg["fvg_end"]
        else:
            return fvg["fvg_start"]

    def get_rr(self, ltf_df, idx, fvg, liq_target):
        entry = ltf_df["close"].iloc[idx]
        stop = self.get_stop_loss(fvg)
        if not liq_target:
            logger.warning("Liquidity target is missing for FVG: %s", fvg)
            return None
        target = liq_target["level"]
        # if fvg["direction"] == "bullish":
        #     risk = entry - stop
        #     reward = target - entry
        # else:
        #     risk = stop - entry
        #     reward = entry - target
        risk = abs(entry - stop)
        reward = abs(target - entry)
        if risk <= 0:
            logger.warning("Invalid risk value (<= 0). Risk(Target-Entry): %s, Entry: %s, Stop: %s, Target: %s", risk, entry, stop, target)
            return None
        rr = round(reward / risk, 2)
        logger.info("Calculated RR: %s (Entry: %s, Stop: %s, Target: %s)", rr, entry, stop, target)
        return rr
    
    async def update_signal_status(self, signal_id, status):
        async with self.db_engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE technical_analysis_signals
                    SET status=:status, updated_at=NOW()
                    WHERE id=:id
                """),
                {"id": signal_id, "status": status}
            )

    async def mark_fvg_as_expired(self, db_engine, fvg_id):
        async with db_engine.begin() as conn:
            await conn.execute(
                text("""
                    UPDATE tracked_fvgs
                    SET status = 'expired'
                    WHERE id = :fvg_id
                """),
                {"fvg_id": fvg_id}
            )
    # @staticmethod
    def calculate_adjusted_target(self,entry_price, stop_loss, direction, max_rr=10.0):
        risk = abs(entry_price - stop_loss)
        adjusted_distance = risk * max_rr
        if direction == "bullish":
            return entry_price + adjusted_distance
        else:
            return entry_price - adjusted_distance

