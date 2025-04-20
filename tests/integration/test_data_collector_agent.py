import pytest
from unittest.mock import patch, AsyncMock
from agents.market_data_collector.data_collector_agent import DataCollectorAgent
import pandas as pd
import asyncio

@pytest.fixture
def agent():
    """Fixture to initialize the DataCollectorAgent."""
    return DataCollectorAgent()

@patch("agents.market_data_collector.data_collector_agent.yf.Ticker")
@patch("agents.market_data_collector.data_collector_agent.DataCollectorAgent.store_data", new_callable=AsyncMock)
@patch("agents.market_data_collector.data_collector_agent.DataCollectorAgent.publish_raw_data_event", new_callable=AsyncMock)
def test_integration_fetch_and_store(mock_publish, mock_store, mock_ticker, agent):
    """Integration test for fetching and storing OHLCV data."""
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

    # Run the fetch_and_store_ohlcv method
    asyncio.run(agent.fetch_and_store_ohlcv("AAPL"))

    # Verify that data was stored and events were published
    mock_store.assert_called()
    mock_publish.assert_called()