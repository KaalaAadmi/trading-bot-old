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

    def subscribe(self, stream, callback, consumer_group="market_research_group", consumer_name="market_research_consumer"):
        """
        Subscribe to a Redis Stream using a consumer group and process messages with a callback.

        Args:
            stream (str): The name of the Redis Stream.
            callback (function): A function to handle incoming messages.
            consumer_group (str): The name of the consumer group.
            consumer_name (str): The name of the consumer within the group.
        """
        logger.info("Subscribing to stream '%s' with consumer group '%s' and consumer name '%s'.", stream, consumer_group, consumer_name)

        # Create the consumer group if it doesn't exist
        try:
            self.redis.xgroup_create(stream, consumer_group, id="0-0", mkstream=True)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP Consumer Group name already exists" in str(e):
                logger.info("Consumer group '%s' already exists for stream '%s'.", consumer_group, stream)
            else:
                raise

        def listen():
            while True:
                try:
                    # Read messages from the stream
                    messages = self.redis.xreadgroup(consumer_group, consumer_name, {stream: ">"}, count=1, block=0)
                    for stream_name, entries in messages:
                        for entry_id, entry_data in entries:
                            logger.debug("Message received on stream '%s': %s", stream, entry_data)
                            callback(entry_data)
                            # Acknowledge the message
                            self.redis.xack(stream, consumer_group, entry_id)
                            logger.info("Acknowledged message ID '%s' on stream '%s'.", entry_id, stream)
                            return  # Stop listening after processing one message
                except Exception as e:
                    logger.error("Error while listening to stream '%s': %s", stream, str(e))

        # Run the listener in a separate thread
        thread = threading.Thread(target=listen, daemon=True)
        thread.start()

    def get_channel(self, agent_name):
        """Retrieve the Redis stream for a specific agent."""
        return self.channels.get(agent_name, None)