"""Customer Service agent: drafts messages to customers (never sends them).

MCP tools: get_ticket, check_inventory, list_board, save_draft (customer only; recipient must be the ticket requester)
Writes:    customer drafts only. Promises nothing (price, date, stock) that a teammate's report doesn't support.
Prompt:    prompts/customer_service.md
"""

from agents.base import specialist

AGENT = specialist("customer_service")
