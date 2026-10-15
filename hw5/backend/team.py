"""Run the Campus Customs team over tickets.

    cd backend
    ../.venv/bin/python team.py --all          # full run: resets the working DB first, then every open ticket
    ../.venv/bin/python team.py --ticket 101   # one ticket against the current working DB (no reset)
    ../.venv/bin/python team.py --reset        # only reset data/campus_customs_new.db from the original

Loop per ticket: Boss reads the ticket -> delegates to specialists (who may delegate to each other)
-> returns a BossDecision -> the backend records it on the board via MCP `record_ticket_decision`.
Tickets run one at a time so each sees the cash commitments the previous ones put on the board.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import shutil
import uuid
from typing import Any

import audit
import mcp_link
import agents  # noqa: F401  (importing the package registers all five agents)
from agents.base import AgentFailed, run_agent
from config import (DB_ORIGINAL, DB_WORKING, MODEL_NAME, TICKET_REQUEST_LIMIT, TICKET_TOKEN_LIMIT)
from models import BossDecision, TeamDeps
from pydantic_ai.usage import UsageLimits

TICKET_LIMITS = UsageLimits(request_limit=TICKET_REQUEST_LIMIT, total_tokens_limit=TICKET_TOKEN_LIMIT)


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


async def reset_db(run_id: str) -> None:
    """Restore the working copy to the original values. The original is only ever read."""
    before = _sha(DB_ORIGINAL)
    shutil.copyfile(DB_ORIGINAL, DB_WORKING)
    DB_WORKING.chmod(0o644)
    assert _sha(DB_ORIGINAL) == before == _sha(DB_WORKING)
    await audit.log("db_reset", run_id=run_id, source=DB_ORIGINAL.name, target=DB_WORKING.name, sha256_16=before)


async def run_ticket(ticket_id: int, run_id: str) -> dict[str, Any]:
    deps = TeamDeps(run_id=run_id, ticket_id=ticket_id, agent="boss", chain=["boss"])
    task = (f"Handle ticket {ticket_id}. Read it, delegate to the right specialists, and return your decision.")
    try:
        result = await run_agent("boss", task, deps, TICKET_LIMITS)
    except AgentFailed as exc:
        return {"ticket_id": ticket_id, "ok": False, "error": str(exc)}

    decision: BossDecision = result.output
    recorded = await mcp_link.call("record_ticket_decision", {
        "ticket_id": ticket_id, "decision": decision.decision, "summary": decision.summary,
        "approval_ids": decision.approval_ids, "draft_ids": decision.draft_ids,
        "next_steps_for_human": decision.next_steps_for_human, "requested_by": "boss"})
    await audit.log("decision_recorded", run_id=run_id, ticket_id=ticket_id, agent="boss",
                    decision_id=recorded["decision"]["id"], decision=decision.decision)
    u = result.usage
    return {"ticket_id": ticket_id, "ok": True, "decision": decision.model_dump(),
            "usage": {"requests": u.requests, "total_tokens": u.total_tokens}}


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


async def run(ticket_ids: list[int] | None, reset: bool, run_id: str | None = None) -> list[dict[str, Any]]:
    run_id = run_id or new_run_id()
    await audit.log("run_start", run_id=run_id, model=MODEL_NAME, tickets=ticket_ids or "all open", reset=reset)
    if reset:
        await reset_db(run_id)
    async with mcp_link.TOOLSET:  # one MCP server process for the whole run
        if ticket_ids is None:
            ticket_ids = [t["id"] for t in (await mcp_link.call("list_open_tickets", {}))["tickets"]]
        results = [await run_ticket(t, run_id) for t in ticket_ids]
    await audit.log("run_end", run_id=run_id, results=[{k: r[k] for k in ("ticket_id", "ok")} for r in results],
                    total_tokens=sum(r.get("usage", {}).get("total_tokens", 0) for r in results))
    return results


def main() -> None:
    p = argparse.ArgumentParser(description="Run the Campus Customs agent team.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true", help="full run: reset the working DB, then every open ticket")
    g.add_argument("--ticket", type=int, nargs="+", help="run these ticket ids against the current working DB")
    g.add_argument("--reset", action="store_true", help="only reset the working DB from the original")
    a = p.parse_args()

    if a.reset:
        asyncio.run(reset_db(new_run_id()))
        print(f"Reset {DB_WORKING.name} from {DB_ORIGINAL.name}.")
        return
    for r in asyncio.run(run(None if a.all else a.ticket, reset=a.all)):
        if not r["ok"]:
            print(f"Ticket {r['ticket_id']}: FAILED - {r['error']}")
            continue
        d = r["decision"]
        print(f"\nTicket {r['ticket_id']}: {d['decision']}  (via {', '.join(d['delegated_to'])}; "
              f"{r['usage']['requests']} requests, {r['usage']['total_tokens']} tokens)")
        print(f"  {d['summary']}")
        print(f"  approvals {d['approval_ids']}  drafts {d['draft_ids']}")
        for step in d["next_steps_for_human"]:
            print(f"  - {step}")


if __name__ == "__main__":
    main()
