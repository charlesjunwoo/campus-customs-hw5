"""Append-only audit trail: output/audit_trail.json is a JSON array that is never wiped.

Each event: ts (UTC), run_id, ticket_id, event, agent, plus event-specific fields.
Events: run_start, db_reset, agent_start, mcp_call, delegation, delegation_refused,
agent_end, agent_error, decision_recorded, run_end.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

from config import AUDIT_PREVIEW_CHARS, AUDIT_TRAIL

_lock = asyncio.Lock()


def preview(value: Any) -> Any:
    """Keep small results whole; truncate big ones so the trail stays readable."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return value if len(text) <= AUDIT_PREVIEW_CHARS else text[:AUDIT_PREVIEW_CHARS] + f"... [{len(text)} chars]"


def _load() -> list[dict[str, Any]]:
    if not AUDIT_TRAIL.exists() or not AUDIT_TRAIL.read_text().strip():
        return []
    data = json.loads(AUDIT_TRAIL.read_text())
    if not isinstance(data, list):
        raise RuntimeError(f"{AUDIT_TRAIL} is not a JSON array; refusing to overwrite it.")
    return data


async def log(event: str, **fields: Any) -> None:
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": event, **fields}
    async with _lock:
        AUDIT_TRAIL.parent.mkdir(parents=True, exist_ok=True)
        trail = _load()
        trail.append(entry)
        tmp = AUDIT_TRAIL.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(trail, indent=1, default=str) + "\n")
        os.replace(tmp, AUDIT_TRAIL)  # atomic: a crash mid-write never truncates the trail


# --- reading the trail back (for the dashboard) --------------------------------------

def read(limit: int | None = None, since_reset: bool = False) -> list[dict[str, Any]]:
    trail = _load()
    if since_reset:
        last = max((i for i, e in enumerate(trail) if e["event"] == "db_reset"), default=-1)
        trail = trail[last:] if last >= 0 else trail   # keep the reset event itself
    return trail[-limit:] if limit else trail


def agent_turns(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group events into one entry per agent run: what it was asked, which MCP tools it used
    (in order), who it delegated to, and what it said (its structured output).

    Events are sequential and nested agents finish before their caller continues, so a stack
    attributes each mcp_call / delegation to the agent currently running.
    """
    turns: list[dict[str, Any]] = []
    stack: dict[str, list[dict[str, Any]]] = {}       # run_id -> open turns
    for e in events:
        rid, kind = e.get("run_id"), e["event"]
        open_turns = stack.setdefault(rid, [])
        if kind == "agent_start":
            chain = e.get("chain") or [e["agent"]]
            turn = {"run_id": rid, "ticket_id": e.get("ticket_id"), "agent": e["agent"], "depth": e.get("depth", 0),
                    "asked_by": chain[-2] if len(chain) > 1 else "backend", "task": e.get("task"),
                    "started": e["ts"], "ended": None, "status": "running", "tools": [], "delegations": [],
                    "said": None, "usage": None, "error": None}
            open_turns.append(turn)
            turns.append(turn)
        elif kind in ("mcp_call", "delegation", "delegation_refused") and open_turns:
            turn = next((t for t in reversed(open_turns) if t["agent"] == e.get("agent")), open_turns[-1])
            if kind == "mcp_call":
                turn["tools"].append({"ts": e["ts"], "tool": e["tool"], "args": e.get("args"), "ok": e.get("ok"),
                                      "ms": e.get("ms"), "error": e.get("error"), "result": e.get("result")})
            else:
                turn["delegations"].append({"ts": e["ts"], "to": e.get("to"), "task": e.get("task"),
                                            "refused": kind == "delegation_refused", "reason": e.get("reason")})
        elif kind in ("agent_end", "agent_error") and open_turns:
            idx = next((i for i in range(len(open_turns) - 1, -1, -1) if open_turns[i]["agent"] == e.get("agent")), None)
            if idx is None:
                continue
            turn = open_turns.pop(idx)
            turn.update(ended=e["ts"], status="done" if kind == "agent_end" else "failed",
                        said=e.get("output"), usage=e.get("usage"), error=e.get("error"))
    return turns
