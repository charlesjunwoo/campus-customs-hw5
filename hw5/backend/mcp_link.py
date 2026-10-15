"""The team's only path to shop data: one MCP connection, built from the project's .mcp.json.

  * One `MCPToolset` (one stdio server process) is shared by all five agents.
  * Each agent sees only its role's tools (`tools_for(role)`): least privilege.
  * Every MCP call passes through `_audit_and_attribute`, which
      - stamps write tools with `requested_by = <calling agent>` (the model can't impersonate a role), and
      - appends the call, arguments, result preview, and duration to output/audit_trail.json.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastmcp import Client
from pydantic_ai import RunContext
from pydantic_ai.mcp import MCPToolset

import audit
from config import MCP_CONFIG, MCP_SERVER_NAME, MCP_TOOL_RETRIES, ROOT
from models import AgentName, TeamDeps

WRITE_TOOLS = {"submit_payment_request", "submit_purchase_order", "submit_price_quote", "save_draft",
               "record_ticket_decision", "decide_request"}  # agents are stamped with their own name, so never "human"

ROLE_TOOLS: dict[AgentName, set[str]] = {
    "boss": {"list_open_tickets", "get_ticket", "list_board"},
    "inventory": {"get_ticket", "check_inventory", "find_restock_vendor", "find_unpaid_invoices", "list_board",
                  "save_draft"},
    "accounting": {"get_ticket", "find_unpaid_invoices", "check_lease_obligations", "get_cash_position",
                   "get_pricing", "list_board", "submit_payment_request", "submit_purchase_order",
                   "submit_price_quote"},
    "facilities": {"get_ticket", "check_lease_obligations", "list_board", "save_draft"},
    "customer_service": {"get_ticket", "check_inventory", "list_board", "save_draft"},
}


def _server_config() -> dict[str, Any]:
    cfg = json.loads(MCP_CONFIG.read_text())
    server = cfg["mcpServers"][MCP_SERVER_NAME]
    server.setdefault("cwd", str(ROOT))  # .mcp.json paths are relative to the project root
    return {"mcpServers": {MCP_SERVER_NAME: server}}


async def _audit_and_attribute(ctx: RunContext[TeamDeps], call_tool, name: str, args: dict[str, Any]) -> Any:
    deps = ctx.deps
    if name in WRITE_TOOLS:
        args = {**args, "requested_by": deps.agent}
    started = time.perf_counter()
    try:
        result = await call_tool(name, args)
    except Exception as exc:
        await audit.log("mcp_call", run_id=deps.run_id, ticket_id=deps.ticket_id, agent=deps.agent, tool=name,
                        args=args, ok=False, error=str(exc), ms=round((time.perf_counter() - started) * 1000))
        raise
    await audit.log("mcp_call", run_id=deps.run_id, ticket_id=deps.ticket_id, agent=deps.agent, tool=name,
                    args=args, ok=True, result=audit.preview(result), ms=round((time.perf_counter() - started) * 1000))
    return result


TOOLSET = MCPToolset(Client(_server_config()), id=MCP_SERVER_NAME, process_tool_call=_audit_and_attribute,
                     max_retries=MCP_TOOL_RETRIES)


def tools_for(role: AgentName):
    allowed = ROLE_TOOLS[role]
    return TOOLSET.filtered(lambda ctx, tool_def: tool_def.name in allowed)


async def call(name: str, args: dict[str, Any]) -> Any:
    """Backend-initiated MCP call (outside any agent), e.g. recording the Boss's decision."""
    return await TOOLSET.direct_call_tool(name, args)
