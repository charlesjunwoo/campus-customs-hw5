"""Machinery every agent shares: the model, the delegation tool, the fact check, and the run wrapper.

Delegation (full connectivity): every agent has `delegate(teammate, task)` and may call any
other specialist, so Inventory can ask Accounting, Customer Service can ask Inventory, and so on.
Loops are impossible because an agent already on the current delegation chain can't be called
again, the chain is at most MAX_DELEGATION_DEPTH deep, and a ticket allows at most
MAX_DELEGATIONS_PER_TICKET hand-offs. The Boss is always the root of the chain, so the final call
stays with the Boss.
"""

from __future__ import annotations

import json
import re
from functools import cache
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelRequest, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

import audit
from config import (AGENT_REQUEST_LIMIT, AGENT_TOKEN_LIMIT, AGENT_TOOL_CALL_LIMIT, MAX_DELEGATION_DEPTH,
                    MAX_DELEGATIONS_PER_TICKET, MAX_OUTPUT_TOKENS, MODEL_NAME, PORTKEY_BASE_URL, PROMPTS,
                    REASONING_EFFORT, portkey_api_key)
from mcp_link import tools_for
from models import AgentName, Fact, SpecialistReport, TeamDeps, Teammate

REGISTRY: dict[AgentName, Agent] = {}
SPECIALISTS: tuple[Teammate, ...] = ("inventory", "accounting", "facilities", "customer_service")
AGENT_LIMITS = UsageLimits(request_limit=AGENT_REQUEST_LIMIT, tool_calls_limit=AGENT_TOOL_CALL_LIMIT,
                           total_tokens_limit=AGENT_TOKEN_LIMIT)


@cache
def model() -> OpenAIResponsesModel:
    key = portkey_api_key()
    client = AsyncOpenAI(base_url=PORTKEY_BASE_URL, api_key=key, default_headers={"x-portkey-api-key": key})
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


SETTINGS = OpenAIResponsesModelSettings(openai_reasoning_effort=REASONING_EFFORT, max_tokens=MAX_OUTPUT_TOKENS)


def prompt(name: AgentName) -> str:
    return (PROMPTS / f"{name}.md").read_text()


def runtime_context(ctx: RunContext[TeamDeps]) -> str:
    """Appended to every agent's prompt: where it sits in the delegation chain right now."""
    d = ctx.deps
    can_reach = [a for a in SPECIALISTS if a not in d.chain] if d.depth < MAX_DELEGATION_DEPTH else []
    return (f"## This run\n- You are: {d.agent}\n- Ticket: {d.ticket_id}\n- Delegation chain: {' -> '.join(d.chain)}\n"
            f"- Teammates you may delegate to now: {', '.join(can_reach) or 'none (answer with your own tools)'}\n"
            f"- Hand-offs used on this ticket: {d.budget.delegations}/{MAX_DELEGATIONS_PER_TICKET}")


# --- delegation ------------------------------------------------------------------------

async def delegate(ctx: RunContext[TeamDeps], teammate: Teammate, task: str) -> dict[str, Any]:
    """Hand a specific question or job to a teammate and get their structured report back.

    Args:
        teammate: inventory, accounting, facilities, or customer_service.
        task: A precise, self-contained request: the ticket facts they need (SKU, size, qty,
            invoice/lease ids, names), what you want back, and anything already on the board.
    """
    d = ctx.deps
    refusal = None
    if teammate == d.agent or teammate in d.chain:
        refusal = f"{teammate} is already on this delegation chain ({' -> '.join(d.chain)}); answer with what you have."
    elif d.depth >= MAX_DELEGATION_DEPTH:
        refusal = f"Delegation depth limit ({MAX_DELEGATION_DEPTH}) reached; use your own tools."
    elif d.budget.delegations >= MAX_DELEGATIONS_PER_TICKET:
        refusal = f"This ticket has used all {MAX_DELEGATIONS_PER_TICKET} hand-offs; decide with what you have."
    if refusal:
        await audit.log("delegation_refused", run_id=d.run_id, ticket_id=d.ticket_id, agent=d.agent,
                        to=teammate, task=task, reason=refusal)
        return {"refused": True, "reason": refusal}

    d.budget.delegations += 1
    await audit.log("delegation", run_id=d.run_id, ticket_id=d.ticket_id, agent=d.agent, to=teammate,
                    task=task, depth=d.depth + 1, chain=d.chain + [teammate])
    child = TeamDeps(run_id=d.run_id, ticket_id=d.ticket_id, agent=teammate, chain=d.chain + [teammate],
                     depth=d.depth + 1, budget=d.budget)
    try:
        result = await run_agent(teammate, task, child, AGENT_LIMITS)
    except AgentFailed as exc:
        return {"failed": True, "teammate": teammate, "error": str(exc)}
    ctx.usage.incr(result.usage)  # roll the teammate's tokens into the caller's (and so the ticket's) budget
    return result.output.model_dump()


