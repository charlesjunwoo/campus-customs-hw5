"""Campus Customs operations API: the backend for the approvals dashboard.

Start (from this folder, with the project venv active):
    uvicorn main:app --reload --port 8000

  * Shop data: every route reads and writes through the MCP server (mcp_link), never SQLite directly.
  * Agents prepare; humans decide. Agents only put requests on the board. POST /api/approvals/{id}/approve
    is the only path that moves cash, via the human-only MCP tool `decide_request`.
  * Agent runs execute in the background (one at a time). Poll GET /api/runs/{run_id} and
    GET /api/activity to watch them.
  * Every run, approval, rejection, and reset is appended to output/audit_trail.json.

Docs: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import audit
import mcp_link
import team
from config import MODEL_NAME

RUNS: dict[str, dict[str, Any]] = {}     # run_id -> status of agent runs started from this API
_busy = asyncio.Lock()                    # one agent run (or reset) at a time


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_link.TOOLSET:          # one MCP server process for the app's lifetime
        yield


app = FastAPI(title="Campus Customs Ops API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["GET", "POST"], allow_headers=["*"])


async def mcp(tool: str, args: dict[str, Any] | None = None) -> Any:
    """Call an MCP tool; turn a refusal from the server into a 409 with its message."""
    try:
        return await mcp_link.call(tool, args or {})
    except Exception as exc:  # FastMCP raises ToolError for refusals; surface the server's own message
        msg = str(exc)
        raise HTTPException(status_code=409, detail=msg.split("Error calling tool", 1)[-1].strip(" :'") or msg) from exc


# --- health ---------------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict[str, Any]:
    cash = await mcp("get_cash_position")
    return {"ok": True, "model": MODEL_NAME, "mcp": "connected", "shop_date": cash["as_of"],
            "agent_run_in_progress": _busy.locked()}


# --- 1. tickets -------------------------------------------------------------------------------

@app.get("/api/tickets")
async def list_tickets() -> dict[str, Any]:
    """Every ticket (101, 102, 103) with status open/resolved, the stage, the Boss's latest decision, and its approvals."""
    data = await mcp("list_tickets")
    active = {r["ticket_id"]: r["run_id"] for r in RUNS.values() if r["status"] in ("queued", "running")}
    for t in data["tickets"]:
        t["agents_running"] = t["id"] in active
        t["active_run_id"] = active.get(t["id"])
        if t["agents_running"]:
            t["stage"] = "running"
    return {"as_of": data["as_of"], "tickets": data["tickets"]}


# --- 2. run the agent team on one ticket -------------------------------------------------------

async def _run_in_background(run_id: str, ticket_id: int) -> None:
    async with _busy:
        RUNS[run_id]["status"] = "running"
        try:
            result = (await team.run([ticket_id], reset=False, run_id=run_id))[0]
            RUNS[run_id].update(status="done" if result["ok"] else "failed", result=result, finished_at=_now())
        except Exception as exc:  # keep the API alive; the failure is visible in the run status
            RUNS[run_id].update(status="failed", result={"error": f"{type(exc).__name__}: {exc}"}, finished_at=_now())


@app.post("/api/tickets/{ticket_id}/run", status_code=202)
async def run_ticket(ticket_id: int) -> dict[str, Any]:
    """Start the agent team (Boss -> specialists) on one ticket. Returns a run_id immediately."""
    tickets = {t["id"] for t in (await mcp("list_tickets"))["tickets"]}
    if ticket_id not in tickets:
        raise HTTPException(404, f"Ticket {ticket_id} does not exist.")
    if _busy.locked():
        raise HTTPException(409, "An agent run or reset is already in progress; wait for it to finish.")
    run_id = team.new_run_id()
    RUNS[run_id] = {"run_id": run_id, "ticket_id": ticket_id, "status": "queued", "started_at": _now(),
                    "finished_at": None, "result": None}
    asyncio.create_task(_run_in_background(run_id, ticket_id))
    return {"run_id": run_id, "ticket_id": ticket_id, "status": "started",
            "poll": [f"/api/runs/{run_id}", f"/api/activity?run_id={run_id}"]}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Status of a run started through this API: queued / running / done / failed, plus the Boss's decision."""
    if run_id not in RUNS:
        raise HTTPException(404, f"Unknown run {run_id} (runs are tracked since the API last started).")
    return RUNS[run_id]


# --- 3. recent agent activity -----------------------------------------------------------------

