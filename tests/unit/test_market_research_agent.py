import pytest
import pandas as pd
from unittest.mock import patch, MagicMock, mock_open
from unittest import mock  # Import mock for mock.ANY
from agents.market_research.market_research_agent import MarketResearchAgent
import os

@pytest.fixture
def agent():
    """Fixture to initialize the MarketResearchAgent."""
    # Pass the absolute path to settings.yaml for testing
    settings_path = os.path.join(
        os.path.dirname(__file__), "../../core/config/settings.yaml"
    )
    return MarketResearchAgent(settings_path=settings_path)

@patch("builtins.open", new_callable=mock_open, read_data='{"coin50": ["bitcoin", "ethereum"]}')
def test_fetch_assets(mock_open, agent):
    """Test the fetch_assets method."""
    assets = agent.fetch_assets()
    assert assets == ["bitcoin", "ethereum"]
    mock_open.assert_called_once_with("data/tickers.json", "r")

@patch("agents.market_research.market_research_agent.yf.Ticker")
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

    df = agent.fetch_ohlcv("BTC")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "daily_returns"]
    assert df["daily_returns"].iloc[0] == (102 - 100) / 100
    assert df["daily_returns"].iloc[1] == (112 - 110) / 110

def test_filter_assets(agent):
    """Test the filter_assets method."""
    # Mock the settings to include coin50 and sp500 arrays
    agent.settings = {
        "tickers": {
            "coin50": ["BTC-EUR", "ETH-EUR"],
            "sp500": ["AAPL", "MSFT"]
        },
        "agents": {
            "market_research": {
                "volume_threshold": {
                    "stocks": 500000,
                    "crypto": 5000000
                },
                "volatility_threshold": 0.015,
                "price_change_threshold": 0.015,  # Not used for now
                "min_price": {
                    "stocks": 1,  # Not used for now
                    "crypto": 0.05  # Not used for now
                }
            }
        }
    }

    # Test data
    ohlcv_data = {
        "BTC-EUR": pd.DataFrame(
            {
                "open": [30000, 31000, 29000, 32000, 28000],
                "close": [31000, 29000, 32000, 28000, 33000],
                "volume": [6000000, 7000000, 8000000, 9000000, 10000000],  # Meets liquidity threshold
            }
        ),
        "ETH-EUR": pd.DataFrame(
            {
                "open": [2000, 2020, 2040, 2060, 2080],
                "close": [2020, 2040, 2060, 2080, 2100],
                "volume": [4000000, 4200000, 4400000, 4600000, 4800000],  # Below liquidity threshold
            }
        ),
    }

    # Add the price column (set to the close price)
    for asset, df in ohlcv_data.items():
        df["price"] = df["close"]

    # Add the daily_returns column to the test data
    for asset, df in ohlcv_data.items():
        df["daily_returns"] = (df["close"] - df["open"]) / df["open"]

    # Run the filter_assets method
    filtered_assets = agent.filter_assets(ohlcv_data)

    # Assertions
    assert isinstance(filtered_assets, list)
    assert len(filtered_assets) == 1  # Only BTC-EUR should pass
    assert "BTC-EUR" in filtered_assets
    assert "ETH-EUR" not in filtered_assets

@patch("agents.market_research.market_research_agent.create_engine")
def test_store_data(mock_engine, agent):
    """Test the store_data method."""
    mock_conn = MagicMock()
    mock_engine.return_value.connect.return_value = mock_conn

    df = pd.DataFrame({"timestamp": ["2023-01-01"], "price": [30000]})
    with patch("pandas.DataFrame.to_sql") as mock_to_sql:
        agent.store_data("bitcoin", df)
        mock_to_sql.assert_called_once_with(
            "ohlcv_data", agent.db_engine, if_exists="append", index=False
        )

@patch("agents.market_research.market_research_agent.MarketResearchAgent.fetch_assets")
@patch("agents.market_research.market_research_agent.MarketResearchAgent.fetch_ohlcv")
@patch("agents.market_research.market_research_agent.MarketResearchAgent.filter_assets")
@patch("agents.market_research.market_research_agent.MarketResearchAgent.store_data")
@patch("agents.market_research.market_research_agent.RedisPubSub.publish")
def test_run(mock_publish, mock_store, mock_filter, mock_fetch_ohlcv, mock_fetch_assets, agent):
    """Test the run method."""
    mock_fetch_assets.return_value = ["bitcoin", "ethereum"]
    mock_fetch_ohlcv.side_effect = lambda asset: pd.DataFrame(
        {"timestamp": ["2023-01-01"], "price": [30000]}
    )
    mock_filter.return_value = ["bitcoin"]

    agent.run()

    mock_fetch_assets.assert_called_once()
    mock_fetch_ohlcv.assert_called()
    mock_filter.assert_called_once()
    mock_store.assert_called_once_with("bitcoin", mock.ANY)
    mock_publish.assert_called_once_with(agent.channel, "Asset bitcoin passed screening.")