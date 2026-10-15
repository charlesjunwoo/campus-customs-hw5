"""Facilities agent: the physical shop: leases, rent, landlord and City correspondence, contracts.

MCP tools: get_ticket, check_lease_obligations, list_board, save_draft (landlord / city only)
Writes:    landlord and City drafts only. Rent payments go through Accounting for human approval.
Prompt:    prompts/facilities.md
"""

from agents.base import specialist

AGENT = specialist("facilities")
