# Campus Customs (HW5): a multi-agent team that runs the shop

Five PydanticAI agents (**Boss, Inventory, Accounting, Facilities, Customer Service**) work the shop's tickets. They get every fact through an **MCP server** over SQLite, report to a **FastAPI** backend, and are watched and approved from a **React** dashboard. Agents only *prepare* payments, purchase orders, and messages. **A human approves every payment**, and nothing is ever sent.

```
React dashboard (frontend/, :5173)
        │  HTTP
FastAPI backend (backend/main.py, :8000) ── runs ──▶ agent team (backend/agents/, gpt-6-luna via Portkey)
        │                                                     │
        └──────────── MCP (stdio, .mcp.json) ◀────────────────┘
                     MCP server (mcp_server/server.py, 16 tools)
                              │
                     data/campus_customs_new.db  (working copy; reset from data/campus_customs_original.db)
```

**How the system works:** [`output/harness.md`](output/harness.md) covers tables, tools, agents, safety, API, dashboard, run procedure, audit trail, and results. **Prompt log:** [`AI_prompts.md`](AI_prompts.md).

---

## 1. Prerequisites

- Python 3.12+ (developed on 3.14)
- Node 20+ (developed on Node 24)
- A Portkey API key with access to OpenAI `gpt-6-luna`

## 2. One-time setup

All commands run from this `hw5/` folder.

```bash
# Python: one venv for the MCP server, backend, and tools
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# Frontend
cd frontend && npm install && cd ..

# API key (placeholders only in .env.example; .env is git-ignored)
cp .env.example .env
# then edit .env and set PORTKEY_API_KEY=<your key>
```

## 3. The two databases: copy/reset for a clean run

| File | Role |
|---|---|
| `data/campus_customs_original.db` | Source of truth. Never modified (`chmod 444` locally). |
| `data/campus_customs_new.db` | Working copy that agents and humans update. It also holds the board tables (`approval_requests`, `drafts`, `ticket_decisions`). |

The committed `campus_customs_new.db` holds the state after the graded full run (checking $152.00). To start clean, copy the original over the working copy using any one of these:

```bash
cp data/campus_customs_original.db data/campus_customs_new.db && chmod 644 data/campus_customs_new.db   # plain copy
cd backend && ../.venv/bin/python team.py --reset && cd ..                                            # same, logged to the audit trail
curl -X POST http://localhost:8000/api/reset                                                           # same, while the API is running
```

Or click **↺ Reset shop** in the dashboard.

## 4. Start everything

Use three terminals, each starting in `hw5/`.

**① MCP server.** You don't need to start it by hand. It's a stdio server registered in [`.mcp.json`](.mcp.json): the FastAPI backend launches it automatically at startup and keeps it running, and Claude Code (or any MCP client) launches it from that file too. To run it on its own or test it:

```bash
.venv/bin/python mcp_server/server.py          # starts the stdio server (waits for an MCP client on stdin)
.venv/bin/python tools/mcp_smoke.py            # connects via .mcp.json, runs 8 prompts through gpt-6-luna -> output/mcp_smoke.json
```

**② FastAPI backend** (http://localhost:8000, docs at `/docs`):

```bash
cd backend
source ../.venv/bin/activate
uvicorn main:app --reload --port 8000
```

**③ React frontend** (http://localhost:5173):

```bash
cd frontend
npm run dev
```

Open http://localhost:5173. The dashboard talks to the API at http://localhost:8000 (override with `VITE_API_BASE` in `frontend/.env.local`).

## 5. Full run of all tickets

**Always reset the database before a full run.**

**From the dashboard (recommended):**
1. Type your name in **Approving as**.
2. Click **↺ Reset shop** → **Confirm reset**. Checking goes back to $3,400.00 and the board clears.
3. Select **#101** → **▶ Run agent team**. Watch the workflow graph and activity feed live.
4. When it finishes, do the same for **#102**, then **#103**, in that order. Each later ticket sees the cash commitments the earlier ones made.
5. Approve or reject the requests in **Needs you** (💸 vendor payment, 🏠 rent, 📦 purchase order, 🏷️ price quote). Approving takes two clicks and is the only thing that moves cash. Overdrafts, and POs to a vendor with an unpaid invoice, are refused with the reason.

**From the command line** (no dashboard; approvals then go through the API):

```bash
cd backend
../.venv/bin/python team.py --all            # resets the working DB first, then runs 101, 102, 103 in order
../.venv/bin/python team.py --ticket 103     # one ticket against the current DB (no reset)
```

**Rebuild the Problem 9 reports** after a run and your approvals:

```bash
.venv/bin/python tools/problem9_report.py   # fills desk_tickets.html Actual + Cash, writes resolved_tickets.json and resolved_board.html
```

It refuses to write if the cash ledger doesn't reconcile exactly with `cash_accounts`.

## 6. Stopping

Press Ctrl-C in each terminal. Ctrl-C on uvicorn also stops the MCP server subprocess it started. Check that nothing is left on the ports with `lsof -nP -iTCP:8000 -iTCP:5173 -sTCP:LISTEN`.

`--reload` watches `backend/` only, so restart uvicorn after editing `mcp_server/server.py`.

## 7. What's where

| Path | Contents |
|---|---|
| `AI_prompts.md` | Every prompt used, problem by problem, with follow-ups and why they were needed |
| `.mcp.json` | MCP connection config (stdio server `campus-customs`) |
| `.env.example` | Environment variables, placeholders only |
| `mcp_server/` | `server.py` (FastMCP, 16 tools; agents write only to the board; human-only `decide_request` moves cash), `README.md`, `requirements.txt` |
| `backend/` | `main.py` (FastAPI), `team.py` (runner and CLI), `agents/` (boss, inventory, accounting, facilities, customer_service, base), `prompts/` (one per agent), `models.py`, `mcp_link.py` (the only route to the DB), `audit.py`, `config.py` |
| `frontend/` | React + Vite + TypeScript dashboard (`src/App.tsx`, `src/components/`) |
| `data/` | `campus_customs_original.db` (source of truth) and `campus_customs_new.db` (working copy) |
| `tools/` | `mcp_smoke.py` (MCP smoke test), `problem9_report.py` (full-run reports) |
| `output/harness.md` | **The system spec**: tables, tools, agents, safety, API, dashboard, run, audit, results |
| `output/desk_tickets.html` | Per-ticket Expected / Actual, plus Cash ledger and Reflection (double-click to open) |
| `output/resolved_board.html` | Full-run board with dashboard screenshots (double-click to open) |
| `output/resolved_tickets.json` | Per-ticket outcome, agent contributions, and human approvals |
| `output/audit_trail.json` | Append-only log of every agent turn, MCP call, hand-off, decision, approval, and reset |
| `output/design.md` | Dashboard design rationale |
| `output/mcp_smoke.json`, `output/mcp_live_test.md` | MCP tool tests |
| `output/screenshots/` | Dashboard screenshots per resolved ticket |
| `output/github_url.txt` | This repository's URL |

## 8. Shop rules the system enforces

- **"Today" is `desk.date_today`** (2026-08-31). Overdue status and lead times are measured from it.
- **Vendor lead times come from `vendors`.** A vendor with an unpaid invoice won't ship.
- **Every payment needs human approval.** Agents only create `pending_human` requests.
- **Cash only goes out**, because revenue isn't modeled.
- **No real emails or calls.** Drafts stay on the board (`sent = 0` is enforced).
- **Every agent uses only `gpt-6-luna` through Portkey**, via the Responses API, with token and loop limits (see harness section 6).
