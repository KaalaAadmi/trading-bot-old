from core.scheduler.apscheduler_config import start_scheduler
from agents.market_research.market_research_agent import MarketResearchAgent
from agents.ticker_updater.ticker_updater_agent import TickerUpdaterAgent
from agents.market_data_collector.data_collector_agent import DataCollectorAgent
from agents.technical_analysis.technical_analysis_agent import TechnicalAnalysisAgent
from agents.portfolio_manager.portfolio_manager_agent import PortfolioManagerAgent
from agents.execution.execution_agent import ExecutionAgent
from agents.position_tracker.position_tracker_agent import PositionTrackerAgent
from agents.journaling.journaling_agent import JournalingAgent
from agents.performance_measurer.performance_measurer_agent import PerformanceMeasurerAgent  # Import the agent
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

    # Initialize and start the TechnicalAnalysisAgent
    technical_analysis_agent = TechnicalAnalysisAgent()
    await technical_analysis_agent.start()
    
    # Initialize and start the PortfolioManagerAgent
    portfolio_manager_agent = PortfolioManagerAgent()
    await portfolio_manager_agent.start()

    # Initialize and start the ExecutionAgent
    execution_agent = ExecutionAgent()
    await execution_agent.start()

    # Initialize and start the PositionTrackerAgent
    position_tracker_agent = PositionTrackerAgent()
    await position_tracker_agent.start()

    # Initialize and start the JournalingAgent
    journaling_agent = JournalingAgent()
    await journaling_agent.start()

    # Initialize and start the PerformanceMeasurerAgent
    performance_measurer_agent = PerformanceMeasurerAgent()
    await performance_measurer_agent.start()
    
    logging.info("All agents started successfully.")
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