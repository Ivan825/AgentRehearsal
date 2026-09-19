"""Runtime configuration, read from environment (and a local .env if present)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env if it exists; environment variables already set take precedence.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
TARGET_MODEL_ID = os.getenv("AGENTREHEARSAL_TARGET_MODEL", "us.amazon.nova-lite-v1:0")
AUTHOR_MODEL_ID = os.getenv("AGENTREHEARSAL_AUTHOR_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
RUNS_DIR = Path(os.getenv("AGENTREHEARSAL_RUNS_DIR", "runs"))

# The principal name used in Cedar requests. One agent per project for now.
CEDAR_PRINCIPAL = 'Agent::"target"'

# Optional: AgentCore Gateway (Path B). When set and --tools gateway is used, the target agent's tools come from the
# Gateway over MCP and denials are made by AgentCore Policy rather than the local hook.
GATEWAY_URL = os.getenv("AGENTREHEARSAL_GATEWAY_URL", "")
GATEWAY_TOKEN = os.getenv("AGENTREHEARSAL_GATEWAY_TOKEN", "")
GATEWAY_TARGET = os.getenv("AGENTREHEARSAL_GATEWAY_TARGET", "SupportTools")

# Optional: DynamoDB run history
DDB_TABLE = os.getenv("AGENTREHEARSAL_DDB_TABLE", "")
