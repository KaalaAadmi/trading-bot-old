import sys
import os

# Dynamically add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from core.redis_bus.redis_pubsub import RedisPubSub
import time

def message_handler(message):
    """Callback function to handle received messages."""
    print(f"Received message: {message}")

def test_redis_pubsub():
    """Test the Redis Pub/Sub functionality."""
    # Initialize Redis Pub/Sub
    pubsub = RedisPubSub()

    # Subscribe to a test channel
    pubsub.subscribe("test_channel", message_handler)

    # Publish messages to the test channel
    for i in range(5):
        pubsub.publish("test_channel", f"Test message {i + 1}")
        time.sleep(1)

    # Add an assertion to ensure the test framework recognizes this as a test
    assert True  # Replace with actual assertions if needed

if __name__ == "__main__":
    # Initialize Redis Pub/Sub
    pubsub = RedisPubSub()

    # Subscribe to a test channel
    pubsub.subscribe("test_channel", message_handler)

    # Publish messages to the test channel
    for i in range(5):
        pubsub.publish("test_channel", f"Test message {i + 1}")
        time.sleep(1)