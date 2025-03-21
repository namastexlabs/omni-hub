"""
Evolution API Client for WhatsApp integration.

This module provides a client for interacting with the Evolution API
for WhatsApp messaging through RabbitMQ.
"""

import logging
import json
import pika
from enum import Enum, auto
from typing import Dict, Any, List, Optional, Callable, Union
from pydantic import BaseModel
import time
import random

# Configure logging
logger = logging.getLogger("src.channels.whatsapp.evolution_api_client")

class EventType(str, Enum):
    """Event types supported by Evolution API."""
    MESSAGES_UPSERT = "messages.upsert"
    MESSAGES_UPDATE = "messages.update"
    MESSAGES_DELETE = "messages.delete"
    CONTACTS_SET = "contacts.set"
    CONTACTS_UPDATE = "contacts.update"
    PRESENCE_UPDATE = "presence.update"
    CHATS_SET = "chats.set"
    CHATS_UPDATE = "chats.update"
    CONNECTION_UPDATE = "connection.update"
    GROUPS_UPSERT = "groups.upsert"
    GROUPS_UPDATE = "groups.update"
    GROUP_PARTICIPANTS_UPDATE = "group-participants.update"
    STATUS_UPDATE = "status.update"

class RabbitMQConfig(BaseModel):
    """Configuration for RabbitMQ connection."""
    uri: str
    exchange_name: str = "evolution_exchange"
    instance_name: str
    global_mode: bool = False
    events: List[EventType]
    api_key: Optional[str] = None  # API key for Evolution API authentication if needed
    # Connection settings
    heartbeat: int = 30  # Heartbeat interval in seconds
    connection_attempts: int = 3  # Number of connection attempts
    retry_delay: int = 5  # Delay between connection attempts in seconds

