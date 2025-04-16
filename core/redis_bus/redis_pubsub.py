import redis
import threading

class RedisPubSub:
    def __init__(self, host="localhost", port=6379, db=0):
        """Initialize the Redis connection and Pub/Sub instance."""
        self.redis = redis.StrictRedis(host=host, port=port, db=db, decode_responses=True)
        self.pubsub = self.redis.pubsub()

    def publish(self, channel, message):
        """Publish a message to a specific channel."""
        self.redis.publish(channel, message)

    def subscribe(self, channel, callback):
        """
        Subscribe to a channel and process messages with a callback.

        Args:
            channel (str): The channel to subscribe to.
            callback (function): A function to handle incoming messages.
        """
        def listen():
            self.pubsub.subscribe(channel)
            for message in self.pubsub.listen():
                if message["type"] == "message":
                    callback(message["data"])

        # Run the listener in a separate thread
        thread = threading.Thread(target=listen, daemon=True)
        thread.start()