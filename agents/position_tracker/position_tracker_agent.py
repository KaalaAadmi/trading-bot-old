import logging
import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql import text
from core.redis_bus.redis_stream import RedisStream
from core.config.config_loader import load_settings
from agents.common.utils import convert_decimals

logger = logging.getLogger("agents.position_tracker")

class PositionTrackerAgent:
    def __init__(self, settings_path=None):
        self.settings = load_settings(settings_path)
        self.redis_stream = RedisStream()

        # Input stream from ExecutionAgent
        self.execution_results_channel = self.redis_stream.get_channel("execution_results")
        # Output stream for JournalingAgent or other downstream agents
        self.position_updates_channel = self.redis_stream.get_channel("position_updates")

        db_cfg = self.settings["database"]
        self.db_engine = create_async_engine(
            f"postgresql+asyncpg://{db_cfg['user']}:{db_cfg['password']}@{db_cfg['host']}:{db_cfg['port']}/{db_cfg['db']}"
        )

    async def start(self):
        logger.info("Starting Position Tracker Agent...")
        self.redis_stream.subscribe(
            self.execution_results_channel,
            self.process_execution_result,
            consumer_group="position_tracker_group",
            consumer_name="position_tracker_consumer"
        )
        logger.info(f"Subscribed to Redis stream: {self.execution_results_channel}")

        # Start monitoring open positions
        asyncio.create_task(self.monitor_positions())

        while True:
            await asyncio.sleep(60)  # Keep the agent running

    async def process_execution_result(self, message):
        """Processes execution results and tracks positions."""
        try:
            logger.info(f"Received execution result: {message}")

            # Validate required fields
            required_keys = ["execution_id", "symbol", "status", "fill_price", "position_size", "direction", "stop_loss", "take_profit"]
            if not all(key in message for key in required_keys):
                logger.warning(f"Execution result missing required keys: {message}. Skipping.")
                return

            execution_id = message["execution_id"]
            symbol = message["symbol"]
            status = message["status"]
            fill_price = Decimal(str(message["fill_price"]))
            position_size = Decimal(str(message["position_size"]))
            direction = message["direction"].upper()
            stop_loss = Decimal(str(message["stop_loss"]))
            take_profit = Decimal(str(message["take_profit"]))

            # Handle only filled orders
            if status != "filled":
                logger.info(f"Execution result status is not 'filled': {status}. Skipping.")
                return

            # Insert the new position into the portfolio_positions table
            await self.insert_position(
                execution_id, symbol, direction, fill_price, position_size, stop_loss, take_profit
            )

        except Exception as e:
            logger.exception(f"Error processing execution result: {message} - {e}")

    async def insert_position(self, execution_id, symbol, direction, fill_price, position_size, stop_loss, take_profit):
        """Inserts a new position into the portfolio_positions table."""
        try:
            async with self.db_engine.begin() as conn:
                await conn.execute(
                    text("""
                        INSERT INTO portfolio_positions (
                            execution_id, ticker, direction, entry_price, quantity,
                            stop_loss, take_profit, status, entry_timestamp
                        ) VALUES (
                            :execution_id, :ticker, :direction, :entry_price, :quantity,
                            :stop_loss, :take_profit, 'open', NOW()
                        )
                    """),
                    {
                        "execution_id": execution_id,
                        "ticker": symbol,
                        "direction": direction,
                        "entry_price": fill_price,
                        "quantity": position_size,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit
                    }
                )
                logger.info(f"Inserted new position into portfolio_positions for {symbol} (Execution ID: {execution_id})")
        except Exception as e:
            logger.exception(f"Failed to insert position into portfolio_positions for {symbol}: {e}")

    async def monitor_positions(self):
        """Periodically checks open positions and closes them if SL/TP is hit."""
        while True:
            try:
                async with self.db_engine.connect() as conn:
                    # Fetch all open positions
                    result = await conn.execute(
                        text("""
                            SELECT * FROM portfolio_positions
                            WHERE status = 'open'
                        """)
                    )
                    open_positions = result.mappings().all()

                # Check each position against live price data
                for position in open_positions:
                    await self.check_position(position)

            except Exception as e:
                logger.exception(f"Error monitoring positions: {e}")

            # Sleep for a configured interval before checking again
            await asyncio.sleep(self.settings.get("position_tracker", {}).get("monitor_interval", 60))

    async def check_position(self, position):
        """Checks if a position's SL or TP is hit and closes it if necessary."""
        try:
            ticker = position["ticker"]
            stop_loss = Decimal(str(position["stop_loss"]))
            take_profit = Decimal(str(position["take_profit"]))
            direction = position["direction"].upper()
            entry_price = Decimal(str(position["entry_price"]))
            quantity = Decimal(str(position["quantity"]))

            # Fetch the latest price for the ticker
            latest_price = await self.get_latest_price(ticker)
            if latest_price is None:
                logger.warning(f"Could not fetch latest price for {ticker}. Skipping position check.")
                return

            # Check if SL or TP is hit
            if direction == "BUY":
                if latest_price <= stop_loss:
                    await self.close_position(position, latest_price, "stop_loss_hit")
                elif latest_price >= take_profit:
                    await self.close_position(position, latest_price, "take_profit_hit")
            elif direction == "SELL":
                if latest_price >= stop_loss:
                    await self.close_position(position, latest_price, "stop_loss_hit")
                elif latest_price <= take_profit:
                    await self.close_position(position, latest_price, "take_profit_hit")

        except Exception as e:
            logger.exception(f"Error checking position {position}: {e}")

    async def close_position(self, position, exit_price, reason):
        """Closes a position and updates the database."""
        try:
            execution_id = position["execution_id"]
            entry_price = Decimal(str(position["entry_price"]))
            quantity = Decimal(str(position["quantity"]))
            pnl = (exit_price - entry_price) * quantity if position["direction"] == "BUY" else (entry_price - exit_price) * quantity

            async with self.db_engine.begin() as conn:
                # Update the position in the database
                await conn.execute(
                    text("""
                        UPDATE portfolio_positions
                        SET status = 'closed',
                            exit_price = :exit_price,
                            exit_timestamp = NOW(),
                            pnl = :pnl
                        WHERE execution_id = :execution_id
                    """),
                    {
                        "execution_id": execution_id,
                        "exit_price": exit_price,
                        "pnl": pnl
                    }
                )
                logger.info(f"Closed position for {position['ticker']} (Execution ID: {execution_id}). Reason: {reason}, PnL: {pnl}")

            # Publish the closed position to the position_updates stream
            position_update = {
                "event": reason,
                "execution_id": execution_id,
                "symbol": position["ticker"],
                "exit_price": float(exit_price),
                "pnl": float(pnl),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self.redis_stream.publish(self.position_updates_channel, convert_decimals(position_update))

        except Exception as e:
            logger.exception(f"Error closing position {position}: {e}")

    async def get_latest_price(self, ticker):
        """Fetches the latest price for a given ticker."""
        try:
            async with self.db_engine.connect() as conn:
                result = await conn.execute(
                    text("""
                        SELECT close FROM ohlcv_data
                        WHERE symbol = :ticker
                        ORDER BY timestamp DESC
                        LIMIT 1
                    """),
                    {"ticker": ticker}
                )
                row = result.fetchone()
                return Decimal(str(row["close"])) if row else None
        except Exception as e:
            logger.exception(f"Error fetching latest price for {ticker}: {e}")
            return None

# --- Main execution ---
async def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    agent = PositionTrackerAgent()
    await agent.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Position Tracker Agent stopped.")
    except Exception as main_err:
        logger.exception(f"Position Tracker Agent failed to start: {main_err}")