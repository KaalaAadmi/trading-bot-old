from core.scheduler.apscheduler_config import start_scheduler
from agents.market_research.market_research_agent import MarketResearchAgent
from agents.ticker_updater.ticker_updater_agent import TickerUpdaterAgent
import logging
import os

# Initialize logger
logging.basicConfig(level=logging.INFO)

def ensure_tickers_file():
    """Ensure that the tickers.json file exists by running the TickerUpdaterAgent if necessary."""
    ticker_file_path = "data/tickers.json"
    if not os.path.exists(ticker_file_path):
        logging.info("tickers.json file not found. Running TickerUpdaterAgent to generate it...")
        ticker_updater = TickerUpdaterAgent()
        ticker_updater.update_tickers()
    else:
        logging.info("tickers.json file already exists. Proceeding with MarketResearchAgent.")

if __name__ == "__main__":
    logging.info("Starting the Agentic Trading Bot...")

    # Start the MarketResearchAgent subscription
    market_research_agent = MarketResearchAgent()
    market_research_agent.subscribe_to_ticker_updates()
    
    # Ensure tickers.json is available
    ensure_tickers_file()

    # Start the scheduler
    start_scheduler()

    # Keep the application running
    try:
        while True:
            pass
    except (KeyboardInterrupt, SystemExit):
        logging.info("Shutting down the Agentic Trading Bot...")