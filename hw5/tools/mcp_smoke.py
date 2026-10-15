"""MCP smoke test: natural-language prompts -> gpt-6-luna -> MCP tools -> checked against SQLite.

  1. Connects to the MCP server exactly as .mcp.json describes (stdio, launched as a subprocess).
  2. For each prompt, gpt-6-luna (OpenAI via Portkey, Responses API) picks a tool and its arguments.
     (Chat Completions rejects function tools on gpt-6-luna unless reasoning is turned off.)
  3. The tool call goes through the live MCP connection; its output is recorded.
  4. An independent SQL query against data/campus_customs_new.db checks every value the tool returned.
  5. Writes output/mcp_smoke.json.

Run from the project root: .venv/bin/python tools/mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import find_dotenv, load_dotenv
from fastmcp import Client
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "campus_customs_new.db"
OUT = ROOT / "output" / "mcp_smoke.json"
MODEL = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

SYSTEM = (
    "You are a Campus Customs back-office agent. Answer only from MCP tool results; "
    "never guess values. Call exactly the tool needed, then answer in one or two sentences."
)


# --- independent database checks (plain SQL, not the MCP code) -------------------

def sql(q: str, p: tuple = ()) -> list[dict[str, Any]]:
    with sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(q, p)]


def today() -> date:
    return date.fromisoformat(sql("SELECT date_today FROM desk")[0]["date_today"])


def inv_check(sku: str, size: str, requested: int | None = None) -> Callable[[dict], tuple[str, dict, dict]]:
    def check(out: dict) -> tuple[str, dict, dict]:
        q = "SELECT sku, size, qty, location FROM inventory WHERE sku = ? AND size = ?"
        rows = sql(q, (sku, size))
        if not rows:
            sizes = [r["size"] for r in sql("SELECT size FROM inventory WHERE sku = ?", (sku,))]
            return q, {"row_exists": False, "sizes_on_record": sizes}, {
                "found": out["found"], "sizes_in_message": [s for s in sizes if s in out.get("message", "")]}
        db = {"qty": rows[0]["qty"], "location": rows[0]["location"]}
        tool = {"qty": out["rows"][0]["qty"], "location": out["rows"][0]["location"]} if out["rows"] else {}
        if requested is not None:
            db["shortfall"] = max(0, requested - rows[0]["qty"])
            tool["shortfall"] = out.get("shortfall")
        return q, db, tool
    return check


def invoice_check(where: str, params: tuple) -> Callable[[dict], tuple[str, dict, dict]]:
    def check(out: dict) -> tuple[str, dict, dict]:
        q = ("SELECT i.id, v.name, i.amount, i.due_date, i.status FROM invoices i "
             f"JOIN vendors v ON v.id = i.vendor_id WHERE LOWER(i.status) <> 'paid' {where} ORDER BY i.id")
        rows = sql(q, params)
        db = {"invoices": [{"id": r["id"], "vendor": r["name"], "amount": r["amount"], "due_date": r["due_date"],
                            "days_overdue": max(0, (today() - date.fromisoformat(r["due_date"])).days)} for r in rows]}
        tool = {"invoices": [{"id": r["invoice_id"], "vendor": r["vendor_name"], "amount": r["amount"],
                              "due_date": r["due_date"], "days_overdue": r["days_overdue"]} for r in out["invoices"]]}
        return q, db, tool
    return check


def lease_check(where: str, params: tuple) -> Callable[[dict], tuple[str, dict, dict]]:
    def check(out: dict) -> tuple[str, dict, dict]:
        q = f"SELECT id, landlord, monthly_rent, next_due FROM leases {where} ORDER BY id"
        rows = sql(q, params)
        db = {"leases": [{"id": r["id"], "landlord": r["landlord"], "monthly_rent": r["monthly_rent"],
                          "next_due": r["next_due"],
                          "days_until_due": (date.fromisoformat(r["next_due"]) - today()).days} for r in rows]}
        tool = {"leases": [{"id": r["lease_id"], "landlord": r["landlord"], "monthly_rent": r["monthly_rent"],
                            "next_due": r["next_due"], "days_until_due": r["days_until_due"]} for r in out["leases"]]}
        return q, db, tool
    return check


# --- the prompts --------------------------------------------------------------------

CASES: list[dict[str, Any]] = [
    {"ticket": "101", "tool": "check_inventory", "check": inv_check("CC-TEE-WHITE", "S", 1),
     "prompt": "Ticket 101: Tauhid Zaman wants 1 Classic Bulldog Tee, SKU CC-TEE-WHITE, size S. Can we fill it from stock?"},
    {"ticket": "103", "tool": "check_inventory", "check": inv_check("CC-HOOD-NAVY", "M", 20),
     "prompt": "Ticket 103: the Yale AI Club wants 20 of CC-HOOD-NAVY in size M. How many do we have and how many are we short?"},
    {"ticket": "-", "tool": "check_inventory", "check": inv_check("CC-MUG-CREST", "M"),
     "prompt": "How many Crest Mugs (CC-MUG-CREST) do we have in size M?"},
    {"ticket": "101", "tool": "find_unpaid_invoices", "check": invoice_check("AND i.id = ?", (501,)),
     "prompt": "Ticket 101 is linked to invoice 501. Is that invoice still unpaid, who is it owed to, and how many days overdue is it?"},
    {"ticket": "101/103", "tool": "find_unpaid_invoices", "check": invoice_check("", ()),
     "prompt": "Which vendors can't ship to us right now because we owe them on an unpaid invoice, and how much do we owe in total?"},
    {"ticket": "-", "tool": "find_unpaid_invoices", "check": invoice_check("AND i.vendor_id = ?", (2,)),
     "prompt": "Do we have any unpaid invoices with vendor 2 (Elm City Gifts)?"},
    {"ticket": "102", "tool": "check_lease_obligations", "check": lease_check("WHERE id = ?", (1,)),
     "prompt": "Ticket 102: Elm City Properties emailed that rent is due in 2 days. Check lease 1 - how much is rent and exactly when is it due?"},
    {"ticket": "102", "tool": "check_lease_obligations", "check": lease_check("", ()),
     "prompt": "List every rent obligation the shop has and whether any of it is overdue."},
]


def openai_tools(mcp_tools) -> list[dict]:
    return [{"type": "function", "name": t.name, "description": t.description or "",
             "parameters": t.input_schema, "strict": False} for t in mcp_tools]


async def run_case(llm: OpenAI, mcp: Client, tools: list[dict], case: dict) -> dict:
    items: list[Any] = [{"role": "user", "content": case["prompt"]}]
    calls: list[dict] = []
    answer = ""
    for _ in range(3):  # bounded tool loop
        resp = await asyncio.to_thread(llm.responses.create, model=MODEL, instructions=SYSTEM, input=items, tools=tools)
        fcalls = [o for o in resp.output if o.type == "function_call"]
        if not fcalls:
            answer = resp.output_text
            break
        items += resp.output
        for fc in fcalls:
            args = json.loads(fc.arguments or "{}")
            result = await mcp.call_tool(fc.name, args)
            calls.append({"tool": fc.name, "arguments": args, "output": result.structured_content})
            items.append({"type": "function_call_output", "call_id": fc.call_id,
                          "output": json.dumps(result.structured_content)})

    first = next((c for c in calls if c["tool"] == case["tool"]), None)
    db_check: dict[str, Any] = {"match": False}
    if first:
        query, db_vals, tool_vals = case["check"](first["output"])
        if db_vals.get("row_exists") is False:  # negative case: tool must report a miss and list the real sizes
            match = tool_vals["found"] is False and tool_vals["sizes_in_message"] == db_vals["sizes_on_record"]
        else:
            match = db_vals == tool_vals
        db_check = {"sql": " ".join(query.split()), "db_values": db_vals, "tool_values": tool_vals, "match": match}

    return {
        "ticket": case["ticket"],
        "prompt": case["prompt"],
        "expected_tool": case["tool"],
        "tool_name": first["tool"] if first else (calls[0]["tool"] if calls else None),
        "tool_arguments": first["arguments"] if first else None,
        "tool_output": first["output"] if first else None,
        "all_tool_calls": [c["tool"] for c in calls],
        "agent_answer": answer,
        "db_check": db_check,
        "pass": bool(first) and db_check["match"],
    }


async def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    key = os.environ["PORTKEY_API_KEY"]
    llm = OpenAI(base_url=PORTKEY_BASE_URL, api_key=key, default_headers={"x-portkey-api-key": key})

    mcp_config = json.loads((ROOT / ".mcp.json").read_text())
    for srv in mcp_config["mcpServers"].values():
        srv["cwd"] = str(ROOT)  # same as Claude Code launching it from the project root
    sha_before = hashlib.sha256(DB.read_bytes()).hexdigest()

    async with Client(mcp_config) as mcp:
        mcp_tools = await mcp.list_tools()
        tools = openai_tools(mcp_tools)
        results = [await run_case(llm, mcp, tools, c) for c in CASES]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": MODEL,
        "gateway": "Portkey (OpenAI Responses API)",
        "mcp_connection": ".mcp.json -> campus-customs (stdio: .venv/bin/python mcp_server/server.py)",
        "tools_listed_by_server": [t.name for t in mcp_tools],
        "database": "data/campus_customs_new.db",
        "shop_date_today": today().isoformat(),
        "database_unchanged": sha_before == hashlib.sha256(DB.read_bytes()).hexdigest(),
        "summary": {"cases": len(results), "passed": sum(r["pass"] for r in results)},
        "results": results,
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"]), "database_unchanged:", report["database_unchanged"])
    for r in results:
        print(f'{"PASS" if r["pass"] else "FAIL"}  {r["expected_tool"]:<24} -> {r["tool_name"]} {r["tool_arguments"]}')


if __name__ == "__main__":
    asyncio.run(main())