class EvolutionAPIClient:
    """Client for interacting with Evolution API via RabbitMQ."""
    
    def __init__(self, config: RabbitMQConfig):
        """Initialize the Evolution API client.
        
        Args:
            config: RabbitMQ configuration
        """
        self.config = config
        self.connection = None
        self.channel = None
        self.event_handlers: Dict[EventType, List[Callable[[Dict[str, Any]], None]]] = {
            event_type: [] for event_type in EventType
        }
        self._consumer_tag = None
        self.queue_name = None
        self.is_consuming = False
        self.reconnect_delay = 0  # Initial reconnect delay
        self.max_reconnect_delay = 300  # Maximum reconnect delay (5 minutes)
    
    def connect(self) -> bool:
        """Connect to RabbitMQ.
        
        Returns:
            bool: True if connected successfully, False otherwise
        """
        try:
            # Close existing connection if any
            if self.connection and self.connection.is_open:
                logger.debug("Closing existing connection")
                self.connection.close()
            
            # Create a new connection
            logger.info(f"Connecting to RabbitMQ at {self.config.uri}")
            parameters = pika.URLParameters(self.config.uri)
            parameters.heartbeat = self.config.heartbeat
            parameters.connection_attempts = self.config.connection_attempts
            parameters.retry_delay = self.config.retry_delay
            
            # Add connection blocked/unblocked callbacks
            self.connection = pika.BlockingConnection(parameters)
            self.connection.add_on_connection_blocked_callback(self._on_connection_blocked)
            self.connection.add_on_connection_unblocked_callback(self._on_connection_unblocked)
            
            # Create a channel
            self.channel = self.connection.channel()
            
            # Declare the exchange
            self.channel.exchange_declare(
                exchange=self.config.exchange_name,
                exchange_type='topic',
                durable=True
            )
            
            # Strategy 1: Use our application-specific queue
            app_queue_name = f"evolution-api-{self.config.instance_name}"
            
            # Strategy 2: Try to also consume from the instance-specific queues that already exist
            # Based on the RabbitMQ management UI, these are the queues we should be listening to
            for event in self.config.events:
                # Get the string value of the event enum
                event_value = event.value if isinstance(event, EventType) else str(event)
                # These are the exact queue names seen in RabbitMQ management UI
                instance_queue_name = f"evolution.{event_value}"
                
                try:
                    # Declare queue if it doesn't exist (passive=False) or just get it if it does
                    queue_result = self.channel.queue_declare(queue=instance_queue_name, durable=True, passive=True)
                    logger.info(f"Found existing queue: {instance_queue_name}")
                    
                    # Consume from this queue directly
                    self.channel.basic_consume(
                        queue=instance_queue_name,
                        on_message_callback=self._on_message,
                        auto_ack=True
                    )
                    logger.info(f"Now consuming from instance queue: {instance_queue_name}")
                except Exception as e:
                    logger.warning(f"Couldn't consume from queue {instance_queue_name}: {e}")
            
            # Still set up our app queue with catch-all bindings as a fallback
            result = self.channel.queue_declare(queue=app_queue_name, exclusive=False)
            self.queue_name = result.method.queue
            
            # Try different binding patterns to increase chances of receiving messages
            for event in self.config.events:
                # Get the string value of the event enum
                event_value = event.value if isinstance(event, EventType) else str(event)
                # Pattern 1: Standard instance.event pattern
                routing_key = f"evolution.{event_value}"
                self.channel.queue_bind(
                    exchange=self.config.exchange_name,
                    queue=self.queue_name,
                    routing_key=routing_key
                )
                logger.info(f"Bound queue to routing key: {routing_key}")
            
            # Pattern 2: All events for this instance
            routing_key = "evolution.*"
            self.channel.queue_bind(
                exchange=self.config.exchange_name,
                queue=self.queue_name,
                routing_key=routing_key
            )
            logger.info(f"Bound queue to routing key: {routing_key}")
            
            # Pattern 3: Catch-all binding
            routing_key = "#"
            self.channel.queue_bind(
                exchange=self.config.exchange_name,
                queue=self.queue_name,
                routing_key=routing_key
            )
            logger.info(f"Bound queue to routing key: {routing_key} (catch-all)")
            
            # Reset reconnect delay on successful connection
            self.reconnect_delay = 0
            from urllib.parse import urlparse
            # Parse the URI to extract only the host and port, hiding credentials
            parsed_uri = urlparse(self.config.uri)
            safe_uri = f"{parsed_uri.scheme}://{parsed_uri.hostname}:{parsed_uri.port}"
            logger.info(f"Connected to RabbitMQ at {safe_uri}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            # Implement exponential backoff for reconnection
            self._increase_reconnect_delay()
            return False
    
    def _on_connection_blocked(self, connection, reason):
        """Called when the connection is blocked by RabbitMQ."""
        logger.warning(f"Connection blocked: {reason}")
    
    def _on_connection_unblocked(self, connection):
        """Called when the connection is unblocked by RabbitMQ."""
        logger.info("Connection unblocked")
    
    def _increase_reconnect_delay(self):
        """Increase the reconnect delay with exponential backoff."""
        if self.reconnect_delay == 0:
            self.reconnect_delay = self.config.retry_delay
        else:
            self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)
            # Add jitter to avoid thundering herd problem
            jitter = random.uniform(0, 0.1 * self.reconnect_delay)
            self.reconnect_delay += jitter
            
        logger.info(f"Next reconnection attempt in {self.reconnect_delay:.1f} seconds")
    
    def reconnect(self) -> bool:
        """Attempt to reconnect to RabbitMQ with exponential backoff."""
        # Wait before reconnecting
        if self.reconnect_delay > 0:
            logger.info(f"Waiting {self.reconnect_delay:.1f} seconds before reconnecting...")
            time.sleep(self.reconnect_delay)
        
        # Try to reconnect
        logger.info("Attempting to reconnect to RabbitMQ...")
        return self.connect()
    
    def ensure_connection(self) -> bool:
        """Ensure we have a valid connection to RabbitMQ."""
        if self.connection and self.connection.is_open:
            # Make sure the channel is still valid by checking it
            try:
                # Simple no-op to check if channel is still good
                self.channel.exchange_declare(
                    exchange=self.config.exchange_name,
                    exchange_type='topic',
                    durable=True,
                    passive=True  # Just check if it exists, don't create
                )
                return True
            except Exception as e:
                logger.warning(f"Channel check failed: {e}")
                return self.reconnect()
        else:
            return self.reconnect()
    
    def subscribe(self, event_type: EventType, callback: Callable[[Dict[str, Any]], None]):
        """Subscribe to an event type.
        
        Args:
            event_type: Event type to subscribe to
            callback: Callback function to call when the event is received
        """
        self.event_handlers[event_type].append(callback)
        logger.info(f"Subscribed to {event_type}")
    
    def _on_message(self, ch, method, properties, body):
        """Handle incoming messages from RabbitMQ.
        
        Args:
            ch: Channel
            method: Method
            properties: Properties
            body: Message body
        """
        try:
            # Log routing key for debugging
            logger.info(f"Received message with routing key: {method.routing_key}")
            
            # Parse the message
            try:
                message = json.loads(body.decode('utf-8'))
                logger.debug(f"Message content: {message}")
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode message as JSON: {body}")
                # Try to handle it as a raw string message
                message = {"raw_content": body.decode('utf-8', errors='replace'), "event": method.routing_key}
            
            # Try different approaches to extract the event type
            event = None
            
            # Approach 1: Direct event property
            if "event" in message:
                event = message.get("event")
            
            # Approach 2: Extract from routing key if no event property
            if not event and "." in method.routing_key:
                event = method.routing_key.split(".", 1)[1]
            
            # Approach 3: Default to messages.upsert for WhatsApp messages
            if not event and "message" in message or "messages" in message:
                event = "messages.upsert"
            
            logger.info(f"Identified event type: {event}")
            
            # Call the appropriate handlers
            if event and event in EventType.__members__.values():
                event_type = EventType(event)
                for handler in self.event_handlers[event_type]:
                    logger.info(f"Calling handler for event type: {event_type}")
                    handler(message)
            else:
                # If we still couldn't identify the event or it's not in our defined types,
                # try handling it with any handlers that might be interested
                logger.warning(f"Unknown or missing event type: {event}. Using fallback handlers.")
                
                # Fallback: try messages.upsert handlers for any WhatsApp-related messages
                for handler in self.event_handlers[EventType.MESSAGES_UPSERT]:
                    logger.info(f"Calling fallback handler for event: {EventType.MESSAGES_UPSERT}")
                    handler(message)
        
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
    
    def start_consuming(self):
        """Start consuming messages from RabbitMQ."""
        if not self.ensure_connection():
            logger.error("Not connected to RabbitMQ")
            return False
        
        try:
            # We may have already set up consumption for instance-specific queues
            # This just ensures we're also consuming from our app-specific queue
            self._consumer_tag = self.channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self._on_message,
                auto_ack=True
            )
            
            logger.info(f"Started consuming messages from queue: {self.queue_name}")
            self.is_consuming = True
            
            # Start consuming in a loop that handles connection issues
            while self.is_consuming:
                try:
                    self.connection.process_data_events(time_limit=1)  # Process events but allow for loop to run
                    time.sleep(0.1)  # Small sleep to prevent CPU hogging
                except pika.exceptions.AMQPError as e:
                    logger.error(f"AMQP error while consuming: {e}")
                    if self.ensure_connection():
                        logger.info("Reconnected to RabbitMQ after error")
                    else:
                        logger.error("Failed to reconnect to RabbitMQ after error")
                        time.sleep(5)  # Wait a bit before retry
                except Exception as e:
                    logger.error(f"Unexpected error while consuming: {e}", exc_info=True)
                    time.sleep(5)  # Wait a bit before retry
            
            return True
        
        except Exception as e:
            logger.error(f"Error starting to consume messages: {e}")
            return False
    
    def stop(self):
        """Stop consuming messages and close the connection."""
        self.is_consuming = False
        try:
            if self.channel and self.channel.is_open:
                if self._consumer_tag:
                    self.channel.basic_cancel(self._consumer_tag)
                self.channel.stop_consuming()
            
            if self.connection and self.connection.is_open:
                self.connection.close()
            
            logger.info("Stopped consuming messages and closed connection")
        
        except Exception as e:
            logger.error(f"Error stopping client: {e}") 