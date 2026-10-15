"""Settings shared by every agent: model, gateway, paths, and the token/loop limits."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(find_dotenv(str(ROOT / ".env")) or find_dotenv(usecwd=True))  # nearest .env (project or a parent)

# --- model: gpt-6-luna only, via Portkey, Responses API (Chat Completions rejects tools on this model)
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
REASONING_EFFORT = "low"            # reasoning stays on; "low" keeps token use down
MAX_OUTPUT_TOKENS = 4_000           # per model response, reasoning tokens included

# --- paths
MCP_CONFIG = ROOT / ".mcp.json"
MCP_SERVER_NAME = "campus-customs"
DB_ORIGINAL = ROOT / "data" / "campus_customs_original.db"
DB_WORKING = ROOT / "data" / "campus_customs_new.db"
AUDIT_TRAIL = ROOT / "output" / "audit_trail.json"
PROMPTS = Path(__file__).resolve().parent / "prompts"

# --- loop and token budgets
MAX_DELEGATION_DEPTH = 2            # boss (0) -> specialist (1) -> peer (2); depth-2 agents cannot delegate
MAX_DELEGATIONS_PER_TICKET = 8
TICKET_REQUEST_LIMIT = 40           # model requests per ticket, whole team combined
TICKET_TOKEN_LIMIT = 250_000        # tokens per ticket, whole team combined
AGENT_REQUEST_LIMIT = 10            # model requests in one agent run
AGENT_TOOL_CALL_LIMIT = 14          # tool calls in one agent run
AGENT_TOKEN_LIMIT = 80_000          # tokens in one agent run
MCP_TOOL_RETRIES = 1                # a failed MCP call is shown to the model once more, then the run fails
AUDIT_PREVIEW_CHARS = 1_500         # tool results are truncated to this length in the audit trail


def portkey_api_key() -> str:
    key = os.getenv("PORTKEY_API_KEY")
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is not set (expected in the project's or a parent folder's .env).")
    return key
