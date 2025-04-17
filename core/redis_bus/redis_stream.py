import redis
import threading
import logging
import logging.config
import yaml
import os

# Ensure the logs directory exists
logs_dir = os.path.join(os.path.dirname(__file__), "../../logs")
os.makedirs(logs_dir, exist_ok=True)

# Load centralized logging configuration
logging_config_path = os.path.join(os.path.dirname(__file__), "../config/logging_config.yaml")
with open(logging_config_path, "r") as file:
    logging_config = yaml.safe_load(file)
logging.config.dictConfig(logging_config)

logger = logging.getLogger("core.redis_stream")

class RedisStream:
    def __init__(self, host="localhost", port=6379, db=0, settings_path=None):
        """Initialize the Redis connection and Stream instance."""
        self.redis = redis.StrictRedis(host=host, port=port, db=db, decode_responses=True)
        self.stream = self.redis.stream()

        # Determine the absolute path for settings.yaml
        if settings_path is None:
            settings_path = os.path.join(os.path.dirname(__file__), "../config/settings.yaml")

        # Load agent-specific channels from settings.yaml
        with open(settings_path, "r") as file:
            settings = yaml.safe_load(file)
        self.channels = settings["redis"]["channels"]
        logger.info("RedisStream initialized with channels: %s", self.channels)

    def publish(self, channel, message):
        """Publish a message to a specific channel."""
        logger.info("Publishing message to channel '%s': %s", channel, message)
        self.redis.publish(channel, message)

    def subscribe(self, channel, callback):
        """
        Subscribe to a channel and process messages with a callback.

        Args:
            channel (str): The channel to subscribe to.
            callback (function): A function to handle incoming messages.
        """
        logger.info("Subscribing to channel '%s'", channel)

        def listen():
            self.stream.subscribe(channel)
            for message in self.stream.listen():
                if message["type"] == "message":
                    logger.debug("Message received on channel '%s': %s", channel, message["data"])
                    callback(message["data"])

        # Run the listener in a separate thread
        thread = threading.Thread(target=listen, daemon=True)
        thread.start()

    def get_channel(self, agent_name):
        """Retrieve the Redis channel for a specific agent."""
        return self.channels.get(agent_name, None)

class RedisStream:
    def __init__(self, host="localhost", port=6379, db=0, settings_path=None):
        """Initialize the Redis connection."""
        self.redis = redis.StrictRedis(host=host, port=port, db=db, decode_responses=True)

        # Determine the absolute path for settings.yaml
        if settings_path is None:
            settings_path = os.path.join(os.path.dirname(__file__), "../config/settings.yaml")

        # Load agent-specific channels from settings.yaml
        with open(settings_path, "r") as file:
            settings = yaml.safe_load(file)
        self.channels = settings["redis"]["channels"]
        logger.info("RedisStream initialized with channels: %s", self.channels)

    def publish(self, stream, message, retention_ms=259200000):
        """
        Publish a message to a Redis Stream with a retention policy.

        Args:
            stream (str): The name of the Redis Stream.
            message (dict): The message to publish (key-value pairs).
            retention_ms (int): Retention period in milliseconds (default: 3 days).
        """
        logger.info("Publishing message to stream '%s': %s", stream, message)
        self.redis.xadd(stream, message, maxlen=1000, approximate=True)  # Retain up to 1000 messages

    def subscribe(self, stream, callback, last_id="0-0"):
        """
        Subscribe to a Redis Stream and process messages with a callback.

        Args:
            stream (str): The name of the Redis Stream.
            callback (function): A function to handle incoming messages.
            last_id (str): The ID of the last processed message (default: "0-0").
        """
        logger.info("Subscribing to stream '%s' from ID '%s'", stream, last_id)

        def listen(last_id=last_id):  # Pass last_id as a default argument
            while True:
                try:
                    messages = self.redis.xread({stream: last_id}, block=0)
                    for stream_name, entries in messages:
                        for entry_id, entry_data in entries:
                            logger.debug("Message received on stream '%s': %s", stream, entry_data)
                            callback(entry_data)
                            last_id = entry_id  # Update the last processed ID
                except Exception as e:
                    logger.error("Error while listening to stream '%s': %s", stream, str(e))

        # Run the listener in a separate thread
        thread = threading.Thread(target=listen, daemon=True)
        thread.start()

    def get_channel(self, agent_name):
        """Retrieve the Redis stream for a specific agent."""
        return self.channels.get(agent_name, None)