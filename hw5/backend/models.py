"""Data types shared by the team: run context (deps) and each agent's structured output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
Teammate = Literal["inventory", "accounting", "facilities", "customer_service"]  # who can be delegated to
Decision = Literal["awaiting_human_approval", "blocked", "resolved", "needs_more_info"]


# --- run context ------------------------------------------------------------------

@dataclass
class TicketBudget:
    """Shared by every agent working one ticket, so team-wide limits hold across delegations."""
    delegations: int = 0


@dataclass
class TeamDeps:
    """Passed to every agent run. `agent` is who is acting; `chain` is the delegation path so far."""
    run_id: str
    ticket_id: int
    agent: AgentName
    chain: list[AgentName]
    depth: int = 0
    budget: TicketBudget = field(default_factory=TicketBudget)


# --- outputs ----------------------------------------------------------------------

class Fact(BaseModel):
    """One shop fact, copied from a tool result. Computed numbers go in `analysis`, not here."""
    label: str = Field(description="What the fact is, e.g. 'CC-TEE-WHITE size S on hand'.")
    value: str = Field(description="The value exactly as the tool returned it, e.g. '0' or '2026-09-02'.")
    source_tool: str = Field(description="Name of the tool (or 'delegate') whose result contains this value.")


class SpecialistReport(BaseModel):
    """What a specialist hands back to whoever delegated to it."""
    agent: Teammate
    ticket_id: int
    summary: str = Field(description="2-4 sentences: what you found and what it means for the ticket.")
    facts: list[Fact] = Field(description="Every shop fact your summary relies on, each from a tool result.")
    analysis: str = Field(default="", description="Arithmetic or reasoning built on the facts (e.g. totals, margins).")
    board_items_created: list[str] = Field(
        default_factory=list, description="Board items you created or reused, e.g. 'approval_request 3', 'draft 1'.")
    blockers: list[str] = Field(default_factory=list, description="What stops this ticket moving, if anything.")
    needs_human: list[str] = Field(default_factory=list, description="Actions only the human overseer can take.")
    recommendation: str = Field(description="What you recommend the Boss decide.")


class BossDecision(BaseModel):
    """The Boss's final call on one ticket. Recorded to the board via MCP by the backend."""
    ticket_id: int
    decision: Decision
    summary: str = Field(description="3-6 sentences: the situation, what the team did, and why this decision.")
    delegated_to: list[Teammate] = Field(description="Specialists consulted, in order.")
    approval_ids: list[int] = Field(default_factory=list, description="approval_requests ids awaiting the human.")
    draft_ids: list[int] = Field(default_factory=list, description="drafts ids awaiting human review.")
    next_steps_for_human: list[str] = Field(description="Concrete actions for the human overseer, in order.")
