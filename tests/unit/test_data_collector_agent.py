import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from agents.market_data_collector.data_collector_agent import DataCollectorAgent
import pandas as pd 
import asyncio

@pytest.fixture
def agent():
    """Fixture to initialize the DataCollectorAgent."""
    return DataCollectorAgent()

@patch("agents.market_data_collector.data_collector_agent.yf.Ticker")
def test_fetch_ohlcv(mock_ticker, agent):
    """Test the fetch_ohlcv method."""
    mock_ticker.return_value.history.return_value = pd.DataFrame(
        {
            "Date": ["2023-01-01", "2023-01-02"],
            "Open": [100, 110],
            "High": [105, 115],
            "Low": [95, 105],
            "Close": [102, 112],
            "Volume": [1000, 1200],
        }
    )

    df = agent.fetch_ohlcv("AAPL", "1h", 30)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]

@patch("agents.data_collector.data_collector_agent.DataCollectorAgent.store_data", new_callable=AsyncMock)
@patch("agents.data_collector.data_collector_agent.DataCollectorAgent.publish_raw_data_event", new_callable=AsyncMock)
def test_process_filtered_assets(mock_publish, mock_store, agent):
    """Test the process_filtered_assets method."""
    message = {"filtered_assets": '["AAPL", "MSFT"]'}
    asyncio.run(agent.process_filtered_assets(message))
    mock_store.assert_called()
    mock_publish.assert_called()

@patch("agents.market_data_collector.data_collector_agent.yf.Ticker")
@patch("agents.market_data_collector.data_collector_agent.DataCollectorAgent.store_data", new_callable=AsyncMock)
@patch("agents.market_data_collector.data_collector_agent.DataCollectorAgent.publish_raw_data_event", new_callable=AsyncMock)
def test_empty_database(mock_publish, mock_store, mock_ticker, agent):
    """Test the agent's behavior when the database is empty."""
    # Mock yfinance response
    mock_ticker.return_value.history.return_value = pd.DataFrame(
        {
            "Date": ["2023-01-01", "2023-01-02"],
            "Open": [100, 110],
            "High": [105, 115],
            "Low": [95, 105],
            "Close": [102, 112],
            "Volume": [1000, 1200],
        }
    )

    # Simulate an empty database by returning None for last fetched timestamp
    agent.get_last_fetched_timestamp = AsyncMock(return_value=None)

    # Run the fetch_and_store_ohlcv method
    asyncio.run(agent.process_ohlcv("AAPL"))

    # Verify that data was stored and events were published
    mock_store.assert_called()
    mock_publish.assert_called()