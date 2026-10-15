# Campus Customs Agent Team — Harness

The operating spec for the Campus Customs multi-agent team: Boss, Inventory, Accounting, Facilities, and Customer Service. It covers the data, model, agents, MCP tools, approvals, safety, API, dashboard, run procedure, audit trail, and the full Problem 9 run.

**System at a glance:** React dashboard (`frontend/`, :5173) → FastAPI (`backend/main.py`, :8000) → PydanticAI team (`backend/agents/`, gpt-6-luna via Portkey) → MCP server (`mcp_server/server.py`, 16 tools, stdio via `.mcp.json`) → SQLite working copy (`data/campus_customs_new.db`). Agents prepare; only a human approval through the dashboard moves cash.

**Contents**
1. [Data](#1-data)
2. [Model](#2-model)
3. [Agents & delegation](#3-agents--delegation)
4. [Tools (MCP server)](#4-tools-mcp-server)
5. [Approvals & human-in-the-loop](#5-approvals--human-in-the-loop)
6. [Safety: guardrails & token limits](#6-safety-guardrails--token-limits)
7. [Backend API](#7-backend-api)
8. [Dashboard](#8-dashboard)
9. [Run & reset procedure](#9-run--reset-procedure)
10. [Audit trail](#10-audit-trail)
11. [Full run & results (Problem 9)](#11-full-run--results-problem-9)

---

## 1. Data

### 1.1 Databases

| File | Role | Who writes to it |
|---|---|---|
| `data/campus_customs_original.db` | Source of truth: the original shop state, kept read-only (`chmod 444`). | Nobody. It is never modified. |
| `data/campus_customs_new.db` | Working copy that agents and humans update. Before every full run it is reset by copying the original over it. | Agents write **only** the three board tables below, through MCP. The human overseer writes the shop tables (payments, invoices, cash, inventory). |

**Board tables** (added in Problem 5, created by the MCP server inside the working copy; a reset removes them, and they are recreated on first use):

| Table | Holds | Written by |
|---|---|---|
| `approval_requests` | `invoice_payment`, `rent_payment`, `purchase_order`, `price_quote` proposals with a server-computed `amount`, `cash_out` flag, `blocked_by`, `reason`, `requested_by`, and `status` (`pending_human` → `approved`/`rejected` by the human) | Accounting (via MCP) |
| `drafts` | Customer, landlord, City, and vendor messages: `recipient`, `subject`, `body`, `author`, `status`, and `sent` (a CHECK constraint forces `sent = 0`) | Customer Service, Facilities, Inventory (via MCP) |
| `ticket_decisions` | The Boss's final call per ticket: `decision`, `summary`, `approval_ids`, `draft_ids`, `next_steps_for_human` | Backend, recording the Boss's output via MCP |

### 1.2 Tables and fields

**`desk`**: the shop's clock. `date_today` is "today" for every overdue and lead-time calculation, so agents must never use the real-world date.

| Field | Meaning |
|---|---|
| `date_today` | The shop's current date (`2026-08-31`) |
| `notes` | Free-text desk notes (empty) |

**`tickets`**: the Boss's work queue, where each open ticket starts a delegation chain. Its `sku`/`size`, `invoice_id`, and `lease_id` fields point the Boss to the right specialists.

| Field | Meaning |
|---|---|
| `id` | Ticket number (101–103) |
| `type` | Kind of request (`customer_order`, `rent_notice`, `price_override`). This is the Boss's first routing signal. |
| `requester` | Who raised it (a customer, the landlord, a student org) |
| `subject` | Short title |
| `sku`, `size`, `qty` | The item and quantity involved. These link to `inventory` and `pricing` by value; there is no foreign key. |
| `lease_id` | FK → `leases.id` for space and rent tickets |
| `invoice_id` | FK → `invoices.id` when an unpaid bill blocks the ticket |
| `status` | `open` / resolved state |
| `notes` | Requester's message, which may contain the actual ask |
| `created_at` | When it arrived (ISO timestamp, ET) |

**`inventory`**: stock on hand by SKU and size. Inventory uses it to check whether an order can be filled and to measure any shortfall.

| Field | Meaning |
|---|---|
| `sku` | Product code (PK part 1) |
| `name` | Product name |
| `size` | S/M/L/XL, or OS for one-size (PK part 2) |
| `qty` | Units on hand. Zero means a stockout. |
| `location` | Aisle in the shop |

**`pricing`**: unit cost and list price per SKU. Accounting uses it to check margins before approving any discount or purchase order.

| Field | Meaning |
|---|---|
| `sku` | Product code (PK) |
| `unit_cost` | What a restock costs per unit. This is the cost basis for purchase-order amounts. |
| `list_price` | Retail price, which sets the ceiling on discount math |

**`vendors`**: who can restock what, and how fast. Inventory matches the SKU to a vendor's `specialty` and uses `lead_days` to give a restock date counted from `desk.date_today`.

| Field | Meaning |
|---|---|
| `id` | Vendor ID |
| `name` | Vendor name (fictional, so we never contact them) |
| `specialty` | What they supply (apparel reprint, mugs and small goods, courier). This is the only SKU-to-vendor link. |
| `lead_days` | Days from order to delivery |

**`invoices`**: bills owed to vendors. A vendor with an unpaid invoice won't ship, so Accounting flags overdue bills by comparing them to `desk.date_today`, and Inventory treats that vendor as blocked.

| Field | Meaning |
|---|---|
| `id` | Invoice number |
| `vendor_id` | FK → `vendors.id` |
| `amount` | Amount owed |
| `due_date` | Due date. It is overdue if earlier than `desk.date_today`. |
| `status` | `open` = unpaid, so the vendor is blocked |
| `description` | What the bill covers |

**`cash_accounts`**: the shop's money, and it only goes down because revenue isn't modeled. Accounting checks every proposed payment against the balance and flags when the bills on the board exceed it.

| Field | Meaning |
|---|---|
| `name` | Account name (`checking`) |
| `balance` | Current balance |
| `date` | As-of date of the balance |

**`payments`**: the ledger of money that has gone out. Only the human overseer writes rows here after approving a payment; agents can read it but never insert.

| Field | Meaning |
|---|---|
| `id` | Payment ID |
| `kind` | What was paid (e.g. invoice, rent) |
| `ref_id` | The invoice or lease ID it settles |
| `amount` | Amount paid |
| `account` | Which cash account it came from |
| `paid_at` | Payment date |
| `approved_by` | The human who approved it. Payments require human approval. |

**`leases`**: the physical shop space. Facilities uses it to confirm rent amounts, due dates, and the landlord for rent notices and landlord or city correspondence.

| Field | Meaning |
|---|---|
| `id` | Lease ID |
| `space_name` | The space (`Chapel Street shop`) |
| `landlord` | Who is owed rent |
| `monthly_rent` | Rent amount |
| `next_due` | Next rent due date |
| `notes` | Lease notes (empty) |

**Board tables** (agent-owned, created by the MCP server; a reset removes them, and they are recreated empty on first use):

**`approval_requests`** (board): every payment, purchase order, and price quote the agents prepared. Nothing in it moves money; only a human decision through `decide_request` does.

| Field | Meaning |
|---|---|
| `id` | Request number shown on the dashboard |
| `ticket_id` | FK → `tickets.id`: the ticket it serves |
| `kind` | `invoice_payment`, `rent_payment`, `purchase_order`, or `price_quote` (CHECK constraint) |
| `ref_table`, `ref_id` | What it pays: `invoices` id, `leases` id, or `vendors` id for a PO |
| `vendor_id` | FK → `vendors.id` for invoices and POs |
| `sku`, `size`, `qty`, `unit_price` | Line detail for POs (unit_price = `pricing.unit_cost`) and quotes (the proposed price) |
| `amount` | Computed by the server from the DB, never typed by a model |
| `cash_out` | 1 = approving moves cash (payments and POs); 0 = sign-off only (quotes) |
| `blocked_by` | e.g. "invoice 501 ($840.00 unpaid)"; cleared when the vendor's last unpaid invoice is paid |
| `detail`, `reason` | Server-written description, and the agent's justification for the approver |
| `requested_by` | The agent role, stamped by the backend |
| `status` | `pending_human` → `approved` / `rejected` (by a human only) |
| `shop_date`, `created_at` | Shop date (desk) and real UTC timestamp |
| `decided_by`, `decided_at` | The person who decided, and when |

**`drafts`** (board): messages that are never sent.

| Field | Meaning |
|---|---|
| `id`, `ticket_id` | Draft number; FK → `tickets.id` |
| `audience` | `customer`, `landlord`, `city`, `vendor` (each tied to one role) |
| `recipient` | Must match the ticket requester, a lease landlord, or a vendor name; no addresses |
| `subject`, `body` | The message (body ≤ 2,000 chars; emails and phone numbers rejected) |
| `author` | The agent role that wrote it |
| `status`, `sent` | `draft`; `sent` is forced to 0 by a CHECK constraint |
| `shop_date`, `created_at`, `updated_at` | Timestamps (re-saving updates the same draft) |

**`ticket_decisions`** (board): the Boss's final call per ticket.

| Field | Meaning |
|---|---|
| `id`, `ticket_id` | Decision number; FK → `tickets.id` |
| `decision` | `awaiting_human_approval`, `resolved`, `blocked`, `needs_more_info` |
| `summary` | The Boss's explanation |
| `approval_ids`, `draft_ids` | JSON lists; every id must exist on the board for this ticket |
| `next_steps_for_human` | JSON list of ordered actions for the overseer |
| `decided_by`, `shop_date`, `created_at` | Always `boss`; timestamps |

### 1.3 How the open tickets link to the other tables

```
tickets.sku + size ──► inventory (stock on hand)
tickets.sku ─────────► pricing (cost / list price)
tickets.invoice_id ──► invoices.id ──► vendors.id (lead_days, specialty)
tickets.lease_id ────► leases.id
everything ──────────► desk.date_today (overdue / lead-time math)
payments ────────────► cash_accounts (balance)
```

What we observed in the original database (`desk.date_today` = 2026-08-31, checking = $3,400, no payments yet):

| Ticket | Ask | Linked rows | What it means for the team |
|---|---|---|---|
| **101** `customer_order`, Tauhid Zaman | 1 × CC-TEE-WHITE, size S | Inventory S = **0**. Invoice **501**: $840 to Bulldog Print Co, due 2026-08-28, status `open` (3 days overdue). Lead time 5 days. | Stockout. The only apparel vendor is blocked until the human approves and records payment of invoice 501. Customer Service drafts a delay message. |
| **102** `rent_notice`, Elm City Properties | Rent due in 2 days | Lease **1**: Chapel Street shop, $2,400, next_due 2026-09-02 | Facilities confirms the rent. Accounting prepares a $2,400 payment for human approval. Rent plus invoice 501 comes to $3,240 against $3,400 cash, leaving only $160. |
| **103** `price_override`, Yale AI Club | 20 × CC-HOOD-NAVY M at a bulk discount | Inventory M = **8** (short 12). Pricing: cost $22, list $58. No invoice linked. | Accounting checks how deep a discount the margin allows. Inventory needs a 12-unit reprint (12 × $22 = $264), but that comes from the same blocked vendor and leaves too little cash. The Boss makes the final call. |

**Gaps the agents must handle:**
- No table maps SKUs to vendors directly, so the vendor has to be inferred from `vendors.specialty`.
- Inventory and tickets aren't linked by a foreign key, so they are joined on `sku` and `size` values.

---

## 2. Model

All agents use **`gpt-6-luna`** (OpenAI) through the **Portkey** gateway (`https://api.portkey.ai/v1`), authenticated with `PORTKEY_API_KEY` from `.env`, which is never printed or committed. A smoke test on 2026-10-13 returned HTTP 200 from `gpt-6-luna-2026-09-22`. No fallback model is allowed: if a call fails, the error is surfaced and nothing switches models without the human's approval.

**API surface: use the Responses API (`/v1/responses`) for anything with tools.** Problem 4 found that Chat Completions rejects function tools on this model:
> `400 - azure-openai error: Function tools with reasoning_effort are not supported for gpt-6-luna-global in /v1/chat/completions. To use function tools, use /v1/responses or set reasoning_effort to 'none'.`

We kept `gpt-6-luna` and moved to the Responses API, which leaves reasoning on. We did not set `reasoning_effort: none`, since that would weaken the agents' judgement.

**In code** (`backend/config.py`, `backend/agents/base.py`): PydanticAI `OpenAIResponsesModel("gpt-6-luna")` over an `AsyncOpenAI` client pointed at Portkey. One model instance is shared by all five agents, with settings `openai_reasoning_effort="low"` and `max_tokens=4000`.

---

## 3. Agents & delegation

**Framework:** PydanticAI 2.55. **Code:** `backend/agents/` (one file per role), shared machinery in `backend/agents/base.py`, data types in `backend/models.py`, prompts in `backend/prompts/<agent>.md`, runner in `backend/team.py`.

### 3.1 The team

| Agent | File / prompt | Scope | MCP tools (least privilege) | Tables it draws from (via those tools) | Writes (board only) | Output |
|---|---|---|---|---|---|---|
| **Boss** | `agents/boss.py` / `prompts/boss.md` | Reads each ticket, routes it, makes the final call | `list_open_tickets`, `get_ticket`, `list_board` + `delegate` | `tickets`, `ticket_decisions`, `approval_requests`, `drafts`, `desk` | None directly; its `BossDecision` is recorded via MCP `record_ticket_decision` | `BossDecision` |
| **Inventory** | `agents/inventory.py` / `prompts/inventory.md` | Stock by SKU and size, shortfalls, restock vendor, lead time, blocked vendors | `get_ticket`, `check_inventory`, `find_restock_vendor`, `find_unpaid_invoices`, `list_board`, `save_draft` (vendor) + `delegate` | `tickets`, `inventory`, `vendors`, `invoices`, `desk`, board tables | Vendor drafts | `SpecialistReport` |
| **Accounting** | `agents/accounting.py` / `prompts/accounting.md` | Cash, invoices, margins; prepares payments, POs, and quotes for human approval | `get_ticket`, `find_unpaid_invoices`, `check_lease_obligations`, `get_cash_position`, `get_pricing`, `list_board`, `submit_payment_request`, `submit_purchase_order`, `submit_price_quote` + `delegate` | `tickets`, `invoices`, `vendors`, `leases`, `cash_accounts`, `payments`, `pricing`, `inventory`, `desk`, board tables | `approval_requests` | `SpecialistReport` |
| **Facilities** | `agents/facilities.py` / `prompts/facilities.md` | Leases, rent, landlord and City matters, space contracts | `get_ticket`, `check_lease_obligations`, `list_board`, `save_draft` (landlord/city) + `delegate` | `tickets`, `leases`, `desk`, board tables | Landlord and City drafts | `SpecialistReport` |
| **Customer Service** | `agents/customer_service.py` / `prompts/customer_service.md` | Drafts every customer message | `get_ticket`, `check_inventory`, `list_board`, `save_draft` (customer) + `delegate` | `tickets`, `inventory`, board tables | Customer drafts | `SpecialistReport` |

The tool lists are enforced in code (`backend/mcp_link.py` `ROLE_TOOLS`): an agent never sees another role's tools. Write roles are enforced a second time on the server (`requested_by` is checked against each write tool's allowed roles).

### 3.2 Data types (`backend/models.py`)
- `TeamDeps`: run context passed to every agent: `run_id`, `ticket_id`, `agent`, `chain` (the delegation path), `depth`, and a shared `TicketBudget` (hand-offs used).
- `Fact`: `label`, `value`, `source_tool`. A value copied from a tool result.
- `SpecialistReport`: `agent`, `ticket_id`, `summary`, `facts`, `analysis` (computed numbers), `board_items_created`, `blockers`, `needs_human`, `recommendation`.
- `BossDecision`: `ticket_id`, `decision` (`awaiting_human_approval` / `blocked` / `resolved` / `needs_more_info`), `summary`, `delegated_to`, `approval_ids`, `draft_ids`, `next_steps_for_human`.

### 3.3 The agent loop
1. `team.py` gives the Boss "Handle ticket N".
2. The Boss calls `get_ticket` and `list_board`, then `delegate(teammate, task)` with a self-contained task, **one hand-off per model turn** (`parallel_tool_calls = False`, added in Problem 7), so each specialist sees the previous one's report.
3. Each specialist runs its own PydanticAI loop (model → MCP tool calls → model …) and returns a `SpecialistReport`. Its token usage is rolled into the caller's budget.
4. **Full connectivity:** every specialist also has `delegate`, so any agent can hand work to any other. In testing, Customer Service, given no restock facts, delegated to Inventory at depth 2 and cited the result.
5. The Boss returns a `BossDecision`. The backend records it on the board via MCP `record_ticket_decision`.
6. Tickets run one at a time, so later tickets see the cash commitments earlier ones put on the board (in the full run, ticket 103's analysis included ticket 101's PO and invoice request).

**Loop guards** (`agents/base.py` `delegate`): an agent can't delegate to itself or anyone already on its chain (no cycles); the depth limit is 2 (Boss → specialist → peer, and the peer cannot delegate further); and each ticket allows at most 8 hand-offs. A refused hand-off returns a reason to the model instead of failing, and it is logged as `delegation_refused`. All three guards were verified in Problem 5.

### 3.4 Validators (deterministic checks on model output)
- **Specialists: fact grounding.** Every `Fact.source_tool` must be a tool the agent actually called in this run, and every number in `Fact.value` must appear in that run's tool results; otherwise the model is sent back (`ModelRetry`, up to 2 retries). `agent` and `ticket_id` are overwritten from the run context.
- **Boss: decision integrity.** The Boss must have delegated at least once. Every `approval_id` and `draft_id` must exist on the board for that ticket. Every pending approval for the ticket must be listed. The decision can't be `resolved` while any approval is `pending_human`. Every draft for the ticket must be listed, and a `customer_order` or `price_override` ticket can't be decided until a customer draft exists, so a customer is never left without a reply (added in Problem 8).

---

## 4. Tools (MCP server)

**Server:** `mcp_server/server.py` (FastMCP 4.1.0), name `campus-customs`, connected through `.mcp.json`. Every agent gets its data through these tools. The backend has no other route to the database: `backend/` contains no SQLite code. (`team.py` copies the database file for a reset, but it never queries it.)
**Database:** `data/campus_customs_new.db`. Shop tables are read with SQLite `mode=ro`, so a shop-table write fails with `attempt to write a readonly database`. Agent writes go only to the three board tables (an `assert` guards the insert/update helpers). The one exception is the human-only `decide_request` (tool 16), which writes `payments`, `cash_accounts`, `invoices`, and `leases` inside a single transaction when a person approves. The server refuses to run against `campus_customs_original.db`.
**Grounding rule:** tools return only database rows plus arithmetic on them (shortfall, days overdue, margins, projected cash). Dates are always measured from `desk.date_today`, not the real clock. A miss returns `found: false` or `count: 0` with a `message`; it never guesses.

### 4.0 All tools

| # | Tool | Type | Tables | Used by | What it's for |
|---|---|---|---|---|---|
| 1 | `list_open_tickets()` | read | `tickets`, `ticket_decisions`, `desk` | Boss | The work queue plus each ticket's latest decision |
| 2 | `get_ticket(ticket_id)` | read | `tickets`, `desk` | all | One ticket as stored, plus which link fields (sku/size/qty/invoice_id/lease_id) are set |
| 3 | `check_inventory(sku, size?, requested_qty?)` | read | `inventory` | Inventory, Customer Service | On hand, aisle, `shortfall`, `can_fill` (4.1) |
| 4 | `find_unpaid_invoices(vendor_id?, invoice_id?)` | read | `invoices`, `vendors`, `desk` | Inventory, Accounting | Unpaid invoices, days overdue, `vendors_blocked_from_shipping` (4.2) |
| 5 | `check_lease_obligations(lease_id?)` | read | `leases`, `desk` | Accounting, Facilities | Rent, landlord, `next_due`, `days_until_due` (4.3) |
| 6 | `find_restock_vendor(sku)` | read | `inventory`, `vendors`, `invoices`, `desk` | Inventory | Vendor whose specialty supplies the SKU, `lead_days`, `earliest_arrival_if_ordered_today`, `blocked` plus blocking invoices |
| 7 | `get_pricing(sku, unit_price?, qty?)` | read | `pricing` | Accounting | Cost, list price, margin per unit and margin %, discount %, deal totals |
| 8 | `get_cash_position()` | read | `cash_accounts`, `payments`, `invoices`, `leases`, `approval_requests`, `desk` | Accounting | Balance, payments recorded, unpaid invoices, rent due within 30 days, pending POs, `projected_balance_after_obligations`, `shortfall` |
| 9 | `list_board(ticket_id?)` | read | `approval_requests`, `drafts`, `ticket_decisions` | all | What's already on the board, so work isn't duplicated |
| 10 | `submit_payment_request(kind, ref_id, ticket_id, reason)` | write | reads `invoices`/`leases`/`vendors`/`cash_accounts`; writes `approval_requests` | Accounting only | Invoice or rent payment for human approval; the amount comes from the DB |
| 11 | `submit_purchase_order(vendor_id, sku, size, qty, ticket_id, reason)` | write | reads `inventory`, `vendors`, `invoices`, `pricing`; writes `approval_requests` | Accounting only | Restock PO, amount = `unit_cost` × qty, `blocked_by` the vendor's unpaid invoice |
| 12 | `submit_price_quote(ticket_id, sku, size, qty, unit_price, reason)` | write | reads `pricing`; writes `approval_requests` | Accounting only | Discount proposal; refused below cost or above list |
| 13 | `save_draft(ticket_id, audience, recipient, subject, body)` | write | reads `tickets`, `leases`, `vendors`; writes `drafts` | Customer Service (customer), Facilities (landlord/city), Inventory (vendor) | Message draft, never sent; the recipient must match the ticket, lease, or vendor on record |
| 14 | `record_ticket_decision(...)` | write | reads `tickets`, `approval_requests`, `drafts`; writes `ticket_decisions` | Boss role (called by the backend) | The Boss's final call; the `tickets` row itself is untouched |
| 15 | `list_tickets()` | read | `tickets`, `ticket_decisions`, `approval_requests` | Backend (dashboard), no agent | Every ticket with `status` (resolved once the run finishes) and `stage` (not_started / needs_approval / complete / blocked / needs_more_info) |
| 16 | `decide_request(request_id, action, decided_by)` | **human-only write** | writes `payments`, `cash_accounts`, `invoices.status`, `leases.next_due`, `approval_requests.status` | Backend approval route only; role `human`; in no agent's toolset | Approve or reject a board request; **the only place cash moves** (Problem 7) |

**Assumption (documented in code):** the database has no SKU → vendor column, so `find_restock_vendor` maps SKU prefix → `vendors.specialty` (`CC-HOOD`/`CC-TEE`/`CC-HAT` → apparel reprint; `CC-MUG` → mugs and small goods). QuickShip CT (courier) is never a restock source.

### 4.0.1 New tools per ticket (Problem 5)

| Ticket | New tools that unlock it | Full-run result |
|---|---|---|
| 101 tee S | `find_restock_vendor("CC-TEE-WHITE")` → Bulldog Print Co, 5 days, blocked by invoice 501. `submit_payment_request("invoice", 501)` → $840. `submit_purchase_order(1, "CC-TEE-WHITE", "S", 1)` → $8, blocked. `save_draft(customer, "Tauhid Zaman")` | Requests 1 (PO $8) and 2 (invoice $840), draft 1 |
| 102 rent | `submit_payment_request("rent", 1)` → $2,400. `save_draft(landlord, "Elm City Properties")`. `get_cash_position` → $1,000 left after rent alone | Request 3 (rent $2,400), draft 2 |
| 103 bulk hoodies | `get_pricing("CC-HOOD-NAVY", 52.20, 20)` → 10% off, still above cost. `submit_price_quote` → $52.20 × 20. `submit_purchase_order(1, …, "M", 12)` → $264, blocked. `get_cash_position` → obligations exceed cash by $112 | Requests 4 (quote) and 5 (PO $264), draft 3 |

### 4.1 `check_inventory(sku, size?, requested_qty?)`

| | |
|---|---|
| **Reads** | `inventory`: `sku`, `name`, `size`, `qty`, `location`. It matches the `(sku, size)` primary key case-insensitively. |
| **Returns** | The matching row(s). With `size` and `requested_qty`, it also returns `on_hand`, `shortfall = max(0, requested_qty − qty)`, and `can_fill`. |
| **Unlocks** | **Ticket 101**: `check_inventory("CC-TEE-WHITE", "S", 1)` returns on_hand 0, shortfall 1, can_fill false. **Ticket 103**: `check_inventory("CC-HOOD-NAVY", "M", 20)` returns on_hand 8, shortfall 12, can_fill false. |
| **Why this tool** | Tickets 101 and 103 each name an exact `sku`, `size`, and `qty`, and `inventory` is the only table keyed on `(sku, size)`. Its `shortfall` is exactly the number Inventory needs to know whether to ship from stock (101: no) or how many units to reprint (103: 12). |

### 4.2 `find_unpaid_invoices(vendor_id?, invoice_id?)`

| | |
|---|---|
| **Reads** | `invoices` (`id`, `vendor_id`, `amount`, `due_date`, `status`, `description`) LEFT JOIN `vendors` (`name`, `specialty`, `lead_days`) on `vendor_id`, plus `desk.date_today`. It keeps rows where `LOWER(status) <> 'paid'`. |
| **Returns** | Each unpaid invoice with `days_overdue = date_today − due_date`, plus `total_unpaid` and `vendors_blocked_from_shipping`. |
| **Unlocks** | **Ticket 101**: the ticket's `invoice_id = 501` → `find_unpaid_invoices(invoice_id=501)` returns $840 to Bulldog Print Co (vendor 1, apparel reprint, 5 lead days), due 2026-08-28, 3 days overdue, vendor 1 blocked. It also matters for **Ticket 103**: `find_unpaid_invoices(vendor_id=1)` shows the 12-hoodie reprint is blocked by the same invoice. |
| **Why this tool** | Ticket 101's tee can only be restocked by Bulldog Print Co, and the shop rule says a vendor won't ship while it has an unpaid invoice. Joining `invoices` to `vendors` answers both "is the restock blocked?" and "what must Accounting put up for human approval to unblock it?" ($840, invoice 501) in one call. |

### 4.3 `check_lease_obligations(lease_id?)`

| | |
|---|---|
| **Reads** | `leases` (`id`, `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes`) and `desk.date_today`. |
| **Returns** | Each lease with `days_until_due = next_due − date_today`, `due_status` (`overdue` / `due_today` / `upcoming`), and `total_rent_due`. |
| **Unlocks** | **Ticket 102**: the ticket's `lease_id = 1` → `check_lease_obligations(1)` returns Chapel Street shop, Elm City Properties, $2,400 due 2026-09-02, 2 days out, `upcoming`. |
| **Why this tool** | Ticket 102 is an email that only claims rent is "due in 2 days." Facilities must check that claim against the lease on record (landlord, amount, due date) before Accounting prepares a $2,400 payment for human approval, and `leases` via the ticket's `lease_id` is the only source of those facts. |

### 4.4 Connection & smoke test (Problem 4)

- **Connection:** `.mcp.json` at the project root registers the stdio server `campus-customs`. It runs `.venv/bin/python mcp_server/server.py` with `CC_DB_PATH=data/campus_customs_new.db`, a relative path that the server resolves from the project root so the repo works on any machine.
- **Smoke test:** `.venv/bin/python tools/mcp_smoke.py` launches the server from `.mcp.json` over a live stdio connection and sends 8 natural-language prompts to `gpt-6-luna`. The model picks the tool and arguments, and the call goes through MCP. Each output is then checked against a separate SQL query on `data/campus_customs_new.db`.
- **Result:** saved to `output/mcp_smoke.json`. All 8 passed: 3 for `check_inventory` (including a trap case asking for a mug in size M, where it correctly reported no size M and listed OS), 3 for `find_unpaid_invoices`, and 2 for `check_lease_obligations`. The database checksum was unchanged after the run.


---

## 5. Approvals & human-in-the-loop

- **Every payment needs human approval, with no exceptions.** Agents only create `approval_requests` rows with `status = 'pending_human'`. No agent tool can set `approved`, insert into `payments`, change `invoices.status`, or change `cash_accounts.balance`.
- **The human decides through `POST /api/approvals/{id}/approve` or `/reject`** (section 7). This calls the human-only MCP tool `decide_request` in one SQLite transaction:

  | Request | On approve |
  |---|---|
  | `invoice_payment` | Inserts `payments` (kind `invoice`), debits checking, sets `invoices.status = 'paid'` (which unblocks the vendor) |
  | `rent_payment` | Inserts `payments` (kind `rent`), debits checking, advances `leases.next_due` one month |
  | `purchase_order` | **Refused while the vendor has an unpaid invoice**; otherwise inserts `payments` (kind `purchase_order`, ref_id = request id) and debits checking. Stock arrives `lead_days` later and the human updates inventory then. |
  | `price_quote` | Signed off; no cash moves (revenue isn't modeled) |

  Refusals: no overdraft (the amount must be ≤ the balance), no double approval, `decided_by` must be a person's name (not an agent's), and nothing can be decided during an agent run. Every decision (and every refused attempt) is logged as `human_decision`.
- **A ticket is `resolved` when its agent run finishes** with the Boss deciding `resolved` or `awaiting_human_approval` (rule changed in Problem 8 at the user's request). `blocked` and `needs_more_info` keep it `open`. A separate `stage` shows what's next: `not_started`, `running`, `needs_approval` (pending requests for the human), `complete`, `blocked`, or `needs_more_info`. So a resolved ticket can still be waiting on you, but no money moves until you approve.
- **Purchase orders and price quotes also wait for a human.** A PO commits cash. A quote commits a customer-facing price.
- **Drafts are never sent.** The `drafts.sent` column has `CHECK (sent = 0)`, so even a bug can't mark one sent. No tool emails, calls, or contacts anyone.
- **What the human sees per ticket:** the Boss's `next_steps_for_human` (ordered actions with ids and amounts), the requests (`amount`, `detail`, `reason`, `blocked_by`), and the drafts.
- **Full-run board (reset → 3 tickets):** 5 pending requests (PO $8, invoice $840, rent $2,400, quote $1,044 revenue, PO $264), 3 drafts, 3 `awaiting_human_approval` decisions. `payments` stayed empty, cash stayed $3,400, invoice 501 stayed `open`, and inventory was unchanged.

---

## 6. Safety: guardrails & token limits

### 6.1 Guardrails a real business with real customers needs

| Risk | Guardrail | Where |
|---|---|---|
| Money leaves without a human | Agents can only create `pending_human` requests; no tool writes `payments`/`invoices`/`cash_accounts` | MCP server (no such tool; shop tables opened read-only) |
| Model invents or mistypes an amount | Request amounts are computed by the server from `invoices.amount`, `leases.monthly_rent`, or `pricing.unit_cost × qty`; the model never supplies a dollar figure | `submit_payment_request`, `submit_purchase_order`, `submit_price_quote` |
| Selling at a loss / unauthorized discount | Quotes below `unit_cost` or above `list_price` are refused; quotes wait for human sign-off; Customer Service may only mention a quote as "pending confirmation" | `submit_price_quote`, `prompts/customer_service.md` |
| Ordering from a vendor that won't ship | POs to a vendor with unpaid invoices are recorded with `blocked_by`; the vendor's specialty must match the SKU; qty is capped at 1–200 | `submit_purchase_order` |
| Paying the same bill twice | Identical pending requests are reused, not duplicated; already-paid invoices are refused; an approved request can't be approved again | `_pending()` checks in the write tools, `decide_request` |
| Overdraft / paying a vendor that won't ship | Approval is refused if the amount exceeds the checking balance, or if a PO's vendor still has an unpaid invoice | `decide_request` |
| Agent approves its own request | `decide_request` requires role `human`; agents never have it, and the backend stamps agent calls with the agent's name | `mcp_link.WRITE_TOOLS`, `_require_role` |
| Customer left without a reply | The Boss's validator rejects a decision on a `customer_order` or `price_override` ticket until a customer draft exists, and every draft must be listed in the decision (added in Problem 8 after a run skipped Customer Service) | `agents/boss.py validate_decision` |
| Stale "vendor blocked" warning | Paying a vendor's last unpaid invoice clears `blocked_by` on its pending POs in the same transaction | `decide_request` |
| Board changes mid-run | One agent run at a time; approvals and resets are refused (409) while agents are running | `main._busy` lock |
| Messages reach real people | No send capability exists; `sent = 0` is enforced by a CHECK constraint; drafts with email addresses or phone numbers are rejected | `save_draft`, `drafts` schema |
| Message to the wrong person | Customer drafts must go to the ticket's `requester`, landlord drafts to a landlord on a lease, vendor drafts to a name in `vendors` | `save_draft` |
| Leaking internal matters to customers | The Customer Service prompt forbids mentioning invoices, vendor disputes, cash, rent, or approvals; it promises no date while a vendor is blocked | `prompts/customer_service.md` |
| Payment-redirect fraud ("pay this new account") | Facilities verifies landlord, amount, and due date against `leases` and never accepts a new amount, payee, or bank detail from an email | `prompts/facilities.md`, rent amount taken from `leases` |
| Hallucinated facts | Tools return only DB rows; specialists' `facts` are checked against this run's tool results; misses say "does not exist" | Server grounding + `validate_report` |
| Role overreach / impersonation | Each agent sees only its role's tools; write tools re-check the role; `requested_by` is stamped by the backend, not the model | `mcp_link.ROLE_TOOLS`, `_audit_and_attribute`, `_require_role` |
| Corrupting the source of truth | The server refuses `campus_customs_original.db`; that file is `chmod 444`; reset only copies original → working | `server._check_db`, `team.reset_db` |
| Wrong "today" | Every date calculation uses `desk.date_today`, never the system clock | Server `_today()` |
| Secrets exposure | `PORTKEY_API_KEY` is read from `.env` (git-ignored) and never logged; the audit trail records tool args and results, not headers or keys | `config.py`, `.gitignore` |
| No accountability | Every agent start and end, delegation, MCP call (args, result, ms), refusal, and decision is appended to `output/audit_trail.json` | `backend/audit.py` (section 10) |

### 6.2 Token and loop limits (`backend/config.py`)

| Limit | Value | Enforced by |
|---|---|---|
| Model | `gpt-6-luna` only, `reasoning_effort = low` | `config.py`, one shared model instance |
| Output per model response (reasoning included) | 4,000 tokens | `max_tokens` model setting |
| Per agent run | 10 model requests, 14 tool calls, 80,000 tokens | `UsageLimits` on every specialist run |
| Per ticket (whole team; teammates' usage rolls up to the Boss) | 40 model requests, 250,000 tokens | `UsageLimits` on the Boss run |
| Delegation | Depth 2, 8 hand-offs per ticket, no cycles | `delegate()` guards |
| Validation retries | 2 per agent run | `Agent(retries=2)` |
| MCP tool error retries | 1 | `MCPToolset(max_retries=1)` |
| Audit result preview | 1,500 characters per tool result | `audit.preview` |
| Concurrency | Tickets run sequentially; one MCP server process per run (CLI) or per app (API); the API allows one agent run at a time | `team.run`, `main._busy` |
| Boss hand-offs | One per model turn (`parallel_tool_calls = False`), so each specialist sees the previous report (added in Problem 7 after a test run showed Facilities and Accounting running in parallel on ticket 102) | `agents/boss.py` |

When a limit is hit, the agent run stops with `UsageLimitExceeded`, which is logged as `agent_error`. A specialist failure is returned to its caller as `{"failed": true, ...}` so the Boss can decide with what it has.

**Measured cost.** Problem 9 full run: 56 model requests and 164,057 tokens (101: 19 / 54,266; 102: 13 / 34,165; 103: 24 / 75,626). The 103 run cost more because of the peer hand-off and the quote math. Problem 5 full run, for comparison: 46 model requests and about 135,500 tokens in total. Ticket 101 used 17 requests and 50,500 tokens, ticket 102 used 11 and 28,074, and ticket 103 used 18 and 56,937. All were well inside the per-ticket caps.

---

## 7. Backend API

`backend/main.py` (FastAPI). Start it from `backend/` with the venv active: `uvicorn main:app --reload --port 8000`. Interactive docs are at `/docs`. Every route reads and writes shop data through MCP; the API holds one MCP server process for its lifetime.

- `GET /api/tickets`: returns tickets 101, 102, 103 with `status` open/resolved (resolved once the agent run finishes), the `stage`, `active_run_id` while agents run, the Boss's latest decision, the ticket's approval requests, and whether agents are running on it.
- `POST /api/tickets/{ticket_id}/run`: starts the agent team (Boss → specialists) on that ticket in the background and returns a `run_id` right away (202). Returns 409 if a run or reset is already in progress, and 404 for an unknown ticket.
- `GET /api/runs/{run_id}`: status of a run started through the API (queued/running/done/failed) with the Boss's decision and token usage once finished.
- `GET /api/activity?limit=&ticket_id=&run_id=&since_reset=`: recent agent activity, newest first (`since_reset=true` keeps only events after the last reset), from `output/audit_trail.json`. One entry per agent turn: who asked it, the task, every MCP tool it called (args, ok, ms), who it delegated to, what it said (its structured output), and usage. Also lists human decisions and resets.
- `GET /api/approvals?status=pending_human|approved|rejected|all&ticket_id=`: approval requests and drafts on the board, for the dashboard's approval queue.
- `POST /api/approvals/{request_id}/approve` (body `{"decided_by": "<name>"}`): human approval; the **only route that changes cash**. It records a payment, debits checking, and updates the invoice or lease (via MCP `decide_request`). It returns 409 with the reason when refused (overdraft, vendor blocked, already decided, agents running).
- `POST /api/approvals/{request_id}/reject` (body `{"decided_by": "<name>"}`): human rejection; marks the request rejected, and no cash moves.
- `GET /api/cash`: the current checking balance from `cash_accounts`, payments recorded, obligations (unpaid invoices, rent due within 30 days, pending POs), and the projected balance and shortfall.
- `POST /api/reset`: restores `data/campus_customs_new.db` from the original for a fresh run (clears the board; keeps the audit trail). Returns 409 while agents are running.
- `GET /api/health`: model name, MCP connection, shop date, and whether a run is in progress.

**Verified (Problem 7):** reset → `GET /api/tickets` showed all three open and `not_started` → `POST /api/tickets/102/run` → polled to `done` (12 requests, 31,712 tokens, Facilities then Accounting) → `GET /api/activity` showed both turns with tools and outputs → approving the rent request moved checking from $3,400 to $1,000 and inserted 1 payment → approving it again returned 409 → ticket 102 showed `resolved` → reset brought cash back to $3,400 with 0 payments.

---

## 8. Dashboard

`frontend/` (React 19, Vite 8, TypeScript; no UI library). Start it with `cd frontend && npm install && npm run dev`, which serves http://localhost:5173. It calls the API at `http://localhost:8000` (override with `VITE_API_BASE`). Design rationale is in `output/design.md`.

| Area | Shows | API |
|---|---|---|
| Top bar | Live/offline, shop date, model, "Approving as" name (required to approve), Reset shop (two-click) | `/api/health`, `POST /api/reset` |
| Tickets rail | 101, 102, 103 with an Open / ● Running / ✓ Resolved pill, stage, and ✋ pending count | `GET /api/tickets` |
| Workflow graph | Boss → specialists. The planned route (from Problem 6) is drawn as ghost edges before a run; during a run the hand-off edge animates and the active agent pulses with its current MCP tool call | `GET /api/activity?run_id=` (1.2s poll while running) |
| Activity feed | Every pickup, tool call, hand-off, and report-back, newest first; board writes tagged | `GET /api/activity` |
| On the board | Approval cards (💸 vendor payment, 🏠 rent, 📦 PO, 🏷️ quote) with two-click Approve / Reject, ⛔ blocked warnings, server refusals shown in place; drafts marked "never sent" | `GET /api/approvals?status=all`, `POST /api/approvals/{id}/approve|reject` |
| Run summary | The Boss's final call and next steps, planned vs. actual route check, and per-agent "actions completed" with board-write outcomes | `GET /api/activity?ticket_id=&since_reset=true` |
| Money rail | Checking balance (animates on change, with a −$ delta chip), cash vs. owed bars, shortfall warning, payments you approved, "Needs you" inbox across all tickets | `GET /api/cash`, `GET /api/approvals` |

**Agents can't approve.** The approve and reject buttons exist only in the UI, require a human name, are disabled while agents run, and call the only cash-moving route.

**Verified (Problem 8, live in the browser):**
1. Reset, then ran ticket 101 from the dashboard. The graph animated Boss → Inventory → Accounting → Customer Service, and the feed streamed the tool calls.
2. The ticket flipped to ✓ Resolved with "Needs your approval ✋ 2".
3. Approving the $8 PO first was refused in place ("Vendor 1 won't ship while invoice 501 ($840.00) is unpaid"), and cash stayed $3,400.
4. Approving invoice 501 took checking to $2,560 with a −$840 chip; then approving the PO took it to $2,552.
5. The ticket went to Complete, and the inbox emptied.
6. The tablet layout had no horizontal overflow.
7. Reset afterwards.

**Two bugs found and fixed:**
- The route check showed ⚠ on the first run because the Boss skipped Customer Service. Fixed with the customer-draft rule in section 6.1.
- A paid invoice left a stale ⛔ warning on its PO. Fixed in `decide_request`.

---

## 9. Run & reset procedure

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend
../.venv/bin/python team.py --all          # FULL RUN: resets data/campus_customs_new.db from the original, then every open ticket
../.venv/bin/python team.py --ticket 101   # one ticket against the current working DB (no reset)
../.venv/bin/python team.py --reset        # reset only
```

- **From the dashboard:** start the API (`cd backend && uvicorn main:app --reload --port 8000`) and the UI (`cd frontend && npm run dev`). Click **↺ Reset shop**, then **▶ Run agent team** on 101, 102, and 103 in order, approving or rejecting in **Needs you**.
- **Restart note:** `--reload` watches `backend/` only. After editing `mcp_server/server.py`, restart uvicorn so the MCP subprocess reloads.
- **From the dashboard backend directly:** `POST /api/reset`, then `POST /api/tickets/{id}/run` for 101, 102, and 103 in order.
- **A reset is mandatory before a full run.** `--all` always resets first: it copies `campus_customs_original.db` → `campus_customs_new.db`, verifies the checksums, and logs `db_reset`. The reset also clears the board tables.
- The original database is only ever read.

---

## 10. Audit trail

`output/audit_trail.json` is a JSON array that is **appended to and never wiped** between runs. Each write is atomic (temp file + rename), so a crash can't truncate it. Every event has `ts` (UTC), `event`, `run_id`, and usually `ticket_id` and `agent`.

| Event | Extra fields | Purpose |
|---|---|---|
| `run_start` / `run_end` | model, tickets, reset flag / per-ticket ok and total tokens | Bracket a run |
| `db_reset` | source, target, checksum | Proof the run started from original values |
| `agent_start` | depth, chain, task | Who was asked what, by whom (via chain) |
| `mcp_call` | tool, args (including stamped `requested_by`), ok, result preview or error, ms | Every fact and every board write, traceable to an agent |
| `delegation` / `delegation_refused` | to, task, depth, chain / reason | The agent-to-agent graph and guard hits |
| `agent_end` / `agent_error` | full structured output plus usage (requests, tool calls, tokens) / error type and message | What each agent concluded and what it cost |
| `decision_recorded` | decision_id, decision | The Boss's final call landing on the board |
| `human_decision` | request_id, action, decided_by, ok, kind, amount, cash_before, cash_after, payment / error | Every approval or rejection from the API, including refused attempts |

The Problem 9 run (reset → 3 tickets → 6 human decisions) appended 104 events, taking the trail from 226 to 330; nothing was removed. The first full run (Problem 5) produced 88 events: 52 MCP calls, 11 agent runs, 8 delegations, and 3 decisions. A follow-up verification run (`run_id` `peertest-…`) logged the specialist-to-specialist delegation and the three refusals.

---

## 11. Full run & results (Problem 9)

**Procedure (2026-10-14):**
1. `POST /api/reset`. All 9 shop tables were verified identical to `campus_customs_original.db`, checking was $3,400.00, and the board and `payments` were empty.
2. `POST /api/tickets/{id}/run` for 101, then 102, then 103, one at a time. All three finished with the Boss deciding `awaiting_human_approval`, so each ticket was **resolved**.
3. The human overseer (Charles Park) decided every request in the dashboard. The agents approved nothing.
4. `tools/problem9_report.py` built every artifact from `output/audit_trail.json` and the database (read-only). It refuses to write if the cash ledger doesn't reconcile to the cent, or if any Expected section in `desk_tickets.html` would change.

| Ticket | Route (Boss →) | Requests / tokens | Board | Human decisions | Cash effect |
|---|---|---|---|---|---|
| 101 | Inventory → Accounting → Customer Service ✓ | 19 / 54,266 | #1 invoice 501 $840.00 · #2 PO 1 × tee S $8.00 · draft to Tauhid Zaman | #1 approved, #2 approved | −$848.00 |
| 102 | Facilities → Accounting ✓ | 13 / 34,165 | #3 rent $2,400.00 · draft to Elm City Properties | #3 approved | −$2,400.00 |
| 103 | Inventory → Accounting (→ Inventory peer) → Customer Service | 24 / 75,626 | #4 quote 20 × $52.00 (10.3% off, 57.7% margin) · #5 PO 12 × hoodie M $264.00 · draft to Yale AI Club | #4 approved (no cash), #5 approve **refused** (overdraft: $152 < $264), then #5 rejected | $0.00 |

**Cash:** $3,400.00 start − $840.00 − $8.00 − $2,400.00 = **$152.00**, which equals `cash_accounts.balance` exactly. There are 3 `payments` rows totaling $3,248.00, and each approval's before/after balance chains to the next. Itemized in `desk_tickets.html` → Cash.

**Deviations from the Expected plan (shown honestly on the Actual tabs):**
- On ticket 103, Accounting delegated to Inventory directly (a depth-2 peer hand-off), which the plan didn't include.
- Also on 103, Accounting re-submitted invoice 501. The server's duplicate check returned the existing request #1, so nothing was duplicated.
- Every required tool in each Expected table was called by the expected agent, and no unexpected agent was called on any ticket.

**Fixes made during this problem:**
- The dashboard's balance animation could freeze mid-count in a hidden tab (it showed $75.59 instead of $152.00). It now jumps straight to the true value when the tab isn't visible or on first load.
- Report labels used "rejectd"; corrected to "rejected".

**Artifacts:**

| File | Contents |
|---|---|
| `output/desk_tickets.html` | Problem 6 Expected sections unchanged. Actual sections filled in (workflow that ran, delegations in order, every MCP call, board, decision, human approvals, expected-vs-actual checks). Cash tab ledger plus verification. Reflection tab (Problem 10): Expected vs Actual per ticket, what the Cash tab showed, three problems the team can solve, and three it can't (with what each would need). |
| `output/resolved_tickets.json` | Per ticket: id, final status and stage, outcome, run stats, route, each agent's contribution, tools, and board items, the board, human approvals with cash before/after, and the cash change |
| `output/resolved_board.html` | Double-clickable board with the cash reconciliation, a per-ticket summary, and a dashboard screenshot per ticket |
| `output/screenshots/ticket_10{1,2,3}.jpg` | The React dashboard with each ticket selected, after it was resolved and its approvals were decided |
| `output/audit_trail.json` | 330 events in total; the Problem 9 run was appended |
| `tools/problem9_report.py` | Rerunnable generator for all of the above |
