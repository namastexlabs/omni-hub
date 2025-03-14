"""
Configuration management for Stan WhatsApp Agent.
Loads configuration from environment variables.
"""

import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from typing import Optional

# Load environment variables from .env file
load_dotenv()

class RabbitMQConfig(BaseModel):
    """RabbitMQ configuration."""
    uri: str = Field(default_factory=lambda: os.getenv("RABBITMQ_URI", ""))
    exchange_name: str = Field(default_factory=lambda: os.getenv("RABBITMQ_EXCHANGE", "evolution_exchange"))
    instance_name: str = Field(default_factory=lambda: os.getenv("WHATSAPP_INSTANCE", ""))
    global_mode: bool = False  # Always use instance-specific mode

class AgentApiConfig(BaseModel):
    """Agent API configuration."""
    url: str = Field(default_factory=lambda: os.getenv("AGENT_API_URL", "http://localhost:8000"))
    api_key: str = Field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    default_agent_name: str = Field(default_factory=lambda: os.getenv("DEFAULT_AGENT_NAME", "default"))

class EvolutionTranscriptConfig(BaseModel):
    """Evolution transcript API configuration."""
    api_url: str = Field(default_factory=lambda: os.getenv("EVOLUTION_TRANSCRIPT_API", ""))
    api_key: str = Field(default_factory=lambda: os.getenv("EVOLUTION_TRANSCRIPT_API_KEY", ""))

class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

class Config(BaseModel):
    """Main application configuration."""
    rabbitmq: RabbitMQConfig = RabbitMQConfig()
    agent_api: AgentApiConfig = AgentApiConfig()
    evolution_transcript: EvolutionTranscriptConfig = EvolutionTranscriptConfig()
    logging: LoggingConfig = LoggingConfig()
    
    @property
    def is_valid(self) -> bool:
        """Check if the configuration is valid."""
        return bool(self.rabbitmq.uri and self.rabbitmq.instance_name and 
                   self.agent_api.url and self.agent_api.api_key)

# Singleton instance
config = Config() 