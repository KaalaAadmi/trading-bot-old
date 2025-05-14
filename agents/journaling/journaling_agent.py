import logging
import asyncio
import json
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql import text
from core.redis_bus.redis_stream import RedisStream
from core.config.config_loader import load_settings
from agents.common.utils import convert_decimals

logger = logging.getLogger("agents.journaling")

class JournalingAgent:
    def __init__(self, settings_path=None):
        self.settings = load_settings(settings_path)
        self.redis_stream = RedisStream()

        # Input stream from PositionTrackerAgent
        self.position_updates_channel = self.redis_stream.get_channel("position_updates")
        # Output stream for downstream agents (e.g., PerformanceAgent)
        self.journal_updates_channel = self.redis_stream.get_channel("journal_updates")

        db_cfg = self.settings["database"]
        self.db_engine = create_async_engine(
            f"postgresql+asyncpg://{db_cfg['user']}:{db_cfg['password']}@{db_cfg['host']}:{db_cfg['port']}/{db_cfg['db']}"
        )

    async def start(self):
        logger.info("Starting Journaling Agent...")
        self.redis_stream.subscribe(
            self.position_updates_channel,
            self.process_position_update,
            consumer_group="journaling_group",
            consumer_name="journaling_consumer"
        )
        logger.info(f"Subscribed to Redis stream: {self.position_updates_channel}")

        while True:
            await asyncio.sleep(60)  # Keep the agent running

    async def process_position_update(self, message):
        """Processes position updates and archives closed positions."""
        try:
            logger.info(f"Received position update: {message}")

            # Validate required fields
            required_keys = ["execution_id", "symbol", "exit_price", "pnl", "timestamp"]
            if not all(key in message for key in required_keys):
                logger.warning(f"Position update missing required keys: {message}. Skipping.")
                return

            execution_id = message["execution_id"]
            symbol = message["symbol"]
            exit_price = float(message["exit_price"])
            pnl = float(message["pnl"])
            timestamp = message["timestamp"]

            # Fetch the closed position from the portfolio_positions table
            position = await self.fetch_closed_position(execution_id)
            if not position:
                logger.warning(f"No closed position found for Execution ID: {execution_id}. Skipping.")
                return

            # Archive the position in the journal table
            await self.archive_position(position, exit_price, pnl, timestamp)

            # Optionally delete the position from the portfolio_positions table
            await self.delete_position(execution_id)

            # Publish the archived position to the journal_updates stream
            journal_update = {
                "event": "position_archived",
                "execution_id": execution_id,
                "symbol": symbol,
                "exit_price": exit_price,
                "pnl": pnl,
                "timestamp": timestamp
            }
            self.redis_stream.publish(self.journal_updates_channel, convert_decimals(journal_update))
            logger.info(f"Published journal update: {journal_update}")

        except Exception as e:
            logger.exception(f"Error processing position update: {message} - {e}")

    async def fetch_closed_position(self, execution_id):
        """Fetches a closed position from the portfolio_positions table."""
        try:
            async with self.db_engine.connect() as conn:
                result = await conn.execute(
                    text("""
                        SELECT * FROM portfolio_positions
                        WHERE execution_id = :execution_id AND status = 'closed'
                    """),
                    {"execution_id": execution_id}
                )
                row = result.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.exception(f"Error fetching closed position for Execution ID {execution_id}: {e}")
            return None

    async def archive_position(self, position, exit_price, pnl, timestamp):
        """Archives a closed position in the journal table."""
        try:
            async with self.db_engine.begin() as conn:
                await conn.execute(
                    text("""
                        INSERT INTO journal (
                            signal_id, execution_id, symbol, timeframe, direction,
                            entry_price, exit_price, position_size, pnl, pnl_pct,
                            stop_loss, take_profit, rr, signal_confidence,
                            account_balance_at_entry, account_balance_at_exit,
                            entry_timestamp, exit_timestamp, reason, metadata
                        ) VALUES (
                            :signal_id, :execution_id, :symbol, :timeframe, :direction,
                            :entry_price, :exit_price, :position_size, :pnl, :pnl_pct,
                            :stop_loss, :take_profit, :rr, :signal_confidence,
                            :account_balance_at_entry, :account_balance_at_exit,
                            :entry_timestamp, :exit_timestamp, :reason, :metadata
                        )
                    """),
                    {
                        "signal_id": position["signal_id"],
                        "execution_id": position["execution_id"],
                        "symbol": position["ticker"],
                        "timeframe": position.get("timeframe", "unknown"),
                        "direction": position["direction"],
                        "entry_price": position["entry_price"],
                        "exit_price": exit_price,
                        "position_size": position["quantity"],
                        "pnl": pnl,
                        "pnl_pct": (pnl / position["entry_price"]) * 100 if position["entry_price"] else None,
                        "stop_loss": position["stop_loss"],
                        "take_profit": position["take_profit"],
                        "rr": position.get("rr", None),
                        "signal_confidence": position.get("signal_confidence", None),
                        "account_balance_at_entry": position.get("account_balance_at_entry", None),
                        "account_balance_at_exit": position.get("account_balance_at_exit", None),
                        "entry_timestamp": position["entry_timestamp"],
                        "exit_timestamp": timestamp,
                        "reason": position.get("reason", "N/A"),
                        "metadata": json.dumps(position.get("metadata", {}))
                    }
                )
                logger.info(f"Archived position for Execution ID {position['execution_id']} in journal.")
        except Exception as e:
            logger.exception(f"Error archiving position for Execution ID {position['execution_id']}: {e}")

    async def delete_position(self, execution_id):
        """Deletes a closed position from the portfolio_positions table."""
        try:
            async with self.db_engine.begin() as conn:
                await conn.execute(
                    text("""
                        DELETE FROM portfolio_positions
                        WHERE execution_id = :execution_id
                    """),
                    {"execution_id": execution_id}
                )
                logger.info(f"Deleted position for Execution ID {execution_id} from portfolio_positions.")
        except Exception as e:
            logger.exception(f"Error deleting position for Execution ID {execution_id}: {e}")

# --- Main execution ---
async def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    agent = JournalingAgent()
    await agent.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Journaling Agent stopped.")
    except Exception as main_err:
        logger.exception(f"Journaling Agent failed to start: {main_err}")