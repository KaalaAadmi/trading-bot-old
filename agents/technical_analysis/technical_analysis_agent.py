import logging
import asyncio
import json
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd

from core.config.config_loader import load_settings
from core.redis_bus.redis_stream import RedisStream
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql import text
from agents.common.utils import convert_decimals, db_fvg_to_logic_fvg
from agents.technical_analysis.utils.data_loader import load_ohlcv_window
from agents.technical_analysis.logic.fvg_detector import detect_significant_fvgs_atr
from agents.technical_analysis.logic.msb_detector import detect_msbs_swing
from agents.technical_analysis.logic.liquidity_tracker import detect_liquidity_swing
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
        # self.

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

    async def _load_and_prepare_data(self, ticker):
        """Loads HTF/LTF data and detects base features (FVG, Liquidity, MSB)."""
        htf = self.timeframes["htf"]
        htf_lookback = self.history["htf_lookback_days"]
        htf_df = await load_ohlcv_window(self.db_engine, ticker, htf, htf_lookback)
        if htf_df is None or htf_df.empty:
            logger.warning(f"[{ticker}] No HTF data loaded.")
            return None, None, None, None

        # Detect and persist HTF FVGs
        htf_fvgs = detect_significant_fvgs_atr(htf_df, ticker, htf, atr_period=14, atr_multiplier=0.8, min_pct_price=0.003)
        await self.persist_new_fvgs(ticker, htf, htf_fvgs) # Assuming this handles duplicates

        ltf = self.timeframes["ltf"]
        ltf_lookback = self.history["ltf_lookback_days"]
        ltf_df = await load_ohlcv_window(self.db_engine, ticker, ltf, ltf_lookback)
        if ltf_df is None or ltf_df.empty:
            logger.warning(f"[{ticker}] No LTF data loaded.")
            return htf_df, None, None, None # Return htf_df just in case

        # Detect LTF features
        liquidity = detect_liquidity_swing(ltf_df, ticker, ltf, swing_order=5) # Using new detector
        msbs = detect_msbs_swing(ltf_df, ticker, ltf, swing_order=5) # Using new detector

        # Validate and check taps for liquidity (can also be a separate method)
        valid_liquidity = []
        for liq in liquidity:
            # Basic validation
            if isinstance(liq, dict) and isinstance(liq.get("level"), (float, int)):
                 valid_liquidity.append(liq)
            else:
                 logger.warning(f"[{ticker}] Skipping invalid liquidity format: {liq}")
        # Check taps
        for liq in valid_liquidity:
            ltf_after = ltf_df[ltf_df["timestamp"] > liq["formed_at"]]
            tapped = False
            tap_time = None
            if not ltf_after.empty:
                 if liq["type"] == "sell-side" and ltf_after["high"].max() >= liq["level"]:
                     tapped = True; tap_time = ltf_after["timestamp"].iloc[-1]
                 elif liq["type"] == "buy-side" and ltf_after["low"].min() <= liq["level"]:
                     tapped = True; tap_time = ltf_after["timestamp"].iloc[-1]
            liq.update({"tapped": tapped, "tap_time": tap_time})
        await self.persist_liquidity(ticker, ltf, valid_liquidity) # Persist liquidity state


        return htf_df, ltf_df, valid_liquidity, msbs, htf_fvgs

    def _find_confirming_msb(self, fvg, msbs, ltf_df, inversion_idx):
        """Checks for a valid MSB near the inversion point."""
        current_price = ltf_df["close"].iloc[inversion_idx]
        buffer = 0.005 * current_price # Buffer around FVG for MSB level check
        candle_buffer = 10 # Look N candles before/after inversion for MSB timestamp

        current_ts = ltf_df["timestamp"].iloc[inversion_idx]
        # Find index in original df (safer than assuming iloc matches index directly if df was filtered)
        current_loc_idx = ltf_df.index.get_loc(inversion_idx) if isinstance(inversion_idx, pd.Timestamp) else inversion_idx

        start_loc_idx = max(0, current_loc_idx - candle_buffer)
        end_loc_idx = min(len(ltf_df) - 1, current_loc_idx + candle_buffer)
        start_ts = ltf_df["timestamp"].iloc[start_loc_idx]
        end_ts = ltf_df["timestamp"].iloc[end_loc_idx]

        # Trade direction is inverse of FVG direction
        required_msb_direction = "bearish" if fvg["direction"] == "bullish" else "bullish"

        for m in msbs:
            # Check 1: Direction must match required trade direction
            if m["direction"] != required_msb_direction:
                continue
            # Check 2: Timestamp must be within the buffer window around inversion
            if not (start_ts <= m["timestamp"] <= end_ts):
                continue
            # Check 3: The broken level must be within the original FVG's range (+ buffer)
            # Using m["broken_level"] from the new MSB detector
            if not ((fvg["fvg_start"] - buffer) <= m["broken_level"] <= (fvg["fvg_end"] + buffer)):
                 continue

            # If all checks pass, this is the confirming MSB
            return m

        return None # No confirming MSB found

    def _calculate_trade_parameters(self, fvg, liq_target, ltf_df, inversion_idx, trade_direction, max_rr_cap=10.0):
        """Calculates entry, stop, target, and RR, applying capping."""
        entry_price = ltf_df["close"].iloc[inversion_idx]
        stop_loss = self.get_stop_loss(fvg) # Uses existing method

        if not liq_target or not isinstance(liq_target.get("level"), (float, int)):
             logger.warning(f"Invalid or missing liquidity target for FVG {fvg.get('id')}")
             return None # Cannot calculate params

        initial_target_price = liq_target["level"]

        # Calculate initial RR
        risk = abs(entry_price - stop_loss)
        if risk <= 1e-9: # Check for zero or near-zero risk
             logger.warning(f"Risk is zero or negligible for FVG {fvg.get('id')}. Entry={entry_price}, SL={stop_loss}")
             return None
        reward = abs(initial_target_price - entry_price)
        initial_rr = round(reward / risk, 2)

        if initial_rr < 1.0:
             logger.info(f"Initial RR {initial_rr:.2f} < 1.0 for FVG {fvg.get('id')}. Skipping.")
             return None # RR too low

        # Apply RR capping
        final_target_price = initial_target_price
        final_rr = initial_rr
        if initial_rr > max_rr_cap:
             logger.info(f"RR {initial_rr:.2f} exceeds {max_rr_cap}. Adjusting target for FVG {fvg.get('id')}...")
             # Use static method, passing TRADE direction
             adjusted_target = TechnicalAnalysisAgent.calculate_adjusted_target(
                 entry_price,
                 stop_loss,
                 trade_direction, # Pass the actual trade direction
                 max_rr=max_rr_cap
             )
             if adjusted_target is not None:
                 final_target_price = adjusted_target
                 final_rr = max_rr_cap
                 logger.info(f"Target adjusted to {final_target_price:.5f} for RR {final_rr:.2f}")
             else:
                 logger.warning(f"Could not calculate adjusted target for FVG {fvg.get('id')}. Skipping.")
                 return None # Adjustment failed

        # Final sanity check on target price vs entry
        if (trade_direction == "bullish" and final_target_price <= entry_price) or \
           (trade_direction == "bearish" and final_target_price >= entry_price):
            logger.warning(f"Final target price {final_target_price:.5f} invalid relative to entry {entry_price:.5f} for {trade_direction} trade. Skipping FVG {fvg.get('id')}.")
            return None

        return {
            "entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "target_price": float(final_target_price),
            "rr": float(final_rr)
        }

    # --- Make calculate_adjusted_target static ---
    @staticmethod
    def calculate_adjusted_target(entry_price, stop_loss, trade_direction, max_rr=10.0):
        """Calculates a target price for a given RR based on trade direction."""
        # Removed internal direction flip - expects TRADE direction now
        if trade_direction not in ["bullish", "bearish"]:
            logger.error(f"Invalid trade_direction '{trade_direction}' passed to calculate_adjusted_target.")
            return None

        risk = abs(entry_price - stop_loss)
        if risk <= 1e-9: # Avoid division by zero or weird results
             logger.warning("Adjusted target calculation failed: Risk is zero or negligible.")
             return None

        adjusted_distance = risk * max_rr
        if trade_direction == "bullish":
            return entry_price + adjusted_distance
        else: # Bearish
            return entry_price - adjusted_distance

    # --- Main Orchestration Method ---
    async def process_new_data(self, message):
        """Orchestrates the technical analysis process."""
        try:
            logger.info("Received new data event: %s", message)
            ticker = message["ticker"]

            # Step 1: Load data and detect base features
            htf_df, ltf_df, valid_liquidity, msbs, _ = await self._load_and_prepare_data(ticker)
            if ltf_df is None or ltf_df.empty:
                return # Exit if essential data is missing

            if not valid_liquidity:
                 logger.info(f"[{ticker}] No valid liquidity found. Skipping FVG checks.")
                 return
            if not msbs:
                 logger.info(f"[{ticker}] No MSBs detected by swing point analysis. Skipping FVG checks.")
                 # return # Decide if you want to exit if no MSBs at all

            # Step 2: Get pending FVGs
            pending_fvgs = await self.get_pending_fvgs(ticker, self.timeframes["htf"])
            if not pending_fvgs:
                 logger.info(f"[{ticker}] No pending FVGs found.")
                 return

            # Step 3: Process each pending FVG
            for fvg in pending_fvgs:
                processed_signal = False # Flag to ensure only one signal per FVG per run

                # Find LTF candles formed *after* the FVG was formed
                ltf_after_fvg = ltf_df[ltf_df["timestamp"] >= fvg["formed_at"]]
                if ltf_after_fvg.empty:
                     # logger.debug(f"[{ticker}] No LTF candles after FVG {fvg['id']} formed at {fvg['formed_at']}.")
                     continue # Skip FVG if no relevant LTF data

                # Iterate through relevant LTF candles to check for inversion
                # Check only recent candles maybe? e.g., last 100? ltf_after_fvg.tail(100).index
                for idx in ltf_after_fvg.index:
                    if self.is_inversion(ltf_df, idx, fvg): # Use original DataFrame for lookup by index 'idx'
                        # logger.info(f"[{ticker}] Inversion detected for FVG {fvg['id']} at index {idx} (TS: {ltf_df.loc[idx, 'timestamp']})")

                        # Step 3a: Find confirming MSB
                        confirming_msb = self._find_confirming_msb(fvg, msbs, ltf_df, idx)
                        if not confirming_msb:
                            # logger.info(f"[{ticker}] No confirming MSB found near inversion for FVG {fvg['id']}.")
                            continue # Keep checking other inversion candles for this FVG

                        logger.info(f"[{ticker}] Confirming MSB found for FVG {fvg['id']}: {confirming_msb}")

                        # Step 3b: Validate signal based on confluences
                        # Pass the index of the *inversion* candle for validation checks
                        is_valid, confluences = validate_signal(fvg, confirming_msb, ltf_df, idx)
                        if not is_valid:
                             logger.info(f"[{ticker}] Signal validation failed for FVG {fvg['id']} ({confluences}).")
                             continue # Keep checking other inversion candles

                        # Step 3c: Find liquidity target
                        # Trade direction based on inverse logic
                        trade_direction = "bearish" if fvg["direction"] == "bullish" else "bullish"
                        # Filter liquidity based on required type for the trade
                        required_liq_type = "buy-side" if trade_direction == "bearish" else "sell-side"
                        potential_targets = [
                            l for l in valid_liquidity
                            if l.get("type") == required_liq_type and not l.get("tapped")
                        ]
                        if not potential_targets:
                             logger.warning(f"[{ticker}] No suitable UNTAPPED liquidity targets ({required_liq_type}) found for FVG {fvg['id']}.")
                             continue # Stop processing this inversion if no target

                        # Find nearest valid target
                        entry_price_for_targeting = ltf_df["close"].iloc[idx]
                        liq_target = min(potential_targets, key=lambda l: abs(l["level"] - entry_price_for_targeting))
                        logger.info(f"[{ticker}] Selected liquidity target for FVG {fvg['id']}: {liq_target}")


                        # Step 3d: Calculate trade parameters (Entry, SL, TP, RR with capping)
                        trade_params = self._calculate_trade_parameters(fvg, liq_target, ltf_df, idx, trade_direction)
                        if not trade_params:
                             logger.warning(f"[{ticker}] Failed to calculate valid trade parameters for FVG {fvg['id']}. Skipping this setup.")
                             continue # Stop processing this inversion if params invalid

                        # Step 3e: Construct and emit signal
                        signal = {
                            "ticker": ticker,
                            "timeframe": self.timeframes["ltf"],
                            "direction": trade_direction.upper(),
                            "fvg_direction": fvg["direction"].upper(),
                            "fvg_height":fvg["fvg_height"],
                            "reason": f"Inverse FVG + MSB + {','.join(confluences)}",
                            "fvg_id": fvg["id"],
                            "entry_price": trade_params["entry_price"],
                            "liquidity_target": trade_params["target_price"],
                            "stop_loss": trade_params["stop_loss"],
                            "rr": trade_params["rr"],
                            "signal_generated_at": datetime.now(timezone.utc).isoformat(),
                        }

                        # --- Persist signal and get its ID ---
                        persisted_signal_id = await self.persist_signal(signal, confirming_msb)

                        if persisted_signal_id:
                            # --- Add the DB ID to the signal dictionary ---
                            signal["signal_id"] = persisted_signal_id

                            # Ensure data is JSON serializable for Redis
                            self.redis_stream.publish(self.signal_channel, convert_decimals(signal))
                            # Update FVG status in DB
                            await self.update_fvg_status(fvg["id"], "filled", ltf_df["timestamp"].iloc[idx], confluences, confirming_msb)

                            logger.info(f"[{ticker}] Published trade signal (ID: {persisted_signal_id}) for FVG {fvg['id']}: {signal}")
                            logger.info(f"[{ticker}] FVG {fvg['id']} processed successfully. Signal emitted.") # Use fvg['id']
                            processed_signal = True
                            break # ---> IMPORTANT: Break from inner loop (LTF candles) after finding the FIRST valid signal for this FVG
                        else:
                            logger.error(f"[{ticker}] Failed to persist signal or get ID for FVG {fvg['id']}. Signal not published.")
                            # Decide if you should update FVG status differently here or retry

                if processed_signal:
                     # Optionally break from outer loop (FVGs) if you only want one signal per ticker per run
                     # break # <-- Uncomment if desired
                     pass # Continue to check next FVG

        except Exception as e:
            logger.exception(f"Critical error in process_new_data: {e}") # Use logger.exception


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

    async def persist_signal(self, signal_data, msb_info): # Add msb_info argument
        """ Persists the generated signal, linking the confirming MSB """
        async with self.db_engine.begin() as conn:
            # Check if the signal already exists based on FVG ID and pending status
            result = await conn.execute(
                text("""
                    SELECT id FROM technical_analysis_signals
                    WHERE symbol=:symbol AND timeframe=:timeframe AND fvg_id=:fvg_id
                      AND status='pending'
                """),
                {
                    "symbol": signal_data["ticker"],
                    "timeframe": signal_data["timeframe"],
                    "fvg_id": signal_data["fvg_id"]
                }
            )
            existing_signal = result.fetchone()

            # Prepare common data, ensuring MSB info is included
            params = {
                "symbol": signal_data["ticker"],
                "timeframe": signal_data["timeframe"],
                "direction": signal_data["direction"],
                "fvg_id": signal_data["fvg_id"],
                "liquidity_target": signal_data["liquidity_target"],
                "stop_loss": signal_data["stop_loss"],
                "rr": signal_data["rr"],
                "reason": signal_data["reason"],
                # Extract MSB info - use defaults if keys are missing in msb_info
                "msb_broken_level": msb_info.get("broken_level"), # Using broken_level from new MSB detector
                "msb_timestamp": msb_info.get("broken_level_ts") # Using timestamp of the broken swing point
            }

            if existing_signal:
                # Update the existing signal
                params["id"] = existing_signal["id"]
                # ... (existing update execution) ...
                signal_id = existing_signal["id"] # Assign existing ID
                logger.info(f"Updated existing signal ID {signal_id} with MSB {params.get('msb_broken_level')} @ {params.get('msb_timestamp')}")
            else:
                # Insert a new signal and retrieve the ID
                params["status"] = 'pending'
                result = await conn.execute(
                    text("""
                        INSERT INTO technical_analysis_signals
                        (symbol, timeframe, direction, fvg_id, liquidity_target,
                        stop_loss, rr, reason, status, msb_broken_level, msb_timestamp)
                        VALUES (:symbol, :timeframe, :direction, :fvg_id,
                                :liquidity_target, :stop_loss, :rr, :reason, :status,
                                :msb_broken_level, :msb_timestamp)
                        RETURNING id -- Add RETURNING id to get the new ID
                    """),
                    params
                )
                inserted_row = result.fetchone() # Fetch the result of RETURNING
                if inserted_row:
                    signal_id = inserted_row["id"] # Assign new ID
                    logger.info(f"Inserted new signal ID {signal_id} for FVG {params.get('fvg_id')} with MSB {params.get('msb_broken_level')} @ {params.get('msb_timestamp')}")
                else:
                    logger.error(f"Failed to retrieve ID after inserting signal for FVG {params.get('fvg_id')}")

        return signal_id # Return the ID


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
    # def calculate_adjusted_target(self,entry_price, stop_loss, direction, max_rr=10.0):
    #     trade_direction=""
    #     if direction=="bullish":
    #         trade_direction="bearish"
    #     elif direction=="bearish":
    #         trade_direction="bullish"
    #     risk = abs(entry_price - stop_loss)
    #     adjusted_distance = risk * max_rr
    #     if trade_direction == "bullish":
    #         return entry_price + adjusted_distance
    #     else:
    #         return entry_price - adjusted_distance