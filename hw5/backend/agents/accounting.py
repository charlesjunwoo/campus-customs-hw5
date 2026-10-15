"""Accounting agent: cash, invoices, margins; prepares payments, purchase orders, and price quotes for HUMAN approval.

MCP tools: get_ticket, find_unpaid_invoices, check_lease_obligations, get_cash_position, get_pricing, list_board,
           submit_payment_request, submit_purchase_order, submit_price_quote
Writes:    approval_requests only (status pending_human). Never pays, never edits payments/invoices/cash.
Prompt:    prompts/accounting.md
"""

from agents.base import specialist

AGENT = specialist("accounting")
