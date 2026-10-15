"""Boss agent: reads each ticket, delegates to specialists, and makes the final call.

MCP tools: list_open_tickets, get_ticket, list_board (+ `delegate` to any specialist)
Writes:    nothing directly. The backend records the BossDecision via MCP `record_ticket_decision`.
Prompt:    prompts/boss.md
"""

from __future__ import annotations

from pydantic_ai import Agent, ModelRetry, RunContext

import mcp_link
from agents.base import REGISTRY, SETTINGS, delegate, model, prompt, runtime_context, tool_evidence
from models import BossDecision, TeamDeps

CUSTOMER_FACING = {"customer_order", "price_override"}  # tickets whose requester is a customer


async def validate_decision(ctx: RunContext[TeamDeps], out: BossDecision) -> BossDecision:
    out.ticket_id = ctx.deps.ticket_id
    problems = []

    names, _, _ = tool_evidence(ctx)
    if "delegate" not in names:
        problems.append("You must delegate to at least one specialist before deciding.")

    board = await mcp_link.call("list_board", {"ticket_id": out.ticket_id})
    approvals = {r["id"]: r for r in board["approval_requests"]}
    drafts = {r["id"] for r in board["drafts"]}
    ticket = (await mcp_link.call("get_ticket", {"ticket_id": out.ticket_id}))["ticket"]
    if ticket["type"] in CUSTOMER_FACING and not any(d["audience"] == "customer" for d in board["drafts"]):
        problems.append(f"Ticket {out.ticket_id} is a {ticket['type']} from {ticket['requester']}: delegate to "
                        "customer_service to draft their update before you decide. A customer is never left without a reply.")
    if missing_drafts := [i for i in drafts if i not in out.draft_ids]:
        problems.append(f"Drafts {missing_drafts} for this ticket are missing from draft_ids.")
    if bad := [i for i in out.approval_ids if i not in approvals]:
        problems.append(f"approval_ids {bad} are not on the board for ticket {out.ticket_id}.")
    if bad := [i for i in out.draft_ids if i not in drafts]:
        problems.append(f"draft_ids {bad} are not on the board for ticket {out.ticket_id}.")
    pending = [i for i, r in approvals.items() if r["status"] == "pending_human"]
    if out.decision == "resolved" and pending:
        problems.append(f"Approval requests {pending} are still pending a human, so the ticket is not resolved.")
    if missing := [i for i in pending if i not in out.approval_ids]:
        problems.append(f"Pending approval requests {missing} for this ticket are missing from approval_ids.")

    if problems:
        raise ModelRetry("Fix your decision:\n- " + "\n- ".join(problems))
    return out


AGENT: Agent[TeamDeps, BossDecision] = Agent(
    model(), name="boss", deps_type=TeamDeps, output_type=BossDecision,
    instructions=[prompt("boss"), runtime_context], toolsets=[mcp_link.tools_for("boss")], tools=[delegate],
    # One hand-off per model turn: the Boss must read each specialist's report before routing the next
    # (e.g. Facilities verifies the lease before Accounting prepares the rent payment).
    model_settings={**SETTINGS, "parallel_tool_calls": False}, retries=2)
AGENT.output_validator(validate_decision)
REGISTRY["boss"] = AGENT
