import logging
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql import text
from core.redis_bus.redis_stream import RedisStream
from core.config.config_loader import load_settings

logger = logging.getLogger("agents.performance_measurer")

class PerformanceMeasurerAgent:
    def __init__(self, settings_path=None):
        self.settings = load_settings(settings_path)
        self.redis_stream = RedisStream()

        # Output stream for notifications or downstream agents
        self.performance_updates_channel = self.redis_stream.get_channel("performance_updates")

        db_cfg = self.settings["database"]
        self.db_engine = create_async_engine(
            f"postgresql+asyncpg://{db_cfg['user']}:{db_cfg['password']}@{db_cfg['host']}:{db_cfg['port']}/{db_cfg['db']}"
        )

    async def start(self):
        logger.info("Starting Performance Measurer Agent...")
        while True:
            try:
                # Periodically calculate performance metrics
                await self.calculate_performance_metrics()
            except Exception as e:
                logger.exception(f"Error in performance measurement loop: {e}")

            # Sleep for a configured interval before recalculating
            await asyncio.sleep(self.settings.get("performance_measurer", {}).get("interval_seconds", 3600))

    async def calculate_performance_metrics(self):
        """Calculates and stores performance metrics."""
        try:
            async with self.db_engine.connect() as conn:
                # Fetch closed trades from the journal table
                result = await conn.execute(
                    text("""
                        SELECT pnl, rr, status, entry_timestamp, exit_timestamp, max_drawdown_pct
                        FROM journal
                        WHERE status = 'CLOSED'
                    """)
                )
                trades = result.mappings().all()

            if not trades:
                logger.info("No closed trades found in the journal table.")
                return

            # Calculate metrics
            total_trades = len(trades)
            winning_trades = [t for t in trades if t["pnl"] > 0]
            losing_trades = [t for t in trades if t["pnl"] <= 0]

            win_rate = len(winning_trades) / total_trades * 100 if total_trades > 0 else 0
            avg_rr = sum(t["rr"] for t in trades if t["rr"]) / total_trades if total_trades > 0 else 0
            profit_factor = sum(t["pnl"] for t in winning_trades) / abs(sum(t["pnl"] for t in losing_trades)) if losing_trades else float("inf")
            total_pnl = sum(t["pnl"] for t in trades)
            max_drawdown = max(t["max_drawdown_pct"] for t in trades if t["max_drawdown_pct"] is not None)

            logger.info(f"Calculated Performance Metrics: Win Rate={win_rate:.2f}%, Avg RR={avg_rr:.2f}, Profit Factor={profit_factor:.2f}, Total PnL={total_pnl:.2f}, Max Drawdown={max_drawdown:.2f}%")

            # Store metrics in the performance_metrics table
            await self.store_performance_metrics(win_rate, avg_rr, profit_factor, total_pnl, max_drawdown)

            # Publish performance updates to Redis
            performance_update = {
                "event": "performance_metrics_updated",
                "win_rate": win_rate,
                "avg_rr": avg_rr,
                "profit_factor": profit_factor,
                "total_pnl": total_pnl,
                "max_drawdown": max_drawdown,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self.redis_stream.publish(self.performance_updates_channel, performance_update)

        except Exception as e:
            logger.exception(f"Error calculating performance metrics: {e}")

    async def store_performance_metrics(self, win_rate, avg_rr, profit_factor, total_pnl, max_drawdown):
        """Stores performance metrics in the performance_metrics table."""
        try:
            async with self.db_engine.begin() as conn:
                await conn.execute(
                    text("""
                        INSERT INTO performance_metrics (
                            metric_name, metric_value, recorded_at
                        ) VALUES
                            ('win_rate', :win_rate, NOW()),
                            ('avg_rr', :avg_rr, NOW()),
                            ('profit_factor', :profit_factor, NOW()),
                            ('total_pnl', :total_pnl, NOW()),
                            ('max_drawdown', :max_drawdown, NOW())
                    """),
                    {
                        "win_rate": win_rate,
                        "avg_rr": avg_rr,
                        "profit_factor": profit_factor,
                        "total_pnl": total_pnl,
                        "max_drawdown": max_drawdown
                    }
                )
                logger.info("Stored performance metrics in the database.")
        except Exception as e:
            logger.exception(f"Error storing performance metrics: {e}")

# --- Main execution ---
async def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    agent = PerformanceMeasurerAgent()
    await agent.start()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Performance Measurer Agent stopped.")
    except Exception as main_err:
        logger.exception(f"Performance Measurer Agent failed to start: {main_err}")