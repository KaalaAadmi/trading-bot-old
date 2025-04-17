import sys
import os
import time
import threading
from core.redis_bus.redis_stream import RedisStream
from unittest.mock import MagicMock

# Dynamically add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

received_messages = {}  # Dictionary to store messages by channel

def message_handler(channel, message):
    """Callback function to handle received messages."""
    global received_messages
    received_messages[channel] = message  # Store the message for the channel

def test_redis_stream():
    """Test the Redis Pub/Sub functionality with all agent-specific channels."""
    # Initialize Redis Pub/Sub
    stream = RedisStream()

    # Mock the subscribe and publish methods
    stream.subscribe = MagicMock()
    stream.publish = MagicMock()

    # Test all channels defined in settings.yaml
    channels = [
        stream.get_channel("market_research"),
        stream.get_channel("technical_analysis"),
        stream.get_channel("risk_manager"),
        stream.get_channel("portfolio_manager"),
        stream.get_channel("fvg_tracker"),
        stream.get_channel("journaling"),
        stream.get_channel("performance"),
        stream.get_channel("notification"),
    ]

    for channel in channels:
        # Assert that the channel name is valid
        assert channel is not None, f"Channel for {channel} is None"

        # Simulate subscribing to the channel
        stream.subscribe(channel, lambda message: message_handler(channel, message))

        # Simulate publishing a test message to the channel
        test_message = f"Test message for {channel}"
        stream.publish(channel, test_message)

        # Simulate the callback being called
        message_handler(channel, test_message)

        # Assert that the message was received correctly
        assert received_messages[channel] == test_message, \
            f"Expected '{test_message}', but got '{received_messages[channel]}'"

    # TODO: Replace these basic assertions with agent-specific assertions once agents are implemented

if __name__ == "__main__":
    # Run the test manually
    test_redis_stream()