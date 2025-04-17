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

logger = logging.getLogger("core.redis_pubsub")

class RedisPubSub:
    def __init__(self, host="localhost", port=6379, db=0, settings_path=None):
        """Initialize the Redis connection and Pub/Sub instance."""
        self.redis = redis.StrictRedis(host=host, port=port, db=db, decode_responses=True)
        self.pubsub = self.redis.pubsub()

        # Determine the absolute path for settings.yaml
        if settings_path is None:
            settings_path = os.path.join(os.path.dirname(__file__), "../config/settings.yaml")

        # Load agent-specific channels from settings.yaml
        with open(settings_path, "r") as file:
            settings = yaml.safe_load(file)
        self.channels = settings["redis"]["channels"]
        logger.info("RedisPubSub initialized with channels: %s", self.channels)

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
            self.pubsub.subscribe(channel)
            for message in self.pubsub.listen():
                if message["type"] == "message":
                    logger.debug("Message received on channel '%s': %s", channel, message["data"])
                    callback(message["data"])

        # Run the listener in a separate thread
        thread = threading.Thread(target=listen, daemon=True)
        thread.start()

    def get_channel(self, agent_name):
        """Retrieve the Redis channel for a specific agent."""
        return self.channels.get(agent_name, None)