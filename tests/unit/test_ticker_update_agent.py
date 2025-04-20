import pytest
from unittest.mock import patch, MagicMock, mock_open
import json
from agents.ticker_updater.ticker_updater_agent import TickerUpdaterAgent
import pandas as pd

@pytest.fixture
def agent():
    """Fixture to initialize the TickerUpdaterAgent."""
    return TickerUpdaterAgent(output_path="test_tickers.json")

@patch("agents.ticker_updater.ticker_updater_agent.requests.get")
@patch("agents.ticker_updater.ticker_updater_agent.pd.read_html")
def test_fetch_sp500_tickers(mock_read_html, mock_get, agent):
    """Test the fetch_sp500_tickers method."""
    # Mock the HTTP response
    mock_get.return_value.status_code = 200
    mock_get.return_value.text = "<html></html>"

    # Mock the pandas.read_html response
    mock_read_html.return_value = [pd.DataFrame({"Symbol": ["AAPL", "MSFT", "GOOGL"]})]

    tickers = agent.fetch_sp500_tickers()
    assert tickers == ["AAPL", "MSFT", "GOOGL"]
    mock_get.assert_called_once_with("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    mock_read_html.assert_called_once()

@patch("agents.ticker_updater.ticker_updater_agent.requests.get")
def test_fetch_coin50_tickers(mock_get, agent):
    """Test the fetch_coin50_tickers method."""
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"id": "bitcoin", "symbol": "btc"},
        {"id": "ethereum", "symbol": "eth"}
    ]
    mock_get.return_value = mock_response

    tickers = agent.fetch_coin50_tickers()
    assert tickers == ["BTC-USD", "ETH-USD"]
    mock_get.assert_called_once()

@patch("builtins.open", new_callable=mock_open)
@patch("os.makedirs")
@patch("agents.ticker_updater.ticker_updater_agent.TickerUpdaterAgent.fetch_sp500_tickers")
@patch("agents.ticker_updater.ticker_updater_agent.TickerUpdaterAgent.fetch_coin50_tickers")
@patch("agents.ticker_updater.ticker_updater_agent.RedisStream.publish")
def test_update_tickers(mock_publish, mock_fetch_coin50, mock_fetch_sp500, mock_makedirs, mock_open, agent):
    """Test the update_tickers method."""
    mock_fetch_sp500.return_value = ["AAPL", "MSFT"]
    mock_fetch_coin50.return_value = ["bitcoin", "ethereum"]

    agent.update_tickers()

    # Verify that the tickers.json file is updated
    mock_open.assert_called_once_with("test_tickers.json", "w")
    handle = mock_open()
    written_data = "".join(call.args[0] for call in handle.write.call_args_list)
    expected_data = {
        "sp500": ["AAPL", "MSFT"],
        "coin50": ["bitcoin", "ethereum"]
    }
    assert json.loads(written_data) == expected_data

    # Verify that the message was published to the Redis Stream
    mock_publish.assert_called_once_with(agent.channel, {"message": "Ticker update completed."})