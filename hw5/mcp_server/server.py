"""Campus Customs MCP server: the shared tool belt for every agent on the team.

  * Framework: FastMCP
  * Database:  data/campus_customs_new.db (the working copy; override with CC_DB_PATH).
               The original, data/campus_customs_original.db, is refused outright.
  * Shop data: read-only to agents. Shop-table queries open the file with SQLite `mode=ro`.
               The ONLY tool that changes shop tables is `decide_request`, which is human-only:
               the dashboard backend calls it when a person clicks Approve, and it is the one
               place cash moves (payments insert + cash_accounts debit, in one transaction).
               No agent's toolset includes it.
  * The board: agents write only to three agent-owned tables, created here on first use:
               approval_requests (payments / purchase orders / price quotes awaiting a
               human), drafts (messages that are never sent), and ticket_decisions (the
               Boss's final call). Money amounts on the board are computed here from the
               database; the model never types an amount.
  * Grounding: tools return only rows that exist in the database plus arithmetic on them
               (shortfall, days overdue, margins, projected cash), always measured from
               desk.date_today, never the real clock. Misses are reported, not guessed.
  * Roles:     write tools take `requested_by`; the backend overwrites it with the calling
               agent's name, and each write tool accepts only the roles allowed to use it.

Run: `.venv/bin/python mcp_server/server.py` (stdio). Connection config: ../.mcp.json
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = (PROJECT_ROOT / os.getenv("CC_DB_PATH", "data/campus_customs_new.db")).resolve()  # relative = from project root

# The database has no SKU -> vendor link, so restock routing uses this documented rule:
# SKU prefix -> the vendors.specialty that supplies it. (Courier vendors deliver; they don't restock.)
SKU_SPECIALTY = {
    "CC-HOOD": "apparel reprint",
    "CC-TEE": "apparel reprint",
    "CC-HAT": "apparel reprint",
    "CC-MUG": "mugs and small goods",
}

MAX_PO_QTY = 200                # largest purchase order a single request may carry
RENT_HORIZON_DAYS = 30          # rent due within this many days counts as a near-term obligation
MAX_DRAFT_CHARS = 2000
CONTACT_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s().-]{8,}\d")  # emails / phone numbers

mcp = FastMCP(
    name="campus-customs",
    instructions=(
        "Tools over the Campus Customs shop database. 'Today' is desk.date_today, not the real date. "
        "Shop tables are read-only; agents write only to the board (approval requests, drafts, decisions), "
        "and nothing on the board is paid or sent until a human acts. "
        "Report only what these tools return; if a tool says a row was not found, say that."
    ),
)


# --- database helpers --------------------------------------------------------

def _check_db() -> None:
    if DB_PATH.name == "campus_customs_original.db":
        raise ToolError("Refusing to use campus_customs_original.db; it is the read-only source of truth.")
    if not DB_PATH.exists():
        raise ToolError(f"Database not found at {DB_PATH}. Create the working copy first.")


def _connect(write: bool = False) -> sqlite3.Connection:
    _check_db()
    conn = sqlite3.connect(DB_PATH) if write else sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    _ensure_board()
    with _connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _insert(table: str, row: dict[str, Any]) -> int:
    assert table in BOARD_TABLES, "agents may only write to board tables"
    _ensure_board()
    cols = ", ".join(row)
    with _connect(write=True) as conn:
        cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        return int(cur.lastrowid)


def _update(table: str, row_id: int, changes: dict[str, Any]) -> None:
    assert table in BOARD_TABLES, "agents may only write to board tables"
    sets = ", ".join(f"{k} = ?" for k in changes)
    with _connect(write=True) as conn:
        conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*changes.values(), row_id))


def _today() -> date:
    with _connect() as conn:
        row = conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    if not row or not row["date_today"]:
        raise ToolError("desk.date_today is empty, so there is no shop date to measure due dates against.")
    return date.fromisoformat(row["date_today"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_role(requested_by: str, allowed: set[str], action: str) -> str:
    who = (requested_by or "").strip().lower()
    if who not in allowed:
        raise ToolError(f"Role '{requested_by}' may not {action}. Allowed: {', '.join(sorted(allowed))}.")
    return who


def _ticket(ticket_id: int) -> dict[str, Any]:
    rows = _query("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if not rows:
        raise ToolError(f"Ticket {ticket_id} does not exist.")
    return rows[0]


# --- the board (agent-owned tables) ------------------------------------------------

BOARD_TABLES = {"approval_requests", "drafts", "ticket_decisions"}
BOARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER REFERENCES tickets(id),
    kind TEXT NOT NULL CHECK (kind IN ('invoice_payment', 'rent_payment', 'purchase_order', 'price_quote')),
    ref_table TEXT, ref_id INTEGER, vendor_id INTEGER REFERENCES vendors(id),
    sku TEXT, size TEXT, qty INTEGER, unit_price REAL,
    amount REAL NOT NULL,
    cash_out INTEGER NOT NULL CHECK (cash_out IN (0, 1)),
    blocked_by TEXT,
    detail TEXT,
    reason TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_human' CHECK (status IN ('pending_human', 'approved', 'rejected')),
    shop_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_by TEXT, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER REFERENCES tickets(id),
    audience TEXT NOT NULL CHECK (audience IN ('customer', 'landlord', 'city', 'vendor')),
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'rejected')),
    sent INTEGER NOT NULL DEFAULT 0 CHECK (sent = 0),
    shop_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    decision TEXT NOT NULL CHECK (decision IN ('awaiting_human_approval', 'blocked', 'resolved', 'needs_more_info')),
    summary TEXT NOT NULL,
    approval_ids TEXT NOT NULL,
    draft_ids TEXT NOT NULL,
    next_steps_for_human TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    shop_date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""
def _ensure_board() -> None:
    """Create the board tables if missing. Checked every call (not cached) because a reset
    replaces the database file underneath a running server."""
    with _connect() as conn:
        have = conn.execute(f"SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name IN "
                            f"({', '.join('?' * len(BOARD_TABLES))})", tuple(BOARD_TABLES)).fetchone()[0]
    if have < len(BOARD_TABLES):
        with _connect(write=True) as conn:
            conn.executescript(BOARD_SCHEMA)


def _unpaid_invoices(vendor_id: int | None = None) -> list[dict[str, Any]]:
    sql = """SELECT i.id AS invoice_id, i.vendor_id, v.name AS vendor_name, i.amount, i.due_date, i.status
             FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id WHERE LOWER(i.status) <> 'paid'"""
    params: tuple = ()
    if vendor_id is not None:
        sql += " AND i.vendor_id = ?"
        params = (vendor_id,)
    return _query(sql + " ORDER BY i.due_date, i.id", params)


def _pending(kind: str, **match: Any) -> dict[str, Any] | None:
    where = " AND ".join(f"{k} IS ?" for k in match)
    rows = _query(f"SELECT * FROM approval_requests WHERE kind = ? AND status = 'pending_human' AND {where}",
                  (kind, *match.values()))
    return rows[0] if rows else None


# ======================================================================================
# READ TOOLS
# ======================================================================================

@mcp.tool
def list_open_tickets() -> dict[str, Any]:
    """List every ticket whose status is 'open', with the Boss's latest recorded decision (if any).

    Reads `tickets` (all columns) and `ticket_decisions`. Use this to see the work queue.
    """
    rows = _query("SELECT * FROM tickets WHERE status = 'open' ORDER BY created_at, id")
    for r in rows:
        d = _query("SELECT decision, summary, created_at FROM ticket_decisions WHERE ticket_id = ? "
                   "ORDER BY id DESC LIMIT 1", (r["id"],))
        r["latest_decision"] = d[0] if d else None
    return {"source_tables": ["tickets", "ticket_decisions"], "as_of": _today().isoformat(),
            "count": len(rows), "tickets": rows}


@mcp.tool
def get_ticket(ticket_id: int) -> dict[str, Any]:
    """Return one ticket row from `tickets` exactly as stored, plus which link fields are set.

    The link fields tell you which specialist owns which part: sku/size/qty -> Inventory (stock,
    restock) and Accounting (pricing); invoice_id -> Accounting; lease_id -> Facilities.
    """
    t = _ticket(ticket_id)
    links = {k: t[k] for k in ("sku", "size", "qty", "invoice_id", "lease_id") if t[k] is not None}
    return {"source_table": "tickets", "as_of": _today().isoformat(), "ticket": t, "links": links}


@mcp.tool
def check_inventory(sku: str, size: str | None = None, requested_qty: int | None = None) -> dict[str, Any]:
    """Look up units on hand for a SKU, optionally one size, from the `inventory` table.

    Args:
        sku: Product code, e.g. "CC-TEE-WHITE" (case-insensitive).
        size: S, M, L, XL, or OS. Omit to get every size of the SKU.
        requested_qty: Units the ticket needs. If given with a size, the result
            includes the shortfall (requested minus on hand, never below 0).
    """
    sku_n = sku.strip().upper()
    size_n = size.strip().upper() if size else None

    sql = "SELECT sku, name, size, qty, location FROM inventory WHERE UPPER(sku) = ?"
    params: tuple = (sku_n,)
    if size_n:
        sql += " AND UPPER(size) = ?"
        params += (size_n,)
    rows = _query(sql + " ORDER BY rowid", params)

    result: dict[str, Any] = {"source_table": "inventory", "sku": sku_n, "size": size_n, "found": bool(rows), "rows": rows}

    if not rows:
        sizes = [r["size"] for r in _query("SELECT size FROM inventory WHERE UPPER(sku) = ? ORDER BY rowid", (sku_n,))]
        result["message"] = (
            f"SKU {sku_n} has no size {size_n} in inventory; sizes on record: {', '.join(sizes)}."
            if sizes else f"SKU {sku_n} does not exist in inventory."
        )
        return result

    if requested_qty is not None:
        if len(rows) == 1:
            on_hand = rows[0]["qty"]
            result.update(requested_qty=requested_qty, on_hand=on_hand,
                          shortfall=max(0, requested_qty - on_hand), can_fill=on_hand >= requested_qty)
        else:
            result["message"] = "Pass a size to compute a shortfall; this SKU has several sizes."
    return result


@mcp.tool
def find_unpaid_invoices(vendor_id: int | None = None, invoice_id: int | None = None) -> dict[str, Any]:
    """List vendor invoices that are not paid, from `invoices` joined to `vendors`.

    An invoice counts as unpaid unless its status is 'paid'; the raw status is
    returned too. Shop rule: a vendor with any unpaid invoice will not ship new
    product, so every vendor in the result is listed in `vendors_blocked_from_shipping`.
    Days overdue are measured from desk.date_today.

    Args:
        vendor_id: Only this vendor's invoices.
        invoice_id: Only this invoice (e.g. the invoice_id on a ticket).
    """
    today = _today()
    sql = """
        SELECT i.id AS invoice_id, i.vendor_id, v.name AS vendor_name, v.specialty AS vendor_specialty,
               v.lead_days AS vendor_lead_days, i.amount, i.due_date, i.status, i.description
        FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id
        WHERE LOWER(i.status) <> 'paid'
    """
    params: tuple = ()
    if vendor_id is not None:
        sql += " AND i.vendor_id = ?"
        params += (vendor_id,)
    if invoice_id is not None:
        sql += " AND i.id = ?"
        params += (invoice_id,)
    rows = _query(sql + " ORDER BY i.due_date, i.id", params)

    for r in rows:
        late = (today - date.fromisoformat(r["due_date"])).days
        r["days_overdue"] = max(0, late)
        r["is_overdue"] = late > 0

    blocked = sorted({(r["vendor_id"], r["vendor_name"]) for r in rows})
    result: dict[str, Any] = {
        "source_tables": ["invoices", "vendors", "desk"],
        "as_of": today.isoformat(),
        "count": len(rows),
        "total_unpaid": round(sum(r["amount"] for r in rows), 2),
        "invoices": rows,
        "vendors_blocked_from_shipping": [{"vendor_id": vid, "vendor_name": name} for vid, name in blocked],
    }

    if not rows:
        if invoice_id is not None:
            hit = _query("SELECT status FROM invoices WHERE id = ?", (invoice_id,))
            result["message"] = (f"Invoice {invoice_id} exists with status '{hit[0]['status']}', so it is not unpaid."
                                 if hit else f"Invoice {invoice_id} does not exist.")
        elif vendor_id is not None and not _query("SELECT 1 FROM vendors WHERE id = ?", (vendor_id,)):
            result["message"] = f"Vendor {vendor_id} does not exist."
        else:
            result["message"] = "No unpaid invoices match."
    return result


@mcp.tool
def check_lease_obligations(lease_id: int | None = None) -> dict[str, Any]:
    """Return rent owed on the shop's leases and when it is due, from the `leases` table.

    `days_until_due` is next_due minus desk.date_today (negative means overdue).

    Args:
        lease_id: Only this lease (e.g. the lease_id on a ticket). Omit for all leases.
    """
    today = _today()
    sql = "SELECT id AS lease_id, space_name, landlord, monthly_rent, next_due, notes FROM leases"
    params: tuple = ()
    if lease_id is not None:
        sql += " WHERE id = ?"
        params = (lease_id,)
    rows = _query(sql + " ORDER BY next_due, id", params)

    for r in rows:
        days = (date.fromisoformat(r["next_due"]) - today).days
        r["days_until_due"] = days
        r["due_status"] = "overdue" if days < 0 else "due_today" if days == 0 else "upcoming"

    result: dict[str, Any] = {
        "source_tables": ["leases", "desk"],
        "as_of": today.isoformat(),
        "count": len(rows),
        "total_rent_due": round(sum(r["monthly_rent"] for r in rows), 2),
        "leases": rows,
    }
    if not rows:
        result["message"] = f"Lease {lease_id} does not exist." if lease_id is not None else "No leases on record."
    return result


@mcp.tool
def find_restock_vendor(sku: str) -> dict[str, Any]:
    """Find which vendor can restock a SKU, its lead time, and whether it is blocked by an unpaid invoice.

    Reads `vendors` (name, specialty, lead_days), `invoices` (unpaid rows per vendor), and
    `desk.date_today`. The database has no SKU-to-vendor column, so the match uses the
    documented rule SKU prefix -> vendors.specialty (CC-HOOD/CC-TEE/CC-HAT -> 'apparel reprint',
    CC-MUG -> 'mugs and small goods'). `earliest_arrival` = date_today + lead_days and only
    applies once the vendor is unblocked.
    """
    today = _today()
    sku_n = sku.strip().upper()
    if not _query("SELECT 1 FROM inventory WHERE UPPER(sku) = ?", (sku_n,)):
        return {"source_tables": ["inventory"], "sku": sku_n, "found": False,
                "message": f"SKU {sku_n} does not exist in inventory."}

    prefix = next((p for p in SKU_SPECIALTY if sku_n.startswith(p + "-")), None)
    specialty = SKU_SPECIALTY.get(prefix) if prefix else None
    vendors = _query("SELECT id AS vendor_id, name, specialty, lead_days FROM vendors ORDER BY id")
    matches = []
    for v in vendors:
        if v["specialty"] != specialty:
            continue
        unpaid = _unpaid_invoices(v["vendor_id"])
        v["blocked"] = bool(unpaid)
        v["blocking_invoices"] = unpaid
        v["earliest_arrival_if_ordered_today"] = (today + timedelta(days=v["lead_days"])).isoformat()
        matches.append(v)

    result: dict[str, Any] = {
        "source_tables": ["vendors", "invoices", "desk"], "as_of": today.isoformat(), "sku": sku_n, "found": True,
        "match_rule": f"SKU prefix {prefix} -> specialty '{specialty}'" if specialty else "no rule for this SKU prefix",
        "vendors": matches,
        "can_ship_now": [v["name"] for v in matches if not v["blocked"]],
    }
    if not matches:
        result["message"] = "No vendor in the vendors table matches this SKU; do not invent one."
    return result


@mcp.tool
def get_pricing(sku: str, unit_price: float | None = None, qty: int | None = None) -> dict[str, Any]:
    """Return unit cost and list price for a SKU from `pricing`, with margin math for a proposed price.

    Args:
        sku: Product code.
        unit_price: A proposed selling price per unit (e.g. a discounted bulk price). Omit for list price.
        qty: Units in the deal; adds deal totals (revenue, cost, gross profit).
    """
    sku_n = sku.strip().upper()
    rows = _query("SELECT sku, unit_cost, list_price FROM pricing WHERE UPPER(sku) = ?", (sku_n,))
    if not rows:
        return {"source_table": "pricing", "sku": sku_n, "found": False, "message": f"SKU {sku_n} has no pricing row."}
    p = rows[0]
    cost, list_price = p["unit_cost"], p["list_price"]
    price = list_price if unit_price is None else float(unit_price)
    result: dict[str, Any] = {
        "source_table": "pricing", "sku": sku_n, "found": True, "unit_cost": cost, "list_price": list_price,
        "list_margin_per_unit": round(list_price - cost, 2),
        "list_margin_pct": round((list_price - cost) / list_price * 100, 1),
        "evaluated_unit_price": price,
        "discount_pct_vs_list": round((list_price - price) / list_price * 100, 1),
        "margin_per_unit": round(price - cost, 2),
        "margin_pct": round((price - cost) / price * 100, 1) if price else None,
        "below_cost": price < cost,
    }
    if qty is not None:
        result.update(qty=qty, deal_revenue=round(price * qty, 2), deal_cost=round(cost * qty, 2),
                      deal_gross_profit=round((price - cost) * qty, 2))
    return result


@mcp.tool
def get_cash_position() -> dict[str, Any]:
    """Return cash on hand and every known obligation against it, all from the database.

    Reads `cash_accounts` (balance), `payments` (money already paid out), `invoices` (unpaid),
    `leases` (rent due within 30 days of desk.date_today), and `approval_requests` (pending
    purchase orders, which become new cash out if approved). Revenue is not modeled: cash only
    goes down. `projected_balance_after_obligations` = balance minus unpaid invoices, near-term
    rent, and pending purchase orders.
    """
    today = _today()
    accounts = _query("SELECT name, balance, date FROM cash_accounts ORDER BY name")
    balance = round(sum(a["balance"] for a in accounts), 2)
    payments = _query("SELECT * FROM payments ORDER BY paid_at, id")
    invoices = _unpaid_invoices()
    rent = [l for l in check_lease_obligations()["leases"] if l["days_until_due"] <= RENT_HORIZON_DAYS]
    pos = _query("SELECT id, ticket_id, vendor_id, sku, size, qty, amount, blocked_by FROM approval_requests "
                 "WHERE kind = 'purchase_order' AND status = 'pending_human' ORDER BY id")
    inv_total = round(sum(i["amount"] for i in invoices), 2)
    rent_total = round(sum(l["monthly_rent"] for l in rent), 2)
    po_total = round(sum(p["amount"] for p in pos), 2)
    obligations = round(inv_total + rent_total + po_total, 2)
    return {
        "source_tables": ["cash_accounts", "payments", "invoices", "leases", "approval_requests", "desk"],
        "as_of": today.isoformat(),
        "accounts": accounts,
        "cash_balance": balance,
        "payments_recorded": payments,
        "unpaid_invoices": invoices, "unpaid_invoices_total": inv_total,
        "rent_due_within_30_days": rent, "rent_due_total": rent_total,
        "pending_purchase_orders": pos, "pending_purchase_orders_total": po_total,
        "total_obligations": obligations,
        "projected_balance_after_obligations": round(balance - obligations, 2),
        "shortfall": max(0.0, round(obligations - balance, 2)),
        "note": "Revenue is not modeled; no money comes in.",
    }


@mcp.tool
def list_board(ticket_id: int | None = None) -> dict[str, Any]:
    """Return what the team has already put on the board: approval requests, drafts, and Boss decisions.

    Reads `approval_requests`, `drafts`, `ticket_decisions`. Check this before creating a request
    or draft so you don't duplicate work.

    Args:
        ticket_id: Only items for this ticket. Omit for everything.
    """
    where, params = ("WHERE ticket_id = ?", (ticket_id,)) if ticket_id is not None else ("", ())
    return {
        "source_tables": ["approval_requests", "drafts", "ticket_decisions"],
        "approval_requests": _query(f"SELECT * FROM approval_requests {where} ORDER BY id", params),
        "drafts": _query(f"SELECT * FROM drafts {where} ORDER BY id", params),
        "decisions": _query(f"SELECT * FROM ticket_decisions {where} ORDER BY id", params),
    }


# ======================================================================================
# WRITE TOOLS (board only; nothing here moves money or contacts anyone)
# ======================================================================================

@mcp.tool
def submit_payment_request(kind: Literal["invoice", "rent"], ref_id: int, ticket_id: int, reason: str,
                           requested_by: str = "") -> dict[str, Any]:
    """Put a payment on the board for HUMAN approval. This does not pay anything.

    The amount is read from the database, not supplied by you: invoice -> invoices.amount for
    invoice `ref_id`; rent -> leases.monthly_rent for lease `ref_id`. Refuses paid or unknown
    invoices. Returns the existing request if an identical one is already pending.
    Only the accounting role may call this.

    Args:
        kind: "invoice" (pay a vendor invoice) or "rent" (pay a lease's monthly rent).
        ref_id: The invoice id or lease id.
        ticket_id: The ticket this payment unblocks.
        reason: One or two sentences for the human approver: why pay, and what it unblocks.
        requested_by: Set automatically by the backend to the calling agent.
    """
    who = _require_role(requested_by, {"accounting"}, "request payments")
    _ticket(ticket_id)
    today = _today()
    if kind == "invoice":
        rows = _query("SELECT i.*, v.name AS vendor_name FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id "
                      "WHERE i.id = ?", (ref_id,))
        if not rows:
            raise ToolError(f"Invoice {ref_id} does not exist.")
        inv = rows[0]
        if inv["status"].lower() == "paid":
            raise ToolError(f"Invoice {ref_id} is already paid.")
        db_kind, ref_table, amount, vendor_id = "invoice_payment", "invoices", inv["amount"], inv["vendor_id"]
        overdue = (today - date.fromisoformat(inv["due_date"])).days
        detail = (f"Invoice {ref_id} to {inv['vendor_name']}: ${inv['amount']:.2f}, due {inv['due_date']}"
                  + (f" ({overdue} days overdue)" if overdue > 0 else ""))
    else:
        rows = _query("SELECT * FROM leases WHERE id = ?", (ref_id,))
        if not rows:
            raise ToolError(f"Lease {ref_id} does not exist.")
        lease = rows[0]
        db_kind, ref_table, amount, vendor_id = "rent_payment", "leases", lease["monthly_rent"], None
        detail = f"Rent for {lease['space_name']} to {lease['landlord']}: ${amount:.2f}, due {lease['next_due']}"

    existing = _pending(db_kind, ref_id=ref_id)
    if existing:
        return {"created": False, "message": "An identical request is already pending human approval.",
                "request": existing}
    cash = get_cash_position()
    rid = _insert("approval_requests", {
        "ticket_id": ticket_id, "kind": db_kind, "ref_table": ref_table, "ref_id": ref_id, "vendor_id": vendor_id,
        "amount": amount, "cash_out": 1, "detail": detail, "reason": reason.strip()[:600], "requested_by": who,
        "shop_date": today.isoformat(), "created_at": _now()})
    return {"created": True, "request": _query("SELECT * FROM approval_requests WHERE id = ?", (rid,))[0],
            "cash_balance": cash["cash_balance"], "balance_if_paid": round(cash["cash_balance"] - amount, 2),
            "message": "Pending human approval. Nothing has been paid; the human records the payment."}


@mcp.tool
def submit_purchase_order(vendor_id: int, sku: str, size: str, qty: int, ticket_id: int, reason: str,
                          requested_by: str = "") -> dict[str, Any]:
    """Put a restock purchase order on the board for HUMAN approval. Nothing is ordered or paid.

    Amount = pricing.unit_cost x qty, computed here. Refuses a vendor whose specialty doesn't
    supply the SKU, a SKU/size not in inventory, or qty outside 1-200. If the vendor has an unpaid
    invoice, the PO is still recorded but marked `blocked_by` that invoice (the vendor won't ship
    until it is paid). Only the accounting role may call this.

    Args:
        vendor_id: Vendor to order from (see find_restock_vendor).
        sku: Product code.
        size: Size to restock.
        qty: Units to order (e.g. the shortfall from check_inventory).
        ticket_id: The ticket this restock serves.
        reason: One or two sentences for the human approver.
        requested_by: Set automatically by the backend to the calling agent.
    """
    who = _require_role(requested_by, {"accounting"}, "create purchase orders")
    _ticket(ticket_id)
    today = _today()
    sku_n, size_n = sku.strip().upper(), size.strip().upper()
    if not 1 <= qty <= MAX_PO_QTY:
        raise ToolError(f"qty must be between 1 and {MAX_PO_QTY}.")
    if not _query("SELECT 1 FROM inventory WHERE UPPER(sku) = ? AND UPPER(size) = ?", (sku_n, size_n)):
        raise ToolError(f"{sku_n} size {size_n} is not in inventory.")
    vendor = next((v for v in find_restock_vendor(sku_n).get("vendors", []) if v["vendor_id"] == vendor_id), None)
    if vendor is None:
        raise ToolError(f"Vendor {vendor_id} does not supply {sku_n} (see find_restock_vendor).")
    price = _query("SELECT unit_cost FROM pricing WHERE UPPER(sku) = ?", (sku_n,))
    if not price:
        raise ToolError(f"{sku_n} has no pricing row, so the PO amount can't be computed.")
    amount = round(price[0]["unit_cost"] * qty, 2)
    blocked_by = ", ".join(f"invoice {i['invoice_id']} (${i['amount']:.2f} unpaid)" for i in vendor["blocking_invoices"]) or None

    existing = _pending("purchase_order", vendor_id=vendor_id, sku=sku_n, size=size_n, ticket_id=ticket_id)
    if existing:
        return {"created": False, "message": "A PO for this ticket/vendor/SKU/size is already pending.", "request": existing}
    detail = (f"{qty} x {sku_n} {size_n} from {vendor['name']} at ${price[0]['unit_cost']:.2f} = ${amount:.2f}; "
              f"lead time {vendor['lead_days']} days"
              + (f"; earliest arrival {vendor['earliest_arrival_if_ordered_today']} if ordered today" if not blocked_by
                 else "; vendor will not ship until the blocking invoice is paid"))
    rid = _insert("approval_requests", {
        "ticket_id": ticket_id, "kind": "purchase_order", "ref_table": "vendors", "ref_id": vendor_id,
        "vendor_id": vendor_id, "sku": sku_n, "size": size_n, "qty": qty, "unit_price": price[0]["unit_cost"],
        "amount": amount, "cash_out": 1, "blocked_by": blocked_by, "detail": detail, "reason": reason.strip()[:600],
        "requested_by": who, "shop_date": today.isoformat(), "created_at": _now()})
    return {"created": True, "request": _query("SELECT * FROM approval_requests WHERE id = ?", (rid,))[0],
            "message": "Pending human approval. Nothing has been ordered or paid."}


@mcp.tool
def submit_price_quote(ticket_id: int, sku: str, size: str, qty: int, unit_price: float, reason: str,
                       requested_by: str = "") -> dict[str, Any]:
    """Put a proposed customer price (e.g. a bulk discount) on the board for HUMAN sign-off.

    Margin is computed here from `pricing`. Refuses a price below unit_cost (no selling at a loss)
    or above list_price. This records a proposal only; the customer is not told anything.
    Only the accounting role may call this.

    Args:
        ticket_id: The price-override ticket.
        sku: Product code. size: Size quoted. qty: Units quoted.
        unit_price: Proposed price per unit.
        reason: Why this price: the margin it keeps and any stock/lead-time caveat.
        requested_by: Set automatically by the backend to the calling agent.
    """
    who = _require_role(requested_by, {"accounting"}, "propose price quotes")
    _ticket(ticket_id)
    m = get_pricing(sku, unit_price, qty)
    if not m["found"]:
        raise ToolError(m["message"])
    if m["below_cost"]:
        raise ToolError(f"${unit_price:.2f} is below unit cost ${m['unit_cost']:.2f}; the shop does not sell at a loss.")
    if unit_price > m["list_price"]:
        raise ToolError(f"${unit_price:.2f} is above list price ${m['list_price']:.2f}.")
    sku_n, size_n = sku.strip().upper(), size.strip().upper()
    existing = _pending("price_quote", ticket_id=ticket_id, sku=sku_n, size=size_n)
    if existing:
        return {"created": False, "message": "A quote for this ticket/SKU/size is already pending.", "request": existing}
    detail = (f"{qty} x {sku_n} {size_n} at ${unit_price:.2f} (list ${m['list_price']:.2f}, "
              f"{m['discount_pct_vs_list']}% off); margin ${m['margin_per_unit']:.2f}/unit = {m['margin_pct']}%; "
              f"deal revenue ${m['deal_revenue']:.2f}, gross profit ${m['deal_gross_profit']:.2f}")
    rid = _insert("approval_requests", {
        "ticket_id": ticket_id, "kind": "price_quote", "sku": sku_n, "size": size_n, "qty": qty,
        "unit_price": float(unit_price), "amount": m["deal_revenue"], "cash_out": 0, "detail": detail,
        "reason": reason.strip()[:600], "requested_by": who, "shop_date": _today().isoformat(), "created_at": _now()})
    return {"created": True, "request": _query("SELECT * FROM approval_requests WHERE id = ?", (rid,))[0],
            "margin": m, "message": "Pending human sign-off. The customer has not been quoted."}


@mcp.tool
def save_draft(ticket_id: int, audience: Literal["customer", "landlord", "city", "vendor"], recipient: str,
               subject: str, body: str, requested_by: str = "") -> dict[str, Any]:
    """Save a message DRAFT to the board. Drafts are never sent; a human reviews them.

    Roles: customer_service -> customer; facilities -> landlord or city; inventory -> vendor.
    `recipient` must be a name, not an address: for customers it must equal the ticket's
    requester, for landlords the landlord on a lease, for vendors a name in `vendors`.
    Email addresses and phone numbers are rejected. Saving again for the same ticket,
    audience, and recipient updates the existing draft instead of adding another.

    Args:
        ticket_id: Ticket the message is about.
        audience: customer, landlord, city, or vendor.
        recipient: Person or organization name.
        subject: Short subject line.
        body: Message text (max 2000 characters).
        requested_by: Set automatically by the backend to the calling agent.
    """
    allowed = {"customer": {"customer_service"}, "landlord": {"facilities"}, "city": {"facilities"},
               "vendor": {"inventory"}}[audience]
    who = _require_role(requested_by, allowed, f"draft {audience} messages")
    t = _ticket(ticket_id)
    recipient = recipient.strip()
    if audience == "customer" and recipient != t["requester"]:
        raise ToolError(f"Customer drafts for ticket {ticket_id} must go to its requester, '{t['requester']}'.")
    if audience == "landlord" and not _query("SELECT 1 FROM leases WHERE landlord = ?", (recipient,)):
        raise ToolError(f"'{recipient}' is not a landlord on any lease.")
    if audience == "vendor" and not _query("SELECT 1 FROM vendors WHERE name = ?", (recipient,)):
        raise ToolError(f"'{recipient}' is not in the vendors table.")
    if len(body) > MAX_DRAFT_CHARS or not body.strip() or not subject.strip():
        raise ToolError(f"Subject and body are required; body max {MAX_DRAFT_CHARS} characters.")
    if CONTACT_PATTERN.search(recipient + " " + subject + " " + body):
        raise ToolError("Drafts may not contain email addresses or phone numbers.")

    row = {"subject": subject.strip()[:200], "body": body.strip(), "author": who, "updated_at": _now()}
    existing = _query("SELECT id FROM drafts WHERE ticket_id = ? AND audience = ? AND recipient = ? AND status = 'draft'",
                      (ticket_id, audience, recipient))
    if existing:
        _update("drafts", existing[0]["id"], row)
        did, created = existing[0]["id"], False
    else:
        did = _insert("drafts", {"ticket_id": ticket_id, "audience": audience, "recipient": recipient, **row,
                                 "shop_date": _today().isoformat(), "created_at": row["updated_at"]})
        created = True
    return {"created": created, "draft": _query("SELECT * FROM drafts WHERE id = ?", (did,))[0],
            "message": "Saved as a draft on the board. It has not been sent."}


@mcp.tool
def record_ticket_decision(ticket_id: int,
                           decision: Literal["awaiting_human_approval", "blocked", "resolved", "needs_more_info"],
                           summary: str, approval_ids: list[int], draft_ids: list[int],
                           next_steps_for_human: list[str], requested_by: str = "") -> dict[str, Any]:
    """Record the Boss's final call on a ticket. Only the boss role may call this.

    Every approval_id and draft_id must exist on the board for this ticket. The ticket row in
    `tickets` is not modified; the human closes tickets.
    """
    who = _require_role(requested_by, {"boss"}, "record ticket decisions")
    _ticket(ticket_id)
    for table, ids in (("approval_requests", approval_ids), ("drafts", draft_ids)):
        for i in ids:
            if not _query(f"SELECT 1 FROM {table} WHERE id = ? AND ticket_id = ?", (i, ticket_id)):
                raise ToolError(f"{table} id {i} does not exist for ticket {ticket_id}.")
    did = _insert("ticket_decisions", {
        "ticket_id": ticket_id, "decision": decision, "summary": summary.strip()[:2000],
        "approval_ids": json.dumps(approval_ids), "draft_ids": json.dumps(draft_ids),
        "next_steps_for_human": json.dumps(next_steps_for_human), "decided_by": who,
        "shop_date": _today().isoformat(), "created_at": _now()})
    return {"created": True, "decision": _query("SELECT * FROM ticket_decisions WHERE id = ?", (did,))[0]}


# ======================================================================================
# HUMAN-ONLY (called by the dashboard backend on a person's click; no agent has these)
# ======================================================================================

def _ticket_status(ticket: dict[str, Any]) -> dict[str, Any]:
    """open / resolved, derived from the board. A ticket is resolved once the agent run has finished
    with the Boss deciding 'resolved' or 'awaiting_human_approval'; any payments it prepared still wait
    for the human (stage 'needs_approval'). 'blocked' / 'needs_more_info' keep the ticket open."""
    decision = _query("SELECT * FROM ticket_decisions WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (ticket["id"],))
    reqs = _query("SELECT id, kind, amount, status FROM approval_requests WHERE ticket_id = ? ORDER BY id", (ticket["id"],))
    pending = [r for r in reqs if r["status"] == "pending_human"]
    d = decision[0] if decision else None
    if ticket["status"] != "open":            # the human closed it in the tickets table
        resolved = ticket["status"].lower() in {"resolved", "closed", "done"}
    else:
        resolved = bool(d) and d["decision"] in ("resolved", "awaiting_human_approval")
    if d:
        d = {**d, **{k: json.loads(d[k]) for k in ("approval_ids", "draft_ids", "next_steps_for_human")}}
    stage = ("not_started" if not d else "needs_approval" if pending
             else "complete" if resolved else d["decision"])
    return {"status": "resolved" if resolved else "open", "stage": stage,
            "latest_decision": d, "approval_requests": reqs, "pending_approvals": len(pending)}


@mcp.tool
def list_tickets() -> dict[str, Any]:
    """Every ticket with a derived `status` (open / resolved) and `stage`
    (not_started / needs_approval / complete / blocked / needs_more_info).
    Resolved = the agent run finished and the Boss decided; pending payments still need the human.

    Reads `tickets`, `ticket_decisions`, `approval_requests`. The tickets table itself is not changed.
    """
    rows = _query("SELECT * FROM tickets ORDER BY id")
    return {"source_tables": ["tickets", "ticket_decisions", "approval_requests"], "as_of": _today().isoformat(),
            "tickets": [{**t, "db_status": t["status"], **_ticket_status(t)} for t in rows]}


def _add_month(d: date) -> date:
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError(d)


@mcp.tool
def decide_request(request_id: int, action: Literal["approve", "reject"], decided_by: str,
                   requested_by: str = "") -> dict[str, Any]:
    """HUMAN ONLY: approve or reject a board request. Approving a payment or purchase is what moves cash.

    Approve, all in one transaction:
      invoice_payment -> insert `payments` (kind 'invoice'), debit `cash_accounts`, set invoices.status = 'paid'
      rent_payment    -> insert `payments` (kind 'rent'), debit `cash_accounts`, advance leases.next_due one month
      purchase_order  -> refused while the vendor has an unpaid invoice; else insert `payments`
                         (kind 'purchase_order', ref_id = request id) and debit `cash_accounts`
      price_quote     -> signed off; no cash moves (revenue isn't modeled)
    Refuses: non-pending requests, insufficient cash (no overdraft), already-paid invoices.
    Reject: marks the request rejected; nothing else changes.

    Args:
        request_id: approval_requests.id.
        action: approve or reject.
        decided_by: The person approving (recorded in payments.approved_by).
        requested_by: Must be 'human' (set by the dashboard backend; agents are never 'human').
    """
    _require_role(requested_by, {"human"}, "decide approval requests")
    who = decided_by.strip()
    agent_names = {"boss", "inventory", "accounting", "facilities", "customer_service", "human", ""}
    if who.lower() in agent_names:
        raise ToolError("decided_by must be the approving person's name.")
    _ensure_board()
    today = _today().isoformat()

    with _connect(write=True) as conn:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")      # one atomic transaction: all of it happens or none of it
        try:
            req = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
            if not req:
                raise ToolError(f"Approval request {request_id} does not exist.")
            req = dict(req)
            if req["status"] != "pending_human":
                raise ToolError(f"Request {request_id} is already {req['status']}.")
            acct = conn.execute("SELECT name, balance FROM cash_accounts ORDER BY name = 'checking' DESC, name LIMIT 1").fetchone()
            cash_before = round(acct["balance"], 2)
            payment = None

            if action == "approve" and req["cash_out"]:
                if req["amount"] > acct["balance"] + 1e-9:
                    raise ToolError(f"Insufficient cash: {acct['name']} has ${acct['balance']:.2f}, "
                                    f"request {request_id} needs ${req['amount']:.2f}. No overdrafts.")
                if req["kind"] == "invoice_payment":
                    inv = conn.execute("SELECT status FROM invoices WHERE id = ?", (req["ref_id"],)).fetchone()
                    if not inv or inv["status"].lower() == "paid":
                        raise ToolError(f"Invoice {req['ref_id']} is missing or already paid.")
                    conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (req["ref_id"],))
                    still_owed = conn.execute("SELECT COUNT(*) FROM invoices WHERE vendor_id = ? AND LOWER(status) <> 'paid'",
                                              (req["vendor_id"],)).fetchone()[0]
                    if not still_owed:  # vendor unblocked: clear the warning on its pending purchase orders
                        conn.execute("UPDATE approval_requests SET blocked_by = NULL WHERE kind = 'purchase_order' "
                                     "AND status = 'pending_human' AND vendor_id = ?", (req["vendor_id"],))
                    pay_kind, pay_ref = "invoice", req["ref_id"]
                elif req["kind"] == "rent_payment":
                    lease = conn.execute("SELECT next_due FROM leases WHERE id = ?", (req["ref_id"],)).fetchone()
                    nxt = _add_month(date.fromisoformat(lease["next_due"])).isoformat()
                    conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (nxt, req["ref_id"]))
                    pay_kind, pay_ref = "rent", req["ref_id"]
                else:  # purchase_order
                    blocking = conn.execute("SELECT id, amount FROM invoices WHERE vendor_id = ? AND LOWER(status) <> 'paid'",
                                            (req["vendor_id"],)).fetchall()
                    if blocking:
                        ids = ", ".join(f"invoice {b['id']} (${b['amount']:.2f})" for b in blocking)
                        raise ToolError(f"Vendor {req['vendor_id']} won't ship while {ids} is unpaid. "
                                        f"Approve that payment first.")
                    pay_kind, pay_ref = "purchase_order", request_id
                cur = conn.execute("INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
                                   "VALUES (?, ?, ?, ?, ?, ?)", (pay_kind, pay_ref, req["amount"], acct["name"], today, who))
                conn.execute("UPDATE cash_accounts SET balance = ROUND(balance - ?, 2), date = ? WHERE name = ?",
                             (req["amount"], today, acct["name"]))
                payment = dict(conn.execute("SELECT * FROM payments WHERE id = ?", (cur.lastrowid,)).fetchone())

            conn.execute("UPDATE approval_requests SET status = ?, decided_by = ?, decided_at = ? WHERE id = ?",
                         ("approved" if action == "approve" else "rejected", who, _now(), request_id))
            cash_after = round(conn.execute("SELECT balance FROM cash_accounts WHERE name = ?",
                                            (acct["name"],)).fetchone()["balance"], 2)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    return {"request": _query("SELECT * FROM approval_requests WHERE id = ?", (request_id,))[0], "action": action,
            "payment": payment, "account": acct["name"], "cash_before": cash_before, "cash_after": cash_after,
            "message": (f"Paid ${req['amount']:.2f} from {acct['name']}." if payment
                        else "Signed off; no cash moved." if action == "approve" else "Rejected; no cash moved.")}


if __name__ == "__main__":
    mcp.run(show_banner=False)
