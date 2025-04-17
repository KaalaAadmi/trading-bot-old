import pytest
from agents.market_research.market_research_agent import MarketResearchAgent
from unittest.mock import patch, MagicMock

@pytest.fixture
def agent():
    """Fixture to initialize the MarketResearchAgent."""
    return MarketResearchAgent()

@patch("agents.market_research.market_research_agent.requests.get")
def test_integration_run(mock_get, agent):
    """Integration test for the run method."""
    # Mock the API response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "prices": [[1680000000000, 30000], [1680003600000, 30500]]
    }
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    agent.run()
    # Add assertions to verify Redis signals or database updates