# --- grounding check -------------------------------------------------------------------

_NUM = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    return {float(n) for n in _NUM.findall(text.replace(",", ""))}


def tool_evidence(ctx: RunContext[TeamDeps]) -> tuple[set[str], set[float], str]:
    """Tool names called in this run, every number they returned, and the raw returned text."""
    names: set[str] = set()
    chunks: list[str] = []
    for msg in ctx.messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    names.add(part.tool_name)
                    chunks.append(part.content if isinstance(part.content, str)
                                  else json.dumps(part.content, default=str))
    text = "\n".join(chunks)
    return names, _numbers(text), text


def check_facts(ctx: RunContext[TeamDeps], facts: list[Fact]) -> list[str]:
    names, numbers, _ = tool_evidence(ctx)
    problems = []
    for f in facts:
        if f.source_tool not in names:
            problems.append(f"'{f.label}' cites {f.source_tool}, which you did not call in this run.")
        missing = _numbers(f.value) - numbers
        if missing:
            problems.append(f"'{f.label}' = '{f.value}' has numbers no tool returned: {sorted(missing)}.")
    return problems


async def validate_report(ctx: RunContext[TeamDeps], report: SpecialistReport) -> SpecialistReport:
    report.agent, report.ticket_id = ctx.deps.agent, ctx.deps.ticket_id  # identity comes from the run, not the model
    problems = check_facts(ctx, report.facts)
    if problems:
        raise ModelRetry("Every fact must be copied from a tool result in this run. Fix or remove:\n- "
                         + "\n- ".join(problems) + "\nPut computed numbers in `analysis` instead.")
    return report


# --- building and running agents --------------------------------------------------------

def specialist(name: Teammate) -> Agent[TeamDeps, SpecialistReport]:
    agent = Agent(model(), name=name, deps_type=TeamDeps, output_type=SpecialistReport,
                  instructions=[prompt(name), runtime_context], toolsets=[tools_for(name)], tools=[delegate],
                  model_settings=SETTINGS, retries=2)
    agent.output_validator(validate_report)
    REGISTRY[name] = agent
    return agent


class AgentFailed(RuntimeError):
    pass


async def run_agent(name: AgentName, task: str, deps: TeamDeps, limits: UsageLimits):
    """Run one agent with its budget; log start, end (output + usage), or failure to the audit trail."""
    await audit.log("agent_start", run_id=deps.run_id, ticket_id=deps.ticket_id, agent=name, depth=deps.depth,
                    chain=deps.chain, task=task)
    try:
        result = await REGISTRY[name].run(task, deps=deps, usage_limits=limits)
    except (UsageLimitExceeded, UnexpectedModelBehavior, ModelHTTPError) as exc:
        await audit.log("agent_error", run_id=deps.run_id, ticket_id=deps.ticket_id, agent=name,
                        error_type=type(exc).__name__, error=str(exc))
        raise AgentFailed(f"{name} failed: {type(exc).__name__}: {exc}") from exc
    u = result.usage
    await audit.log("agent_end", run_id=deps.run_id, ticket_id=deps.ticket_id, agent=name,
                    output=result.output.model_dump(),
                    usage={"requests": u.requests, "tool_calls": u.tool_calls, "input_tokens": u.input_tokens,
                           "output_tokens": u.output_tokens, "total_tokens": u.total_tokens})
    return result
