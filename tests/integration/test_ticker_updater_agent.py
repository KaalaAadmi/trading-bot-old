import pytest
import json
from agents.ticker_updater.ticker_updater_agent import TickerUpdaterAgent
from unittest.mock import patch, mock_open

@pytest.fixture
def agent():
    """Fixture to initialize the TickerUpdaterAgent."""
    return TickerUpdaterAgent(output_path="test_tickers.json")

@patch("builtins.open", new_callable=mock_open)
@patch("os.makedirs")
def test_integration_update_tickers(mock_makedirs, mock_open, agent):
    """Integration test for the update_tickers method."""
    # Mock the fetch methods
    with patch.object(agent, "fetch_sp500_tickers", return_value=["AAPL", "MSFT"]), \
         patch.object(agent, "fetch_coin50_tickers", return_value=["bitcoin", "ethereum"]):
        agent.update_tickers()

    # Verify that the tickers.json file is updated
    mock_open.assert_called_once_with("test_tickers.json", "w")
    handle = mock_open()

    # Capture all write calls and reconstruct the written content
    written_data = "".join(call.args[0] for call in handle.write.call_args_list)

    # Verify the written content matches the expected JSON
    expected_data = {
        "sp500": ["AAPL", "MSFT"],
        "coin50": ["bitcoin", "ethereum"]
    }
    assert json.loads(written_data) == expected_data