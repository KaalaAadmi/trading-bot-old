from core.scheduler.apscheduler_config import start_scheduler
from agents.market_research.market_research_agent import MarketResearchAgent
from agents.ticker_updater.ticker_updater_agent import TickerUpdaterAgent
import logging
import os
import time

# Initialize logger
logging.basicConfig(level=logging.INFO)

def ensure_tickers_file():
    """Ensure that the tickers.json file exists and run the TickerUpdaterAgent."""
    ticker_file_path = "data/tickers.json"
    ticker_updater = TickerUpdaterAgent()

    # Run the TickerUpdaterAgent regardless of whether tickers.json exists
    if not os.path.exists(ticker_file_path):
        logging.info("tickers.json file not found. Running TickerUpdaterAgent to generate it...")
    else:
        logging.info("tickers.json file exists. Running TickerUpdaterAgent to update it...")

    ticker_updater.update_tickers()

if __name__ == "__main__":
    logging.info("Starting the Agentic Trading Bot...")

    # Initialize the MarketResearchAgent and subscribe to ticker updates
    market_research_agent = MarketResearchAgent()
    market_research_agent.subscribe_to_ticker_updates()

    # Ensure tickers.json is available and run the TickerUpdaterAgent
    ensure_tickers_file()

    # Start the scheduler for daily execution
    start_scheduler()

    # Keep the application running
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logging.info("Shutting down the Agentic Trading Bot...")