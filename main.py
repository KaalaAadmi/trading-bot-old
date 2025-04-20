from core.scheduler.apscheduler_config import start_scheduler
from agents.market_research.market_research_agent import MarketResearchAgent
from agents.ticker_updater.ticker_updater_agent import TickerUpdaterAgent
from agents.market_data_collector.data_collector_agent import DataCollectorAgent
import logging
import asyncio

# Initialize logger
logging.basicConfig(level=logging.INFO)

async def start_agents():
    """Start all agents in the correct order."""
    logging.info("Starting the Agentic Trading Bot...")

    # Initialize the TickerUpdaterAgent and trigger it to update tickers
    ticker_updater_agent = TickerUpdaterAgent()
    logging.info("Running the TickerUpdaterAgent to update tickers...")
    ticker_updater_agent.update_tickers()

    # Initialize and start the MarketResearchAgent
    market_research_agent = MarketResearchAgent()
    market_research_agent.subscribe_to_ticker_updates()  # Call the synchronous method directly

    # Initialize and start the DataCollectorAgent
    data_collector_agent = DataCollectorAgent()
    await data_collector_agent.start()

    logging.info("[main.py] Loop ID: %s", id(asyncio.get_running_loop()))

    # Start the scheduler and pass in the data_collector_agent
    start_scheduler(data_collector_agent)
    # start_scheduler()

    # Keep the application running
    while True:
        await asyncio.sleep(1)  # Prevent the script from exiting

if __name__ == "__main__":
    try:
        asyncio.run(start_agents())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Shutting down the Agentic Trading Bot...")