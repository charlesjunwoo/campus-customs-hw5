# Campus Customs MCP Server

**What it's for:** this is the shared tool belt for the Campus Customs agent team (Boss, Inventory, Accounting, Facilities, Customer Service). Agents don't query the database themselves. They call these MCP tools, which return only rows that exist in the shop database, so agents can't invent stock levels, bills, or due dates.

**Database:** `data/campus_customs_new.db`, the working copy. You can point to a different file with the `CC_DB_PATH` environment variable. The server **refuses** `data/campus_customs_original.db`, the read-only source of truth.

**Access rules**
- **Shop tables are read-only to agents** (`desk`, `tickets`, `inventory`, `pricing`, `vendors`, `invoices`, `cash_accounts`, `payments`, `leases`). They are opened with SQLite `mode=ro`. The only exception is `decide_request`, the human-only tool the approval route calls.
- **Agents write only to the board.** The board is three tables the server creates in the working copy:
  - `approval_requests`: payments, purchase orders, and price quotes, all `pending_human`.
  - `drafts`: messages that are never sent.
  - `ticket_decisions`: the Boss's final calls.
- **Amounts are computed here from the database**, never supplied by the caller.
- **Write tools check the caller's role** through `requested_by`, which the backend stamps with the calling agent's name.

**"Today":** every due-date calculation uses `desk.date_today` (2026-08-31 in the original data), never the real clock.

## Tools (16)

### Read

| Tool | Arguments | Reads | Returns |
|---|---|---|---|
| `list_open_tickets` | none | `tickets`, `ticket_decisions` | Open tickets plus each one's latest Boss decision |
| `get_ticket` | `ticket_id` | `tickets` | The ticket row as stored, plus which link fields (sku/size/qty/invoice_id/lease_id) are set |
| `check_inventory` | `sku`, optional `size`, optional `requested_qty` | `inventory` | On hand and aisle; with `requested_qty`, also `shortfall` and `can_fill`. A miss lists the sizes on record. |
| `find_unpaid_invoices` | optional `vendor_id`, optional `invoice_id` | `invoices` ⨝ `vendors`, `desk` | Invoices with status ≠ `paid`, with `days_overdue`, `total_unpaid`, and `vendors_blocked_from_shipping` |
| `check_lease_obligations` | optional `lease_id` | `leases`, `desk` | Landlord, space, rent, and `next_due`, plus `days_until_due` and `due_status` |
| `find_restock_vendor` | `sku` | `inventory`, `vendors`, `invoices`, `desk` | The vendor whose specialty supplies the SKU, `lead_days`, `earliest_arrival_if_ordered_today`, and `blocked` plus blocking invoices |
| `get_pricing` | `sku`, optional `unit_price`, optional `qty` | `pricing` | Cost, list price, margin per unit and margin %, discount % vs list, and deal totals |
| `get_cash_position` | none | `cash_accounts`, `payments`, `invoices`, `leases`, `approval_requests`, `desk` | Balance, payments recorded, unpaid invoices, rent due within 30 days, pending POs, projected balance, and shortfall |
| `list_board` | optional `ticket_id` | `approval_requests`, `drafts`, `ticket_decisions` | Everything already on the board |
| `list_tickets` | none | `tickets`, `ticket_decisions`, `approval_requests` | Every ticket with a derived `status` (open/resolved) and `stage`; used by the dashboard API |

### Write (board only; nothing is paid, ordered, or sent)

| Tool | Allowed role | Writes | Notes |
|---|---|---|---|
| `submit_payment_request` | accounting | `approval_requests` | `kind` is invoice or rent. The amount comes from `invoices.amount` or `leases.monthly_rent`. Paid invoices and duplicates are refused. |
| `submit_purchase_order` | accounting | `approval_requests` | Amount = `pricing.unit_cost` × qty. The vendor must supply the SKU and qty must be 1–200. The PO carries `blocked_by` if the vendor has an unpaid invoice. |
| `submit_price_quote` | accounting | `approval_requests` | Refused below unit cost or above list price. Records the margin. |
| `save_draft` | customer_service → customer; facilities → landlord/city; inventory → vendor | `drafts` | The recipient must match the ticket requester, a lease landlord, or a vendor name. Emails and phone numbers are rejected. `sent` is always 0. |
| `record_ticket_decision` | boss | `ticket_decisions` | All referenced approval and draft ids must exist for the ticket. The `tickets` row is not modified. |

### Human-only (the dashboard API calls it; no agent has it)

| Tool | Allowed role | Writes | Notes |
|---|---|---|---|
| `decide_request` | human | `payments`, `cash_accounts`, `invoices`, `leases`, `approval_requests` | Approve or reject a board request in one transaction. **This is the only place cash moves.** Approving debits checking and records a payment: an invoice is marked `paid`, rent advances `leases.next_due`, and a PO is refused while its vendor has an unpaid invoice. A quote is signed off with no cash moving. Overdrafts and double approvals are refused. |

## Connecting

The project-root `.mcp.json` registers this server as `campus-customs` (stdio). MCP clients launch it from the project root. That includes Claude Code and the PydanticAI team in `backend/`, which connects through `backend/mcp_link.py` and has no other route to the database.

```bash
python3 -m venv .venv
.venv/bin/pip install -r mcp_server/requirements.txt
.venv/bin/python tools/mcp_smoke.py    # connects via .mcp.json, runs 8 prompts through gpt-6-luna -> output/mcp_smoke.json
```