@app.get("/api/activity")
async def activity(limit: int = Query(30, ge=1, le=200), ticket_id: int | None = None,
                   run_id: str | None = None, since_reset: bool = False) -> dict[str, Any]:
    """Recent agent turns, newest first: who asked whom, what each agent said, and which MCP tools it used.
    since_reset=true limits to events after the last database reset (the current shop state)."""
    events = audit.read(since_reset=since_reset)
    if run_id:
        events = [e for e in events if e.get("run_id") == run_id]
    if ticket_id is not None:
        events = [e for e in events if e.get("ticket_id") == ticket_id]
    turns = audit.agent_turns(events)[::-1][:limit]
    human = [e for e in events if e["event"] in ("human_decision", "db_reset")][::-1][:limit]
    latest_run = next((t["run_id"] for t in turns), None)
    return {"agent_run_in_progress": _busy.locked(), "latest_run_id": latest_run, "turns": turns, "human_and_system_events": human,
            "events_in_trail": len(events)}


# --- 4. human approval (the only route that moves cash) -----------------------------------------

class Decision(BaseModel):
    decided_by: str = Field(min_length=2, max_length=80, description="Name of the person approving or rejecting.")


@app.get("/api/approvals")
async def approvals(status: Literal["pending_human", "approved", "rejected", "all"] = "pending_human",
                    ticket_id: int | None = None) -> dict[str, Any]:
    """Approval requests (and drafts) on the board, filtered by status."""
    board = await mcp("list_board", {"ticket_id": ticket_id} if ticket_id is not None else {})
    reqs = board["approval_requests"]
    if status != "all":
        reqs = [r for r in reqs if r["status"] == status]
    return {"approval_requests": reqs, "drafts": board["drafts"]}


async def _decide(request_id: int, action: str, body: Decision) -> dict[str, Any]:
    if _busy.locked():
        raise HTTPException(409, "Agents are running; decide after the run finishes so they see a stable board.")
    try:
        result = await mcp("decide_request", {"request_id": request_id, "action": action,
                                              "decided_by": body.decided_by, "requested_by": "human"})
    except HTTPException as exc:
        await audit.log("human_decision", request_id=request_id, action=action, decided_by=body.decided_by,
                        ok=False, error=exc.detail)
        raise
    req = result["request"]
    await audit.log("human_decision", ticket_id=req["ticket_id"], request_id=request_id, action=action,
                    decided_by=body.decided_by, ok=True, kind=req["kind"], amount=req["amount"],
                    cash_before=result["cash_before"], cash_after=result["cash_after"], payment=result["payment"])
    return result


@app.post("/api/approvals/{request_id}/approve")
async def approve(request_id: int, body: Decision) -> dict[str, Any]:
    """Human approves a request. Payments and purchase orders debit checking and are recorded in payments."""
    return await _decide(request_id, "approve", body)


@app.post("/api/approvals/{request_id}/reject")
async def reject(request_id: int, body: Decision) -> dict[str, Any]:
    """Human rejects a request. No cash moves."""
    return await _decide(request_id, "reject", body)


# --- 5. cash -----------------------------------------------------------------------------

@app.get("/api/cash")
async def cash() -> dict[str, Any]:
    """Current checking balance from cash_accounts, plus known obligations against it."""
    c = await mcp("get_cash_position")
    checking = next((a for a in c["accounts"] if a["name"] == "checking"), c["accounts"][0])
    return {"account": checking["name"], "balance": checking["balance"], "balance_date": checking["date"],
            "as_of": c["as_of"], "payments_recorded": c["payments_recorded"],
            "obligations": {"unpaid_invoices": c["unpaid_invoices_total"], "rent_due_30_days": c["rent_due_total"],
                            "pending_purchase_orders": c["pending_purchase_orders_total"], "total": c["total_obligations"]},
            "projected_balance_after_obligations": c["projected_balance_after_obligations"], "shortfall": c["shortfall"]}


# --- 6. reset --------------------------------------------------------------------------------

@app.post("/api/reset")
async def reset() -> dict[str, Any]:
    """Restore data/campus_customs_new.db from the original (clears the board). The audit trail is kept."""
    if _busy.locked():
        raise HTTPException(409, "An agent run is in progress; reset after it finishes.")
    async with _busy:
        run_id = team.new_run_id()
        await team.reset_db(run_id)
    c = await mcp("get_cash_position")
    return {"reset": True, "run_id": run_id, "balance": c["cash_balance"], "as_of": c["as_of"],
            "message": "Working database restored to original values. Audit trail kept."}
