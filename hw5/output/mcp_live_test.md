# MCP live test: `campus-customs`

**Connection:** The `campus-customs` server from `.mcp.json` (stdio, `.venv/bin/python mcp_server/server.py`, `CC_DB_PATH=data/campus_customs_new.db`) loaded in a Claude Code session. It exposed exactly 3 tools: `check_inventory`, `find_unpaid_invoices`, `check_lease_obligations`. All 8 calls below went through MCP, not a Python import.

Shop "today" (`desk.date_today`) = 2026-08-31.

| # | Tool | Arguments | Key MCP output | DB value (read-only sqlite3) | Match |
|---|------|-----------|----------------|------------------------------|-------|
| 1 | check_inventory | sku=CC-TEE-WHITE, size=S, requested_qty=1 | found true, on_hand 0, shortfall 1, can_fill false | inventory CC-TEE-WHITE/S qty 0 | yes |
| 2 | check_inventory | sku=CC-HOOD-NAVY, size=M, requested_qty=20 | found true, on_hand 8, shortfall 12, can_fill false | inventory CC-HOOD-NAVY/M qty 8 | yes |
| 3 | check_inventory | sku=CC-MUG-CREST, size=M | found false, "no size M ... sizes on record: OS." | only row CC-MUG-CREST/OS | yes |
| 4 | find_unpaid_invoices | invoice_id=501 | $840, Bulldog Print Co, due 2026-08-28, status open, 3 days overdue | invoices.id 501: vendor 1 Bulldog Print Co, 840.0, 2026-08-28, open; 08-31 − 08-28 = 3 | yes |
| 5 | find_unpaid_invoices | vendor_id=2 | count 0, total 0, "No unpaid invoices match." | 0 non-paid invoices for vendor 2 | yes |
| 6 | find_unpaid_invoices | (none) | count 1, total_unpaid 840, blocked: vendor 1 Bulldog Print Co | SUM(amount) WHERE status<>'paid' = 840.0; only invoice is vendor 1 | yes |
| 7 | check_lease_obligations | lease_id=1 | Elm City Properties, $2,400, next_due 2026-09-02, days_until_due 2, upcoming | leases.id 1: Elm City Properties, 2400.0, 2026-09-02; 09-02 − 08-31 = 2 | yes |
| 8 | check_lease_obligations | lease_id=9 | count 0, "Lease 9 does not exist." | COUNT(*) WHERE id=9 = 0 | yes |

**Result:** 8/8 pass.

## DB checksums (`shasum data/*.db`)

| File | Before | After |
|------|--------|-------|
| data/campus_customs_new.db | f447ca6a2766a90f3c1f81215c8f774ab109ea4c | f447ca6a2766a90f3c1f81215c8f774ab109ea4c |
| data/campus_customs_original.db | f447ca6a2766a90f3c1f81215c8f774ab109ea4c | f447ca6a2766a90f3c1f81215c8f774ab109ea4c |

Both files are unchanged. The DB queries used `sqlite3 -readonly` with `?mode=ro`.
