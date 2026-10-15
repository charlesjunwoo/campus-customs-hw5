"""Problem 9 report: build every artifact for the full run from the audit trail and the working database.

    .venv/bin/python tools/problem9_report.py

Reads (read-only):
  output/audit_trail.json        the runs, tool calls, delegations, and human decisions since the last reset
  data/campus_customs_new.db     board, payments, and cash_accounts (opened with mode=ro)
  data/campus_customs_original.db  the starting cash, to prove the run began from original values
Writes:
  output/desk_tickets.html       fills each ticket's Actual section and the Cash tab (Expected sections untouched)
  output/resolved_tickets.json   one entry per ticket
  output/resolved_board.html     double-clickable board with dashboard screenshots (output/screenshots/)

Every dollar figure comes from the database. The script refuses to write anything if the cash ledger does not
reconcile exactly (start - sum(payments) == cash_accounts.balance, and each approval's before/after chains).
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
sys.path.insert(0, str(ROOT / "backend"))
import audit  # noqa: E402  (agent_turns groups audit events per agent run)

DB_NEW = ROOT / "data" / "campus_customs_new.db"
DB_ORIG = ROOT / "data" / "campus_customs_original.db"
TICKETS = [101, 102, 103]
LABEL = {"boss": "Boss", "inventory": "Inventory", "accounting": "Accounting", "facilities": "Facilities",
         "customer_service": "Customer Service", "backend": "Dashboard"}
CSS_CLASS = {"boss": "boss", "inventory": "inventory", "accounting": "accounting", "facilities": "facilities",
             "customer_service": "cs"}
PAST = {"approve": "approved", "reject": "rejected"}
KIND = {"invoice_payment": ("💸", "Vendor invoice payment"), "rent_payment": ("🏠", "Rent payment"),
        "purchase_order": ("📦", "Purchase order"), "price_quote": ("🏷️", "Price quote")}

# The Expected sections of output/desk_tickets.html (Problem 6), as data for the comparison.
EXPECTED_ROUTE = {101: ["inventory", "accounting", "customer_service"], 102: ["facilities", "accounting"],
                  103: ["inventory", "accounting", "customer_service"]}
EXPECTED_TOOLS = {
    101: {"boss": ["get_ticket", "list_board"], "inventory": ["check_inventory", "find_restock_vendor"],
          "accounting": ["list_board", "find_unpaid_invoices", "submit_payment_request", "submit_purchase_order", "get_cash_position"],
          "customer_service": ["list_board", "save_draft"]},
    102: {"boss": ["get_ticket", "list_board"], "facilities": ["check_lease_obligations", "save_draft"],
          "accounting": ["check_lease_obligations", "list_board", "submit_payment_request", "get_cash_position"]},
    103: {"boss": ["get_ticket", "list_board"], "inventory": ["check_inventory", "find_restock_vendor"],
          "accounting": ["list_board", "get_pricing", "submit_price_quote", "submit_purchase_order", "get_cash_position"],
          "customer_service": ["list_board", "save_draft"]},
}
NOT_EXPECTED = {101: ["facilities"], 102: ["inventory", "customer_service"], 103: ["facilities"]}

e = html.escape
D = lambda x: Decimal(str(x)).quantize(Decimal("0.01"))  # exact cents  # noqa: E731
money = lambda x: f"${D(x):,.2f}"  # noqa: E731


# ------------------------------------------------------------------------------------------------ data

def ro(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def q(db: Path, sql: str, p: tuple = ()) -> list[dict]:
    with ro(db) as c:
        return [dict(r) for r in c.execute(sql, p)]


def load_runs() -> tuple[list[dict], dict[int, dict]]:
    trail = audit.read()
    last_reset = max(i for i, ev in enumerate(trail) if ev["event"] == "db_reset")
    since = trail[last_reset:]
    runs: dict[int, dict] = {}
    for ev in since:
        if ev["event"] == "run_start" and isinstance(ev.get("tickets"), list) and len(ev["tickets"]) == 1:
            runs[ev["tickets"][0]] = {"run_id": ev["run_id"], "started": ev["ts"]}
    for tid, r in runs.items():
        evs = [x for x in since if x.get("run_id") == r["run_id"]]
        end = next((x for x in evs if x["event"] == "run_end"), None)
        assert end and all(x["ok"] for x in end["results"]), f"run for {tid} did not finish cleanly"
        r["ended"] = end["ts"]
        r["turns"] = audit.agent_turns(evs)
        r["boss"] = next(t for t in r["turns"] if t["agent"] == "boss")
    missing = [t for t in TICKETS if t not in runs]
    assert not missing, f"no run since the last reset for tickets {missing}"
    return since, runs


def parse_result(c: dict) -> dict | None:
    r = c.get("result")
    if isinstance(r, str):
        try:
            r = json.loads(r)
        except json.JSONDecodeError:
            return None
    return r if isinstance(r, dict) else None


def write_outcome(c: dict) -> str:
    r = parse_result(c)
    if not c["ok"]:
        return f"refused: {c['error']}"
    if not r:
        return ""
    if "request" in r:
        rq = r["request"]
        return (f"{'created' if r.get('created') else 'reused existing'} request #{rq['id']} · {money(rq['amount'])}"
                + (" · blocked_by " + rq["blocked_by"] if rq.get("blocked_by") else ""))
    if "draft" in r:
        return f"{'created' if r.get('created') else 'updated'} draft #{r['draft']['id']} to {r['draft']['recipient']}"
    return ""


def cash_ledger(since: list[dict]) -> dict:
    """Start, every human decision in order, and the reconciliation against the database. Raises on any mismatch."""
    start = D(q(DB_ORIG, "SELECT balance FROM cash_accounts WHERE name = 'checking'")[0]["balance"])
    reset_cash = start  # the reset copies the original, so the post-reset balance is the original balance
    decisions = [ev for ev in since if ev["event"] == "human_decision"]
    payments = q(DB_NEW, "SELECT * FROM payments ORDER BY id")
    reqs = {r["id"]: r for r in q(DB_NEW, "SELECT * FROM approval_requests ORDER BY id")}
    end_db = D(q(DB_NEW, "SELECT balance FROM cash_accounts WHERE name = 'checking'")[0]["balance"])

    running = reset_cash
    ledger = []
    for ev in decisions:
        if not ev.get("ok"):
            ledger.append({**ev, "effect": D(0), "balance_after": running})
            continue
        before, after = D(ev["cash_before"]), D(ev["cash_after"])
        assert before == running, f"ledger break before request {ev['request_id']}: expected {running}, event says {before}"
        effect = after - before
        if ev["action"] == "approve" and reqs[ev["request_id"]]["cash_out"]:
            assert effect == -D(reqs[ev["request_id"]]["amount"]), f"request {ev['request_id']} moved {effect}, amount is {reqs[ev['request_id']]['amount']}"
        else:
            assert effect == 0, f"request {ev['request_id']} ({ev['action']}) should not move cash but moved {effect}"
        running = after
        ledger.append({**ev, "effect": effect, "balance_after": running})

    paid = sum((D(p["amount"]) for p in payments), D(0))
    assert running == end_db, f"ledger ends at {running}, cash_accounts says {end_db}"
    assert reset_cash - paid == end_db, f"start {reset_cash} - payments {paid} != cash_accounts {end_db}"
    assert len(payments) == sum(1 for x in ledger if x.get("ok") and x["effect"] != 0)
    return {"start": reset_cash, "end_db": end_db, "paid_total": paid, "ledger": ledger, "payments": payments,
            "requests": reqs}


# ------------------------------------------------------------------------------------------------ desk_tickets.html: Actual

def node(agent: str, small: str) -> str:
    cls = {"boss": "boss", "inventory": "inventory", "accounting": "accounting", "facilities": "facilities",
           "customer_service": "cs"}[agent]
    return f'<div class="node {cls}">{LABEL[agent]}<small>{e(small)}</small></div>'


def actual_html(tid: int, run: dict, cash: dict, ticket_status: dict) -> str:
    turns, boss = run["turns"], run["boss"]
    route = [d["to"] for d in boss["delegations"] if not d["refused"]]
    peer = [(t["asked_by"], t["agent"]) for t in turns if t["depth"] >= 2]
    called = {t["agent"] for t in turns}
    route_ok = route == EXPECTED_ROUTE[tid]
    flags_bad = [a for a in NOT_EXPECTED[tid] if a in called]
    u = boss["usage"]

    # workflow strip
    strip = [node("boss", "reads, routes, decides")]
    for i, a in enumerate(route):
        t = next(x for x in turns if x["agent"] == a and x["asked_by"] == "boss")
        strip.append(f'<div class="arrow"><span>{"①②③④⑤"[i]}</span></div>')
        strip.append(node(a, f"{len(t['tools'])} tool calls"))
    skipped = "".join(f'<span class="chip off">{LABEL[a]}</span>' for a in NOT_EXPECTED[tid] if a not in called)
    peer_html = "".join(f'<span class="chip lilac">{LABEL[a]} → {LABEL[b]} (peer hand-off, depth 2)</span>' for a, b in peer)

    # delegations
    drows = []
    hand_offs = sorted(((d, t) for t in turns for d in t["delegations"]), key=lambda x: x[0]["ts"])  # in the order they happened
    for n, (d, t) in enumerate(hand_offs):
        child = next((c for c in turns if c["agent"] == d["to"] and c["asked_by"] == t["agent"]), None)
        said = (child or {}).get("said") or {}
        depth = " <small>(peer, depth 2)</small>" if t["agent"] != "boss" else ""
        drows.append(f'<tr><td class="num-col">{"①②③④⑤⑥⑦⑧"[n]}</td><td class="agent {CSS_CLASS[d["to"]]}">{LABEL[t["agent"]]} → {LABEL[d["to"]]}{depth}</td>'
                     f'<td>{e(d["task"])}</td><td>{e(said.get("summary", "refused: " + (d.get("reason") or "")))}</td></tr>')

    # tools
    trows = []
    for t in turns:
        exp = EXPECTED_TOOLS[tid].get(t["agent"], [])
        used = [c["tool"] for c in t["tools"]]
        cells = []
        for c in t["tools"]:
            a = {k: v for k, v in (c["args"] or {}).items() if k not in ("reason", "body", "subject", "requested_by", "summary", "next_steps_for_human")}
            args = ", ".join(f"{k}={json.dumps(v)}" for k, v in a.items())
            tag = '<span class="req write">write</span>' if c["tool"].startswith(("submit_", "save_")) else (
                '<span class="req">expected</span>' if c["tool"] in exp else '<span class="req opt">extra</span>')
            out = write_outcome(c)
            cells.append(f'<li><code>{e(c["tool"])}({e(args)})</code> {tag} <span class="ok">{"✓" if c["ok"] else "✕"}</span>'
                         + (f' <span class="outcome">{e(out)}</span>' if out else "") + "</li>")
        missing = [x for x in exp if x not in used]
        who = LABEL[t["agent"]] + (f" <small>(asked by {LABEL[t['asked_by']]})</small>" if t["asked_by"] not in ("boss", "backend") else "")
        trows.append(f'<tr><td class="agent {CSS_CLASS[t["agent"]]}">{who}</td><td><ul class="calls">{"".join(cells)}</ul>'
                     + (f'<div class="miss">Expected but not called: {", ".join(missing)}</div>' if missing else "")
                     + f'</td><td class="num-col">{t["usage"]["tool_calls"] if t["usage"] else "–"}</td></tr>')
    trows.append('<tr><td class="agent boss">Backend</td><td><ul class="calls"><li><code>record_ticket_decision'
                 f'(ticket_id={tid}, decision="{boss["said"]["decision"]}")</code> <span class="req write">write</span> <span class="ok">✓</span></li></ul></td><td class="num-col">1</td></tr>')

    # board + decision + approvals
    reqs = [r for r in cash["requests"].values() if r["ticket_id"] == tid]
    drafts = q(DB_NEW, "SELECT * FROM drafts WHERE ticket_id = ? ORDER BY id", (tid,))
    req_li = "".join(
        f'<li>{KIND[r["kind"]][0]} {KIND[r["kind"]][1]} #{r["id"]}: <b>{money(r["amount"])}</b>{" (no cash moves)" if not r["cash_out"] else ""}'
        f' — <span class="st st-{r["status"]}">{r["status"].replace("_", " ")}</span>'
        + (f' by {e(r["decided_by"])}' if r["decided_by"] else "") + f'<br><small>{e(r["detail"] or "")}</small></li>' for r in reqs)
    draft_li = "".join(f'<li>✉️ Draft #{d["id"]} to <b>{e(d["recipient"])}</b> ({d["audience"]}), sent = {d["sent"]}<blockquote>{e(d["body"])}</blockquote></li>' for d in drafts)
    decisions = [x for x in cash["ledger"] if x.get("ticket_id") == tid or cash["requests"].get(x.get("request_id"), {}).get("ticket_id") == tid]
    appr_li = "".join(
        f'<li>{x["ts"][11:19]} UTC: <b>{PAST[x["action"]] if x.get("ok") else x["action"] + " refused"}</b>: request #{x["request_id"]} by {e(x["decided_by"])} — '
        + (f'checking {money(x["cash_before"])} → {money(x["cash_after"])}' if x.get("ok") else f'refused: {e(x.get("error", ""))}') + "</li>"
        for x in decisions) or "<li>No human decisions recorded for this ticket's requests.</li>"
    steps = "".join(f"<li>{e(s)}</li>" for s in boss["said"]["next_steps_for_human"])

    # comparison
    checks = [("Route", route_ok, " → ".join(LABEL[a] for a in route) + (" (matches)" if route_ok else f" (expected {' → '.join(LABEL[a] for a in EXPECTED_ROUTE[tid])})")),
              ("Agents not expected", not flags_bad, ", ".join(LABEL[a] for a in flags_bad) or "none called (" + ", ".join(LABEL[a] for a in NOT_EXPECTED[tid]) + " skipped)"),
              ("Required tools", all(x in [c["tool"] for t in turns if t["agent"] == ag for c in t["tools"]] for ag, xs in EXPECTED_TOOLS[tid].items() for x in xs),
               "every required tool in the Expected table was called by the expected agent"),
              ("Boss decision", boss["said"]["decision"] == "awaiting_human_approval", boss["said"]["decision"]),
              ("Ticket status", ticket_status["status"] == "resolved", f'{ticket_status["status"]} · stage {ticket_status["stage"]}')]
    if peer:
        checks.append(("Peer hand-offs", False, "; ".join(f"{LABEL[a]} → {LABEL[b]}" for a, b in peer) + " (not in the plan; inside the depth-2 guard)"))
    if tid == 103:
        reused = any("reused" in write_outcome(c) for t in turns for c in t["tools"] if c["tool"] == "submit_payment_request")
        dup = sum(1 for r in cash["requests"].values() if r["kind"] == "invoice_payment" and r["ref_id"] == 501) > 1
        checks.append(("Invoice 501 not duplicated", not dup, "Accounting re-submitted invoice 501; the server returned existing request #1 (reused)" if reused else "no second request"))
    check_rows = "".join(f'<tr><td>{e(k)}</td><td class="{ "pass" if ok else "dev"}">{"✓" if ok else "⚠"}</td><td>{e(v)}</td></tr>' for k, ok, v in checks)

    return f"""<!-- ACTUAL:{tid}:START -->
    <div class="actual">
      <div class="runbar">
        <span class="chip mint">run {run["run_id"]}</span>
        <span class="chip">{run["started"][:10]} {run["started"][11:19]}–{run["ended"][11:19]} UTC</span>
        <span class="chip">{u["requests"]} model requests · {u["total_tokens"]:,} tokens (whole team)</span>
        <span class="chip yellow">Boss: {boss["said"]["decision"]}</span>
        <span class="chip {"mint" if ticket_status["status"] == "resolved" else "pink"}">ticket {ticket_status["status"]} · {ticket_status["stage"]}</span>
      </div>

      <h4>1 · Workflow that ran</h4>
      <div class="box">
        <div class="flow">{"".join(strip)}</div>
        <div class="skipped">Not called: {skipped or "<span>—</span>"} {peer_html}</div>
      </div>

      <h4>2 · Delegations</h4>
      <table class="spec"><thead><tr><th>#</th><th>From → To</th><th>Task as sent</th><th>What came back (summary)</th></tr></thead>
        <tbody>{"".join(drows)}</tbody></table>

      <h4>3 · MCP tools used</h4>
      <table class="spec"><thead><tr><th>Agent</th><th>Calls in order (✓ ok)</th><th>#</th></tr></thead>
        <tbody>{"".join(trows)}</tbody></table>

      <h4>4 · Board, decision & human approvals</h4>
      <div class="twocol">
        <div class="box">
          <b>Boss's final call</b>
          <p style="margin:6px 0">{e(boss["said"]["summary"])}</p>
          <b>Next steps it gave the human</b><ol class="tight">{steps}</ol>
        </div>
        <div class="box">
          <b>On the board</b><ul class="tight">{req_li}{draft_li}</ul>
          <b>Human approvals (dashboard)</b><ul class="tight">{appr_li}</ul>
        </div>
      </div>

      <h4>5 · Expected vs actual</h4>
      <table class="spec cmp"><tbody>{check_rows}</tbody></table>
    </div>
    <!-- ACTUAL:{tid}:END -->"""


# ------------------------------------------------------------------------------------------------ desk_tickets.html: Cash

def cash_html(cash: dict, runs: dict) -> str:
    reqs = cash["requests"]
    rows = []
    for x in cash["ledger"]:
        r = reqs.get(x["request_id"], {})
        if x.get("ok"):
            eff = x["effect"]
            rows.append(f'<tr><td>{x["ts"][11:19]}</td><td>#{r.get("ticket_id")}</td><td>{KIND[r["kind"]][0]} #{x["request_id"]} {KIND[r["kind"]][1]}<br><small>{e(r.get("detail") or "")}</small></td>'
                        f'<td>{PAST[x["action"]]} by {e(x["decided_by"])}</td><td class="amt">{money(x["cash_before"])}</td>'
                        f'<td class="amt {"neg" if eff < 0 else ""}">{"−" + money(-eff) if eff < 0 else "$0.00"}</td><td class="amt">{money(x["cash_after"])}</td></tr>')
        else:
            rows.append(f'<tr class="refused"><td>{x["ts"][11:19]}</td><td>#{r.get("ticket_id", "?")}</td><td>{KIND.get(r.get("kind"), ("", ""))[0]} #{x["request_id"]} (attempted {x["action"]})</td>'
                        f'<td>refused: {e(x.get("error", ""))}</td><td class="amt">{money(x["balance_after"])}</td><td class="amt">$0.00</td><td class="amt">{money(x["balance_after"])}</td></tr>')

    per = []
    for tid in TICKETS:
        tr = [r for r in reqs.values() if r["ticket_id"] == tid]
        moved = sum((x["effect"] for x in cash["ledger"] if x.get("ok") and reqs[x["request_id"]]["ticket_id"] == tid), D(0))
        items = "".join(
            f'<li>{KIND[r["kind"]][0]} #{r["id"]} {KIND[r["kind"]][1]}: {money(r["amount"])} — <b>{r["status"].replace("_", " ")}</b>'
            + (f" by {e(r['decided_by'])}" if r["decided_by"] else "")
            + (" → <b>cash −" + money(r["amount"]) + "</b>" if r["status"] == "approved" and r["cash_out"] else " → no cash moved")
            + f'<br><small>Why: {e(r["reason"])}</small></li>' for r in tr)
        per.append(f'<div class="box"><b>Ticket {tid}</b> <span class="chip {"pink" if moved < 0 else ""}">net {"−" + money(-moved) if moved < 0 else "$0.00"}</span>'
                   f'<ul class="tight">{items}</ul></div>')

    ok = cash["start"] - cash["paid_total"] == cash["end_db"]
    pay_rows = "".join(f'<tr><td>{p["id"]}</td><td>{p["kind"]}</td><td>{p["ref_id"]}</td><td class="amt">{money(p["amount"])}</td><td>{p["account"]}</td><td>{p["paid_at"]}</td><td>{e(p["approved_by"])}</td></tr>' for p in cash["payments"]) \
        or '<tr><td colspan="7">No payments recorded.</td></tr>'
    pending = [r for r in reqs.values() if r["status"] == "pending_human"]
    pend = "".join(f'<li>{KIND[r["kind"]][0]} #{r["id"]} (ticket {r["ticket_id"]}): {money(r["amount"])} — still pending; no cash moved</li>' for r in pending)
    return f"""<!-- CASH:START -->
    <div class="actual">
      <div class="cashhead">
        <div class="kpi"><span>Starting checking (after reset)</span><b>{money(cash["start"])}</b></div>
        <div class="kpi"><span>Paid out (human-approved)</span><b class="neg">−{money(cash["paid_total"])}</b></div>
        <div class="kpi"><span>Ending checking (computed)</span><b>{money(cash["start"] - cash["paid_total"])}</b></div>
        <div class="kpi {"ok" if ok else "bad"}"><span>cash_accounts.balance in campus_customs_new.db</span><b>{money(cash["end_db"])} {"✓" if ok else "✕"}</b></div>
      </div>
      <h4>1 · Ledger, in the order you decided</h4>
      <table class="spec ledger"><thead><tr><th>Time UTC</th><th>Ticket</th><th>Request</th><th>Decision</th><th>Before</th><th>Change</th><th>After</th></tr></thead>
        <tbody><tr class="startrow"><td colspan="6">Start: database reset to original values</td><td class="amt">{money(cash["start"])}</td></tr>{"".join(rows)}
        <tr class="endrow"><td colspan="6">End balance</td><td class="amt">{money(cash["end_db"])}</td></tr></tbody></table>
      <h4>2 · How each ticket changed cash, and why</h4>
      <div class="twocol three">{"".join(per)}</div>
      {f'<h4>Still pending</h4><ul class="tight">{pend}</ul>' if pend else ""}
      <h4>3 · Verification against the database</h4>
      <div class="box verify">
        <p><code>{money(cash["start"])}</code> start (original <code>cash_accounts.balance</code>, restored by the reset)
           − <code>{money(cash["paid_total"])}</code> (sum of {len(cash["payments"])} row(s) in <code>payments</code>)
           = <code>{money(cash["start"] - cash["paid_total"])}</code>, and
           <code>SELECT balance FROM cash_accounts WHERE name='checking'</code> returns <code>{money(cash["end_db"])}</code>.
           <b>{"Exact match ✓" if ok else "MISMATCH ✕"}</b></p>
        <p>Every approval's before/after balance chains to the next one, and each approved payment or purchase moved exactly its
           request amount. Rejections, refusals, and price-quote sign-offs moved $0.00. Revenue isn't modeled, so no money came in.</p>
        <table class="spec"><thead><tr><th>payments.id</th><th>kind</th><th>ref_id</th><th>amount</th><th>account</th><th>paid_at</th><th>approved_by</th></tr></thead><tbody>{pay_rows}</tbody></table>
        <p><small>Generated {datetime.now().strftime("%Y-%m-%d %H:%M")} by tools/problem9_report.py from output/audit_trail.json and data/campus_customs_new.db (read-only).</small></p>
      </div>
    </div>
    <!-- CASH:END -->"""


EXTRA_CSS = """
  /* ---------- Actual + Cash (Problem 9) ---------- */
  .actual .runbar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
  ul.calls { margin: 0; padding-left: 16px; } ul.calls li { margin: 2px 0; }
  .ok { color: #0b8a5c; font-weight: 900; }
  .outcome { font: 600 12px var(--mono); background: var(--mint); border: 1px solid var(--ink); padding: 0 5px; }
  .miss { margin-top: 4px; color: #b4126a; font-weight: 700; font-size: 12.5px; }
  .st { font: 700 11px var(--mono); padding: 0 5px; border: 1px solid var(--ink); }
  .st-approved { background: var(--mint); } .st-rejected { background: #eceaf4; } .st-pending_human { background: var(--yellow); }
  .actual blockquote { margin: 6px 0; padding: 6px 10px; border-left: 4px solid var(--pink); background: #fff; font-size: 13px; white-space: pre-wrap; }
  table.cmp td.pass { background: var(--mint); text-align: center; font-weight: 900; width: 40px; }
  table.cmp td.dev { background: var(--yellow); text-align: center; font-weight: 900; width: 40px; }
  table.cmp td:first-child { font-weight: 800; width: 200px; }
  .cashhead { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 16px; }
  .kpi { border: 3px solid var(--ink); background: var(--paper); box-shadow: var(--shadow-sm); padding: 12px 14px; }
  .kpi span { display: block; font: 700 11px var(--mono); text-transform: uppercase; color: #555; }
  .kpi b { font: 900 26px var(--mono); }
  .kpi.ok { background: var(--mint); } .kpi.bad { background: var(--pink); }
  .neg { color: #c0143c; }
  td.amt { font-family: var(--mono); text-align: right; white-space: nowrap; }
  table.ledger tr.startrow td, table.ledger tr.endrow td { background: #f6f4ff; font-weight: 800; }
  table.ledger tr.refused td { background: #fff4f8; color: #6b2140; }
  .twocol.three { grid-template-columns: repeat(3, 1fr); }
  .verify p { margin: 0 0 10px; }
  @media (max-width: 860px) { .cashhead, .twocol.three { grid-template-columns: 1fr 1fr; } }
"""


def fill_desk_tickets(runs: dict, cash: dict, statuses: dict) -> None:
    path = OUT / "desk_tickets.html"
    src = path.read_text()
    blank = '<div class="blank">To be filled in by the overseer after running the agents (delegations, tool calls, board items, decision).</div>'
    cash_blank = '<div class="later-hero"><h2>Cash</h2></div>\n    <div class="blank">Intentionally blank. Reserved for a later problem.</div>'

    def expected_only(s: str) -> str:  # page with every generated region removed, for the "Expected untouched" check
        s = re.sub(r"<!-- ACTUAL:\d+:START -->.*?<!-- ACTUAL:\d+:END -->", "§", s, flags=re.S)
        s = re.sub(r"<!-- CASH:START -->.*?<!-- CASH:END -->", "§C", s, flags=re.S)
        s = s.replace(blank, "§").replace(cash_blank, '<div class="later-hero"><h2>Cash</h2></div>\n    §C')
        return re.sub(r"\n  /\* ---------- Actual \+ Cash \(Problem 9\) ---------- \*/.*?(?=</style>)", "", s, flags=re.S)

    before = expected_only(src)
    out = src
    for tid in TICKETS:
        block = actual_html(tid, runs[tid], cash, statuses[tid])
        if f"<!-- ACTUAL:{tid}:START -->" in out:
            out = re.sub(rf"<!-- ACTUAL:{tid}:START -->.*?<!-- ACTUAL:{tid}:END -->", lambda _m: block.strip(), out, flags=re.S)
        else:  # first fill: the n-th blank belongs to ticket n
            i = out.index(blank, out.index(f'id="t{tid}"'))
            out = out[:i] + block.strip() + out[i + len(blank):]
    cblock = cash_html(cash, runs)
    if "<!-- CASH:START -->" in out:
        out = re.sub(r"<!-- CASH:START -->.*?<!-- CASH:END -->", lambda _m: cblock.strip(), out, flags=re.S)
    else:
        out = out.replace(cash_blank, '<div class="later-hero"><h2>Cash</h2></div>\n    ' + cblock.strip())
    if "Actual + Cash (Problem 9)" not in out:
        out = out.replace("</style>", EXTRA_CSS + "</style>", 1)
    assert expected_only(out) == before, "an Expected section (or anything outside Actual/Cash) would change; aborting"
    path.write_text(out)


# ------------------------------------------------------------------------------------------------ resolved_tickets.json

def ticket_statuses() -> dict[int, dict]:
    sys.path.insert(0, str(ROOT / "mcp_server"))
    import os
    os.environ["CC_DB_PATH"] = str(DB_NEW)
    import server  # the MCP server's own status rule (resolved once the run finishes)
    return {t["id"]: t for t in server.list_tickets()["tickets"]}


def resolved_json(runs: dict, cash: dict, statuses: dict) -> list[dict]:
    out = []
    for tid in TICKETS:
        run, t = runs[tid], statuses[tid]
        boss = run["boss"]
        agents = {}
        for turn in run["turns"]:
            if turn["agent"] == "boss":
                continue
            s = turn["said"] or {}
            agents.setdefault(turn["agent"], []).append({
                "asked_by": turn["asked_by"], "tools_used": [c["tool"] for c in turn["tools"]],
                "board_items": [write_outcome(c) for c in turn["tools"] if c["tool"].startswith(("submit_", "save_"))],
                "contribution": s.get("summary"), "recommendation": s.get("recommendation")})
        reqs = [r for r in cash["requests"].values() if r["ticket_id"] == tid]
        approvals = [{
            "request_id": x["request_id"], "kind": cash["requests"][x["request_id"]]["kind"],
            "amount": float(cash["requests"][x["request_id"]]["amount"]), "action": x["action"], "ok": x.get("ok"),
            "decided_by": x["decided_by"], "at": x["ts"],
            **({"cash_before": float(x["cash_before"]), "cash_after": float(x["cash_after"])} if x.get("ok") else {"refused": x.get("error")}),
        } for x in cash["ledger"] if cash["requests"].get(x["request_id"], {}).get("ticket_id") == tid]
        out.append({
            "ticket_id": tid, "type": t["type"], "requester": t["requester"], "subject": t["subject"],
            "final_status": t["status"], "stage": t["stage"], "boss_decision": boss["said"]["decision"],
            "outcome": boss["said"]["summary"],
            "run": {"run_id": run["run_id"], "started": run["started"], "ended": run["ended"],
                    "model_requests": boss["usage"]["requests"], "total_tokens": boss["usage"]["total_tokens"]},
            "route": [d["to"] for d in boss["delegations"] if not d["refused"]],
            "boss": {"tools_used": [c["tool"] for c in boss["tools"]], "next_steps_for_human": boss["said"]["next_steps_for_human"]},
            "agents": agents,
            "board": {"approval_requests": [{k: r[k] for k in ("id", "kind", "amount", "cash_out", "status", "decided_by", "detail")} for r in reqs],
                      "drafts": [{k: d[k] for k in ("id", "audience", "recipient", "subject", "sent")}
                                 for d in q(DB_NEW, "SELECT * FROM drafts WHERE ticket_id = ?", (tid,))]},
            "human_approvals": approvals,
            "cash_change": float(sum((x["effect"] for x in cash["ledger"] if x.get("ok") and cash["requests"][x["request_id"]]["ticket_id"] == tid), D(0))),
            "screenshot": f"screenshots/ticket_{tid}.jpg",
        })
    return out


# ------------------------------------------------------------------------------------------------ resolved_board.html

def board_html(data: list[dict], cash: dict) -> str:
    cards = []
    for t in data:
        steps = "".join(
            f'<span class="step {a}">{LABEL[a]}</span>' + ("" if i == len(t["route"]) - 1 else '<span class="to">→</span>')
            for i, a in enumerate(t["route"]))
        ag = "".join(
            f'<div class="contrib {a}"><b>{LABEL[a]}</b>' + "".join(
                f'<p>{e(x["contribution"] or "")}</p><p class="tools">{" · ".join(x["tools_used"])}'
                + (f' <i>(asked by {LABEL[x["asked_by"]]})</i>' if x["asked_by"] not in ("boss", "backend") else "") + "</p>"
                + "".join(f'<p class="item">▸ {e(i)}</p>' for i in x["board_items"]) for x in xs) + "</div>"
            for a, xs in t["agents"].items())
        appr = "".join(
            f'<li>{KIND[a["kind"]][0]} #{a["request_id"]} {money(a["amount"])} — <b>{PAST[a["action"]] if a["ok"] else a["action"] + " refused"}</b> by {e(a["decided_by"])}'
            + (f' · checking {money(a["cash_before"])} → {money(a["cash_after"])}' if a["ok"] else f' · {e(a["refused"])}') + "</li>"
            for a in t["human_approvals"]) or "<li>None</li>"
        pend = "".join(f'<li>{KIND[r["kind"]][0]} #{r["id"]} {money(r["amount"])} — {r["status"].replace("_", " ")}</li>'
                       for r in t["board"]["approval_requests"] if r["status"] == "pending_human")
        shot = OUT / t["screenshot"]
        img = (f'<a href="{t["screenshot"]}" target="_blank"><img src="{t["screenshot"]}" alt="React dashboard, ticket {t["ticket_id"]} resolved"></a>'
               if shot.exists() else '<div class="noshot">Screenshot missing</div>')
        cards.append(f"""
      <section class="ticket" id="t{t["ticket_id"]}">
        <header><span class="num">#{t["ticket_id"]}</span><h2>{e(t["subject"])}</h2>
          <span class="pill ok">✓ {t["final_status"]}</span><span class="pill">{t["stage"].replace("_", " ")}</span>
          <span class="pill cash">{"cash −" + money(-t["cash_change"]) if t["cash_change"] < 0 else "no cash moved"}</span></header>
        <p class="meta">{e(t["type"])} · from <b>{e(t["requester"])}</b> · run {t["run"]["run_id"]} · {t["run"]["model_requests"]} model requests · {t["run"]["total_tokens"]:,} tokens</p>
        <div class="route">{steps}</div>
        <p class="outcome">{e(t["outcome"])}</p>
        <div class="grid"><div>{ag}</div>
          <div class="side"><h3>Human approvals</h3><ul>{appr}</ul>{f"<h3>Still pending</h3><ul>{pend}</ul>" if pend else ""}
          <h3>Drafts (never sent)</h3><ul>{"".join(f'<li>✉️ #{d["id"]} to {e(d["recipient"])} — {e(d["subject"])}</li>' for d in t["board"]["drafts"])}</ul></div></div>
        <figure>{img}<figcaption>React dashboard (http://localhost:5173) with ticket {t["ticket_id"]} selected after it was resolved and approvals were decided.</figcaption></figure>
      </section>""")
    ok = cash["start"] - cash["paid_total"] == cash["end_db"]
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Campus Customs — Resolved Board</title>
<style>
  :root {{ --ink:#17172b; --paper:#fbf8f1; --boss:#ffd23f; --inventory:#13c4b4; --accounting:#a98bff; --facilities:#ff9f6b; --cs:#ff5fa2; --mint:#c8f5df;
          --mono:"SF Mono",Menlo,Consolas,monospace; --display:"Futura","Avenir Next","Century Gothic",sans-serif; }}
  * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.5 "Avenir Next","Segoe UI",Arial,sans-serif; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:28px 22px 60px; }}
  .mast {{ background:var(--ink); color:#fff; padding:24px 28px; box-shadow:8px 8px 0 var(--cs); position:relative; }}
  .mast::after {{ content:""; position:absolute; left:0; right:0; bottom:-8px; height:8px; background:linear-gradient(90deg,var(--boss) 0 20%,var(--inventory) 20% 40%,var(--accounting) 40% 60%,var(--facilities) 60% 80%,var(--cs) 80%); }}
  .mast h1 {{ margin:0; font:900 34px var(--display); text-transform:uppercase; }} .mast h1 span {{ color:var(--boss); }}
  .mast p {{ margin:6px 0 0; color:#d8d6ea; }}
  .cash {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:30px 0 8px; }}
  .kpi {{ border:2px solid var(--ink); background:#fff; padding:12px 14px; box-shadow:4px 4px 0 var(--ink); }}
  .kpi span {{ display:block; font:700 11px var(--mono); text-transform:uppercase; color:#555; }} .kpi b {{ font:900 24px var(--mono); }}
  .kpi.ok {{ background:var(--mint); }}
  .ticket {{ background:#fff; border:2px solid var(--ink); box-shadow:6px 6px 0 var(--ink); padding:20px 22px; margin-top:34px; }}
  .ticket header {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
  .num {{ font:900 18px var(--mono); background:var(--boss); border:2px solid var(--ink); padding:0 8px; }}
  h2 {{ margin:0; font:900 24px var(--display); text-transform:uppercase; }}
  .pill {{ font:800 11px var(--mono); text-transform:uppercase; border:2px solid var(--ink); padding:2px 8px; background:#f1eee5; }}
  .pill.ok {{ background:var(--mint); }} .pill.cash {{ background:#ffe3e4; }}
  .meta {{ color:#555; font-size:13px; margin:8px 0; }}
  .route {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}
  .step {{ font:800 12px var(--display); text-transform:uppercase; border:2px solid var(--ink); padding:4px 10px; }}
  .step.boss {{ background:var(--boss); }} .step.inventory {{ background:var(--inventory); }} .step.accounting {{ background:var(--accounting); }}
  .step.facilities {{ background:var(--facilities); }} .step.customer_service {{ background:var(--cs); }} .to {{ font-weight:900; }}
  .outcome {{ font-size:15px; border-left:5px solid var(--boss); padding:6px 12px; background:#fffbe8; }}
  .grid {{ display:grid; grid-template-columns:1.4fr 1fr; gap:18px; }}
  .contrib {{ border:1.5px solid #e4dfd2; border-top:5px solid; padding:8px 12px; margin-bottom:10px; }}
  .contrib.inventory {{ border-top-color:var(--inventory); }} .contrib.accounting {{ border-top-color:var(--accounting); }}
  .contrib.facilities {{ border-top-color:var(--facilities); }} .contrib.customer_service {{ border-top-color:var(--cs); }}
  .contrib p {{ margin:4px 0; font-size:13.5px; }} .contrib .tools {{ font:12px var(--mono); color:#555; }} .contrib .item {{ font:600 12.5px var(--mono); }}
  .side h3 {{ font:800 13px var(--display); text-transform:uppercase; margin:6px 0; }} .side ul {{ padding-left:18px; font-size:13.5px; }}
  figure {{ margin:16px 0 0; }} figure img {{ width:100%; border:2px solid var(--ink); display:block; }}
  figcaption {{ font-size:12px; color:#555; margin-top:6px; }} .noshot {{ padding:30px; border:2px dashed #aaa; text-align:center; }}
  footer {{ margin-top:40px; font:12px var(--mono); color:#555; }}
  @media (max-width:860px) {{ .cash,.grid {{ grid-template-columns:1fr; }} }}
</style></head><body><div class="wrap">
  <header class="mast"><h1>Campus Customs <span>Resolved Board</span></h1>
    <p>Full run after a database reset: tickets 101 → 102 → 103 on gpt-6-luna, then human approvals in the dashboard. Shop date 2026-08-31.</p></header>
  <div class="cash">
    <div class="kpi"><span>Start (after reset)</span><b>{money(cash["start"])}</b></div>
    <div class="kpi"><span>Paid out (approved)</span><b>−{money(cash["paid_total"])}</b></div>
    <div class="kpi"><span>End (computed)</span><b>{money(cash["start"] - cash["paid_total"])}</b></div>
    <div class="kpi {"ok" if ok else ""}"><span>cash_accounts.balance</span><b>{money(cash["end_db"])} {"✓" if ok else "✕"}</b></div>
  </div>
  {"".join(cards)}
  <footer>Generated {datetime.now().strftime("%Y-%m-%d %H:%M")} by tools/problem9_report.py · data: output/resolved_tickets.json, output/audit_trail.json, data/campus_customs_new.db · full cash ledger: desk_tickets.html → Cash tab.</footer>
</div></body></html>
"""


def main() -> None:
    since, runs = load_runs()
    cash = cash_ledger(since)                     # raises if anything fails to reconcile
    statuses = ticket_statuses()
    unresolved = [t for t in TICKETS if statuses[t]["status"] != "resolved"]
    assert not unresolved, f"tickets not resolved: {unresolved}"
    fill_desk_tickets(runs, cash, statuses)
    data = resolved_json(runs, cash, statuses)
    (OUT / "resolved_tickets.json").write_text(json.dumps(data, indent=2, default=str) + "\n")
    (OUT / "resolved_board.html").write_text(board_html(data, cash))
    print(f"start {money(cash['start'])} - paid {money(cash['paid_total'])} = {money(cash['start'] - cash['paid_total'])}; "
          f"cash_accounts = {money(cash['end_db'])}  ✓")
    for t in data:
        print(f"ticket {t['ticket_id']}: {t['final_status']}/{t['stage']} route={t['route']} cash_change={t['cash_change']} "
              f"approvals={[(a['request_id'], a['action'], a['ok']) for a in t['human_approvals']]}")


if __name__ == "__main__":
    main()
