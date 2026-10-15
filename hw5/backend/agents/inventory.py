"""Inventory agent: stock by SKU/size, shortfalls, and which vendor can restock (and whether it can ship).

MCP tools: get_ticket, check_inventory, find_restock_vendor, find_unpaid_invoices, list_board, save_draft (vendor only)
Writes:    vendor message drafts only. Never creates purchase orders (Accounting does) or touches stock counts.
Prompt:    prompts/inventory.md
"""

from agents.base import specialist

AGENT = specialist("inventory")
