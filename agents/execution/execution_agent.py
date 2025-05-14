import logging
import asyncio
import json
import uuid
from sqlalchemy.sql import text
from sqlalchemy.ext.asyncio import create_async_engine

from datetime import datetime, timezone
from core.redis_bus.redis_stream import RedisStream
from core.config.config_loader import load_settings
from agents.common.utils import convert_decimals

logger = logging.getLogger("agents.execution")

class ExecutionAgent:
    def __init__(self, settings_path=None):
        self.settings = load_settings(settings_path)
        self.redis_stream = RedisStream()

        # Input stream from PortfolioManagerAgent
        self.execution_orders_channel = self.redis_stream.get_channel("portfolio_manager")
        # Output stream for execution results
        self.execution_results_channel = self.redis_stream.get_channel("execution_results")

        # Database connection
        db_cfg = self.settings["database"]
        self.db_engine = create_async_engine(
            f"postgresql+asyncpg://{db_cfg['user']}:{db_cfg['password']}@{db_cfg['host']}:{db_cfg['port']}/{db_cfg['db']}"
        )
        
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
        logger.info(f"Starting Execution Agent in '{self.environment}' mode...")
        self.redis_stream.subscribe(
            self.execution_orders_channel,
            self.process_order,
            consumer_group="execution_group",
            consumer_name="execution_consumer_1"
        )
        logger.info(f"Subscribed to Redis stream: {self.execution_orders_channel}")

        while True:
            await asyncio.sleep(1)  # Keep the agent running

    async def process_order(self, message):
        """Processes an order from the PortfolioManagerAgent."""
        async with self.semaphore: # <--- Use the semaphore
            try:
                logger.info(f"Received order: {message}")

                # Validate required fields
                required_keys = ["ticker", "direction", "entry_price", "stop_loss", "liquidity_target", "calculated_quantity", "fvg_id","fvg_height","reason", "timeframe", "fvg_direction", "rr"]
                if not all(key in message for key in required_keys):
                    logger.warning(f"Order missing required keys: {message}. Skipping.")
                    return

                # Extract order details
                ticker = message["ticker"]
                direction = "BUY" if message["direction"].upper() == "BEARISH" else "SELL"
                entry_price = float(message["entry_price"])
                quantity = int(message["calculated_quantity"])
                account_balance_at_entry = float(message["account_balance_at_entry"])
                stop_loss = float(message["stop_loss"])
                take_profit = float(message["liquidity_target"])
                fvg_id = message["fvg_id"]
                fvg_height = float(message["fvg_height"])
                reason = message["reason"]
                timeframe = message["timeframe"]
                fvg_direction = message["fvg_direction"]
                rr = float(message["rr"])
                signal_generated_at = message["signal_generated_at"]
                portfolio_decision_at= message["portfolio_decision_at"]
                technical_signal_id = message["signal_id"]
                signal_confidence = message.get("signal_confidence", 0)
                # Generate a unique execution ID
                execution_id = str(uuid.uuid4())

                # Simulate immediate order fill
                fill_price = entry_price  # In development, assume fill at entry price
                logger.info(f"Simulated order fill for {ticker}: {direction} {quantity} @ {fill_price}")
                # Determine order status
                status = "filled" if fill_price else "failed"
                
                # Prepare metadata
                metadata = {}
                
                # Insert into portfolio_positions table
                await self.insert_portfolio_position(
                    # execution_id,ticker,direction,status,fill_price,quantity,stop_loss,take_profit,fvg_id,fvg_height,reason,timeframe,fvg_direction,rr,account_balance_at_entry,signal_confidence,broker_order_id,timestamp,metadata
                    execution_id,ticker,direction,status,fill_price,quantity,stop_loss,take_profit,fvg_id,fvg_height,reason,timeframe,fvg_direction,rr,account_balance_at_entry,0,0,datetime.now(),metadata

                )

                # Prepare execution result
                execution_result = {
                    "event": "order_filled",
                    "execution_id": execution_id,
                    "symbol": ticker,
                    "status": "filled",
                    "fill_price": fill_price,
                    "position_size": quantity,
                    "direction": direction,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "fvg_id": fvg_id,
                    "fvg_height": fvg_height,
                    "reason": reason,
                    "timeframe": timeframe,
                    "fvg_direction": fvg_direction,
                    "rr": rr,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    # Add the following in production
                    "account_balance_at_entry":1000,
                    "signal_confidence": 0,
                    "broker_order_id":None,
                    "execution_time": datetime.now(timezone.utc).isoformat(),
                    "signal_generated_at":signal_generated_at,
                    "portfolio_decision_at":portfolio_decision_at,
                    "metadata": metadata,
                    "signal_id": technical_signal_id,
                    "signal_confidence": signal_confidence,
                }

                # Publish execution result to Redis
                logger.info(f"Publishing execution result: {execution_result}")
                self.redis_stream.publish(self.execution_results_channel, convert_decimals(execution_result))

            except Exception as e:
                logger.exception(f"Error processing order: {message} - {e}")

    async def insert_portfolio_position(self, execution_id,ticker,direction,status,fill_price,quantity,stop_loss,take_profit,fvg_id,fvg_height,reason,timeframe,fvg_direction,rr,account_balance_at_entry,signal_confidence,broker_order_id,timestamp,metadata):
        """Inserts a new position into the portfolio_positions table."""
        try:
            async with self.db_engine.begin() as conn:
                await conn.execute(
                    text("""
                         INSERT INTO execution_signals (
                             execution_id, ticker, direction,status,fill_price,position_size,stop_loss,take_profit,fvg_id,fvg_height,reason,timeframe,fvg_direction,rr,account_balance_at_entry,signal_confidence,broker_order_id,timestamp,metadata
                         ) VALUES (
                             :execution_id,:ticker,:direction,:status,:fill_price,:position_size,:stop_loss,:take_profit,:fvg_id,:fvg_height,:reason,:timeframe,:fvg_direction,:rr,:account_balance_at_entry,:signal_confidence,:broker_order_id,NOW(),:metadata
                         )
                         """),
                    {
                        "execution_id": execution_id,
                        "ticker": ticker,
                        "direction": direction,
                        "status": status,
                        "fill_price": fill_price,
                        "position_size": quantity,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "fvg_id": fvg_id,
                        "fvg_height": fvg_height,
                        "reason": reason,
                        "timeframe": timeframe,
                        "fvg_direction": fvg_direction,
                        "rr": rr,
                        "account_balance_at_entry": account_balance_at_entry,
                        "signal_confidence": signal_confidence,
                        "broker_order_id": broker_order_id,
                        "timestamp": timestamp,
                        "metadata": json.dumps(metadata) if metadata else None
                    }
                )
                logger.info(f"Inserted new position into portfolio_positions for {ticker} (Execution ID: {execution_id})")
        except Exception as e:
            logger.exception(f"Failed to insert position into portfolio_positions for {ticker}: {e}")
# --- Main execution ---
# async def main():
#     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#     agent = ExecutionAgent()
#     await agent.start()

# if __name__ == "__main__":
    # try:
    #     asyncio.run(main())
    # except KeyboardInterrupt:
    #     logger.info("Execution Agent stopped.")
    # except Exception as main_err:
    #     logger.exception(f"Execution Agent failed to start: {main_err}")