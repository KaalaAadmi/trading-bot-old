from apscheduler.schedulers.background import BackgroundScheduler
from agents.ticker_updater.ticker_updater_agent import TickerUpdaterAgent
import logging

# Initialize logger
logger = logging.getLogger("core.scheduler")

def start_scheduler():
    """Start the APScheduler."""
    scheduler = BackgroundScheduler()
    ticker_updater = TickerUpdaterAgent()

    # Schedule the TickerUpdaterAgent to run daily at 23:59
    scheduler.add_job(
        ticker_updater.update_tickers,
        "cron",
        hour=23,
        minute=59,
        id="ticker_updater_job",
        name="Ticker Updater Agent",
    )
    logger.info("Scheduled TickerUpdaterAgent to run daily at 23:59.")

    # Start the scheduler
    scheduler.start()