# Omnichannel Agent

AI agent integration for OmniChannels.

## Overview

This project implements an AI agent system that can integrate with various communication channels, starting with WhatsApp.

## Setup

1. Create a virtual environment: `python -m venv .venv`
2. Activate the virtual environment: `source .venv/bin/activate`
3. Install dependencies: `uv pip install -e .`

## Configuration

Copy the `.env.example` file to `.env` and fill in the required configuration values:

```bash
cp .env.example .env
```

Then edit the `.env` file to set your specific configuration:

```
# RabbitMQ Configuration
RABBITMQ_URI=amqp://user:password@localhost:5672/default
RABBITMQ_EXCHANGE=evolution_exchange
WHATSAPP_INSTANCE=Personal

# Agent API Configuration
AGENT_API_URL=http://localhost:8000
AGENT_API_KEY=your_api_key
DEFAULT_AGENT_NAME=default

# Evolution Transcript API Configuration
EVOLUTION_TRANSCRIPT_API=http://localhost:8001/api
EVOLUTION_TRANSCRIPT_API_KEY=your_api_key

# Logging Configuration
LOG_LEVEL=DEBUG
```

### WhatsApp Integration with Evolution API

This project integrates with the Evolution API for WhatsApp messaging. The integration uses RabbitMQ for message queuing. Key configuration parameters:

- `RABBITMQ_URI`: URI for connecting to RabbitMQ (e.g., `amqp://user:password@localhost:5672/default`)
- `RABBITMQ_EXCHANGE`: Exchange name for RabbitMQ (default: `evolution_exchange`)
- `WHATSAPP_INSTANCE`: Name of the WhatsApp instance in Evolution API (e.g., `Personal`)

Note: The Evolution API creates RabbitMQ queues with the prefix "evolution." (e.g., "evolution.messages.upsert").

## Running the Application

```bash
python -m src.cli.main
```

## Development

This project uses `uv` as the package manager. To add new dependencies:

```bash
uv add <package-name>
```

## Project Structure

- `src/` - Main source code directory
  - `agent/` - Agent implementation
  - `channels/` - Communication channel integrations
  - `db/` - Database models and repositories
- `tests/` - Test directory (to be implemented) 