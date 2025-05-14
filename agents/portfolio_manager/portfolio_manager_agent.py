import logging
import asyncio
import json
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone

from core.config.config_loader import load_settings
from core.redis_bus.redis_stream import RedisStream
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql import text
from agents.common.utils import convert_decimals # Assuming you might need this

logger = logging.getLogger("agents.portfolio_manager")

class PortfolioManagerAgent:
    def __init__(self, settings_path=None):
        self.settings = load_settings(settings_path)
        self.redis_stream = RedisStream()

        # Input stream from Technical Analysis
        self.signal_channel = self.redis_stream.get_channel("technical_analysis")
        # Output stream for Execution Agent
        self.execution_channel = self.redis_stream.get_channel("portfolio_manager") # New channel

        db_cfg = self.settings["database"]
        self.db_engine = create_async_engine(
            f"postgresql+asyncpg://{db_cfg['user']}:{db_cfg['password']}@{db_cfg['host']}:{db_cfg['port']}/{db_cfg['db']}"
        )

        # --- Load Portfolio and Environment Settings ---
        portfolio_cfg = self.settings.get("portfolio", {})
        # Real risk settings (used in production, placeholder for now)
        self.account_balance = Decimal(portfolio_cfg.get("initial_balance", 1000000.0))
        self.max_risk_per_trade_pct = Decimal(portfolio_cfg.get("max_risk_per_trade_pct", 0.01))
        # Fixed size for development mode
        self.dev_position_size_usd = Decimal(portfolio_cfg.get("dev_position_size_usd", 100.0))

        self.environment = self.settings.get("environment", "development").lower()
        
        self._semaphore = None  # Placeholder
        self._loop = None

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
        logger.info(f"Starting Portfolio Manager Agent in '{self.environment}' mode...")
        self._loop = asyncio.get_running_loop()
        self._semaphore = asyncio.Semaphore(5)

        self.redis_stream.subscribe(
            self.signal_channel,
            self.process_signal,
            consumer_group="pm_group",
            consumer_name="pm_consumer_1"
        )
        logger.info(f"Subscribed to Redis stream: {self.signal_channel}")
        logger.info(f"Will publish orders to Redis stream: {self.execution_channel}")

        while True:
            await asyncio.sleep(1) # Keep alive

    async def process_signal(self, message):
        """Processes a new trade signal, calculates size, and forwards to execution."""
        async with self.semaphore: # <--- Use the semaphore
            try:
                signal = message # Assuming message is already a dict
                logger.info(f"Received trade signal: {signal}")
                # Fetch data from db for all the signals that have been persisted in the technical_analysis_signals table only then will there be an id
                # --- Basic Validation ---
                required_keys = ["ticker", "direction", "entry_price", "stop_loss", "liquidity_target", "fvg_id","fvg_height","reason", "timeframe", "fvg_direction", "rr"]
                # Also need the signal's own ID from the DB if TA agent provides it
                signal_db_id = signal.get("signal_id") # Assuming TA agent adds this key after persisting

                if not all(key in signal for key in required_keys):
                    logger.warning(f"Signal missing required keys: {signal}. Skipping.")
                    return
                if not signal_db_id:
                    logger.warning(f"Signal missing 'signal_id': {signal}. Cannot update status. Skipping.")
                    return

                ticker = signal["ticker"]
                direction = signal["direction"].upper()
                try:
                    entry_price = Decimal(str(signal["entry_price"]))
                    stop_loss = Decimal(str(signal["stop_loss"]))
                    take_profit = Decimal(str(signal["liquidity_target"]))
                except (InvalidOperation, TypeError) as e:
                    logger.error(f"Invalid price/level format in signal {signal_db_id}: {e}. Signal: {signal}. Skipping.")
                    await self.update_signal_status_in_db(signal_db_id, "skipped_invalid_data")
                    return

                quantity = Decimal("0")
                position_value = Decimal("0")

                # --- Sizing Logic ---
                if self.environment == "development":
                    # Fixed position size ($100)
                    position_value = self.dev_position_size_usd
                    if entry_price <= Decimal("1e-9"): # Avoid division by zero
                        logger.warning(f"Entry price is zero or negligible for signal {signal_db_id}. Cannot calculate quantity. Skipping.")
                        await self.update_signal_status_in_db(signal_db_id, "skipped_zero_price")
                        return
                    # Calculate quantity based on fixed size, round down shares/contracts
                    quantity = (position_value / entry_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN) # Adjust precision as needed for crypto/stocks
                    logger.info(f"[DEV MODE] Using fixed position value: ${position_value:.2f}. Calculated quantity: {quantity} {ticker}")

                elif self.environment == "production":
                    # --- Real Risk Management (Placeholder) ---
                    # TODO: Replace with actual risk calculation based on % risk
                    risk_per_share = abs(entry_price - stop_loss)
                    if risk_per_share <= Decimal("1e-9"):
                        logger.warning(f"Risk per share is zero or negligible for signal {signal_db_id}. Skipping.")
                        await self.update_signal_status_in_db(signal_db_id, "skipped_invalid_risk")
                        return

                    risk_amount = self.account_balance * self.max_risk_per_trade_pct
                    quantity = (risk_amount / risk_per_share).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN) # Adjust precision
                    position_value = quantity * entry_price
                    logger.info(f"[PROD MODE] Risk Amount: ${risk_amount:.2f}. Calculated quantity: {quantity} {ticker}. Position Value: ${position_value:.2f}")
                    # --- End Risk Management Placeholder ---
                else:
                    logger.error(f"Unknown environment '{self.environment}'. Cannot proceed.")
                    return

                # Final quantity check
                # Use a small threshold appropriate for your assets (e.g., 1 for stocks, 0.0001 for crypto)
                min_quantity_threshold=0
                if len(signal['ticker'].split("-"))>1:
                    min_quantity_threshold = Decimal("0.0000000000000000001")
                else:
                    min_quantity_threshold = Decimal("0.01")
                if quantity < min_quantity_threshold:
                    logger.warning(f"Calculated quantity {quantity} is below threshold {min_quantity_threshold} for signal {signal_db_id}. Skipping.")
                    await self.update_signal_status_in_db(signal_db_id, "skipped_min_quantity")
                    return
                account_balance_at_entry = float((self.account_balance - 100)) # Convert to float for JSON serialization
                # --- Prepare Order for Execution Agent ---
                execution_order = {
                    **signal, # Include all original signal data
                    "account_balance_at_entry": float(account_balance_at_entry), # Add account balance (float for JSON)
                    "calculated_quantity": float(quantity), # Add calculated quantity (float for JSON)
                    "calculated_value_usd": float(position_value), # Add calculated value (float for JSON)
                    "pm_decision_timestamp": datetime.now(timezone.utc).isoformat(),
                    "environment": self.environment,
                    "signal_confidence": 0,  # Placeholder for confidence score
                    "portfolio_decision_at": datetime.now(timezone.utc).isoformat(),
                }

                # --- Update Signal Status in DB ---
                # Mark the original TA signal as being processed/forwarded
                await self.update_signal_status_in_db(signal_db_id, "sent_to_execution")

                # --- Publish to Execution Agent ---
                logger.info(f"Forwarding order to execution channel '{self.execution_channel}': {execution_order}")
                # Ensure JSON serializable (convert_decimals handles Decimal, datetime etc.)
                self.redis_stream.publish(self.execution_channel, convert_decimals(execution_order))

            except Exception as e:
                logger.exception(f"Error processing signal: {message} - {e}")
                # Optionally try to update signal status to 'failed_pm' if possible
                signal_db_id = message.get("signal_id") if isinstance(message, dict) else None
                if signal_db_id:
                    try:
                        await self.update_signal_status_in_db(signal_db_id, "failed_pm_processing")
                    except Exception as db_err:
                        logger.error(f"Additionally failed to update signal status after processing error: {db_err}")


    async def update_signal_status_in_db(self, signal_id, status):
        """Updates the status of a signal in the technical_analysis_signals table."""
        if not signal_id:
            logger.error("Cannot update signal status: signal_id is missing.")
            return
        try:
            async with self.db_engine.begin() as conn:
                await conn.execute(
                    text("""
                        UPDATE technical_analysis_signals
                        SET status = :status, updated_at = NOW()
                        WHERE id = :id AND status = 'pending' -- Only update if still pending
                    """),
                    {"id": signal_id, "status": status}
                )
                # Check if the update was successful (rowcount might be 0 if status wasn't 'pending')
                # result = await conn.execute(text("SELECT status FROM technical_analysis_signals WHERE id = :id"), {"id": signal_id})
                # current_status = result.scalar_one_or_none()
                # logger.info(f"Signal ID {signal_id} status updated to '{status}' (Current DB status: {current_status})")
                logger.info(f"Attempted to update signal status for Signal ID {signal_id} to '{status}'")

        except Exception as e:
            logger.exception(f"Failed to update signal status for Signal ID {signal_id} to '{status}': {e}")


# --- Main execution ---
# async def main():
#     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#     agent = PortfolioManagerAgent()
#     await agent.start()

# if __name__ == "__main__":
#     try:
#         asyncio.run(main())
#     except KeyboardInterrupt:
#         logger.info("Portfolio Manager Agent stopped.")
#     except Exception as main_err:
#         logger.exception(f"Portfolio Manager Agent failed to start: {main_err}")