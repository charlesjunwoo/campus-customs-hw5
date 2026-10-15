# Campus Customs Ops: Dashboard Design

`frontend/` (React 19 + Vite + TypeScript, no UI library). Run it with `npm run dev`, which serves http://localhost:5173 and talks to the FastAPI backend at http://localhost:8000.

## 1. What the dashboard is for

A professor, TA, or shop owner should be able to answer four questions within seconds of opening it:

1. **What's on the desk?** Three tickets and whether each is open or resolved.
2. **What are the agents doing right now?** Who is working, what they're calling, and what they said.
3. **What needs me?** Payments and purchases the agents prepared but can't approve.
4. **How much cash is left?** The checking balance, and what is already owed against it.

Every layout decision serves one of those questions. Anything that didn't was left out.

## 2. Layout: three zones, read left to right

```
┌──────────── top bar: brand · Live · shop date · model · "Approving as" · Reset ────────────┐
│ TICKETS (what)    │ WORKSPACE for the selected ticket (doing)        │ MONEY (needs me)    │
│ #101 ✓ Resolved   │ #101 Bulldog tee   [▶ Run agent team]            │ Checking $3,400.00  │
│ #102 Open         │ Workflow graph (live)                            │ cash vs owed bars   │
│ #103 Open         │ Activity feed (live)                             │ Needs you ✋ 2      │
│ The team legend   │ On the board: approvals + drafts                 │  💸 −$840  Approve  │
│                   │ Run summary: Boss's call + per-agent actions     │  📦 −$8    Approve  │
└───────────────────┴──────────────────────────────────────────────────┴─────────────────────┘
```

- **Left = the queue.** Tickets are always visible, so switching context is one click. Each card shows its status pill, its stage ("Needs your approval", "Agents working", "Complete"), and a ✋ count of approvals waiting.
- **Center = the work.** It follows the order of a run: start → watch the route → read the activity → act on the board → read the summary.
- **Right = money.** Cash and the approval inbox sit together because approving is the only thing that changes cash. You see the balance move as you click.
- Both side rails are sticky, so cash and pending approvals stay in view while you scroll a long run. Below 1360px the money rail moves under the workspace, and below 900px everything stacks into one column. Tested at desktop and tablet widths with no horizontal overflow.

## 3. How the agents are represented

Each agent has **one color, one geometric shape, and one emoji**, and they never change. That glyph appears in the graph, the activity feed, the approval cards ("Prepared by"), the run summary, and the team legend, so you can recognize an agent before you read its name.

| Agent | Shape | Color | Emoji | Why |
|---|---|---|---|---|
| Boss | Circle | Yellow `#ffd23f` | 👑 | The hub. The circle is the only round, "central" form, and yellow is the warmest, most dominant hue. |
| Inventory | Square | Teal `#13c4b4` | 📦 | Boxes on shelves: a stable, countable shape for a counting job. |
| Accounting | Triangle | Lilac `#a98bff` | 🧮 | The sharpest shape for the strictest role, the one that gates money. |
| Facilities | Arch | Peach `#ff9f6b` | 🏢 | A doorway, for the physical shop space. |
| Customer Service | Speech bubble | Pink `#ff5fa2` | 💬 | It is literally the voice of the shop. |

The shapes come from the Memphis / postmodern-'80s vocabulary (circles, squares, triangles, arches, squiggles). That's the course's house style, and it's the same palette as `output/desk_tickets.html`, so the planning page and the live dashboard read as one system. Shape plus color also means agents stay distinguishable for color-blind users and in grayscale screenshots.

## 4. Watching a run in real time

- **Workflow graph.** The Boss sits on the left and the four specialists on the right, joined by SVG edges measured from the real card positions, so the edges line up at any width.
  - **Before a run**, the graph shows the *planned* route from Problem 6 as dashed grey edges numbered ①②③. Agents the ticket doesn't need are faded and marked *Not needed*, so you can see the team isn't broadcasting.
  - **During a run**, the active hand-off edge animates (marching dashes in that agent's color), and the active agent's card pulses in its color with a *Working…* pill and a "now" line: the exact MCP tool and arguments it's calling (`Checked stock · check_inventory(sku="CC-TEE-WHITE", size="S", requested_qty=1)`). The Boss reads "Waiting on Inventory…" while it waits.
  - **After a run**, edges turn solid, cards say *Done*, and each card's line shows what that agent reported back.
- **Activity feed.** One chronological stream, newest first: who picked up which task from whom, each tool call (with its duration), each hand-off, and what each agent said when it reported back. Board writes (payment requests, POs, quotes, drafts) get a black **BOARD WRITE** tag, because they're the actions that matter to a human. A blue "Agents are working…" row with bouncing dots tells you it's live.
- **Polling, not magic.** The dashboard polls every 1.2s while agents run and every 4s when idle. A toast announces when a run finishes ("Ticket 101: resolved. 2 approval(s) need you ✋"). Reloading mid-run picks the run back up, because the API reports each ticket's `active_run_id`.

## 5. How resolved tickets are shown

- **Status** answers "is the agents' work done?" and is a pill. *Open* is blue, *● Running* is solid blue and pulsing, and *✓ Resolved* is green. A ticket becomes **Resolved when its agent run finishes** with the Boss's decision recorded (`resolved` or `awaiting_human_approval`). `blocked` and `needs_more_info` keep it open.
- **Stage** answers "what happens next?" and is plain text under the card: *Not started*, *Agents working*, ***Needs your approval*** (pink, with a ✋ count), or *Complete*. Splitting the two means a ticket can be resolved by the agents while still clearly waiting on you. The dashboard never implies money moved when it didn't.
- **Run summary** (shown after the Boss decides):
  - The Boss's final call as a green "Resolved: awaiting your approval" pill, its reasoning, and numbered next steps for you.
  - A **route check** comparing the planned route (Problem 6) with the actual route. It's green ✓ when they match and amber ⚠ when they don't. This check caught a real bug during testing (see section 8).
  - One card per specialist listing what it completed (✓ per tool, in plain English), with board writes in bold and their outcome (`request #2 · $840.00`, `draft #1 to Tauhid Zaman`), plus what the agent said and recommended.

## 6. How cash and approvals are shown

- **Checking balance** is the largest number on the screen (36px monospace, tabular figures). When it changes it **counts down** over about 0.9s, and a red **−$840.00** chip pops in beside it and fades. You see the money leave instead of a number silently swapping.
- **Cash vs owed bars.** One bar for cash, and one stacked bar for what's owed: invoices (lilac, Accounting's color), rent (peach, Facilities'), and POs (teal, Inventory's). The bars share a scale, so "owed > cash" is visible before you read a number. If it is, an amber line says by how much.
- **"Payments you approved"** lists each payment with its emoji, amount, and approver name, as a receipt trail.
- **Approval cards** each carry an emoji for what kind of money is involved: 💸 vendor payment, 🏠 rent, 📦 purchase order, 🏷️ price quote. They also show the amount in red with a minus sign (cash out), the server-computed detail, the agent's reason, and who prepared it. A blocked PO shows ⛔ *Vendor won't ship until invoice 501 is paid*, and that warning clears once you pay the invoice. A price quote says "No cash moves."
- **Agents can't approve.** No agent has the approval tool. The buttons exist only in this UI and call `POST /api/approvals/{id}/approve`.
- **Approving takes two clicks.** *Approve* → *Confirm: pay $840.00*. Rejecting is one click because it's harmless. Buttons are disabled, with an explanation, until you enter your name in **Approving as** (it's recorded in `payments.approved_by`) and while agents are running.
- **Refusals are explained in place.** The server's message appears on the card, e.g. "Vendor 1 won't ship while invoice 501 ($840.00) is unpaid. Approve that payment first." Overdrafts are refused the same way.

## 7. Visual system

- **Color is reserved for meaning.** The page itself is warm paper `#f6f3ea` with ink `#17172b`. The five agent hues are the only saturated colors, plus three state colors: green for resolved or approved, red for money out, refused, or live, and amber for warnings. Nothing is colored just for decoration.
- **Memphis, used sparingly.** There's one loud moment: the five-color confetti band under the top bar, which doubles as a key to the agent palette. Everything else borrows only the style's structure: 1.5px ink outlines, hard offset shadows (`4px 4px 0` ink) on primary surfaces, geometric glyphs, and Futura-style uppercase labels.
- **Typography.** Geometric display caps for section labels, a neutral sans for reading, and monospace for anything you might compare or copy (money, ticket ids, tool calls).
- **Motion means state.** Pulsing rings mean working, marching dashes mean a hand-off in flight, blinking red means LIVE, and a count-down means money left. Motion is turned off under `prefers-reduced-motion`.
- **Empty states teach.** "Nothing waiting on you. Agents can't approve payments; they land here." Before a run, the graph shows the plan instead of a blank box.

## 8. Why it's cracked

- **It explains the system while you use it.** A first-time TA sees the planned route, watches the real route draw itself over it, and gets a ✓ or ⚠ verdict. That shows the multi-agent design, the routing logic, and the guardrails, with no README needed.
- **Trust is designed in, not bolted on.** Money has one visual path: agent prepares → card with emoji → your two-click confirm → balance visibly counts down → receipt. Refusals arrive with the reason. Drafts are stamped "never sent."
- **It caught real bugs.** While testing, the route check went amber because the Boss skipped Customer Service on ticket 101 and left the customer without a reply. That led to a hard rule in the Boss's validator: customer-facing tickets must end with a customer draft. The approval card also exposed a stale ⛔ "blocked" warning after the invoice was paid, which is now cleared by the approval transaction.
- **It feels like a real ops tool.** It has sticky rails, a live indicator, toasts, keyboard-reachable controls, persistent selection and approver name, a recoverable live state after reload, a reset with confirmation, and an offline banner that tells you the exact command to start the API.
- **It looks like itself.** Most dashboards are a gray grid of identical cards. This one has an identity: five geometric characters you recognize at a glance, on warm paper, with one burst of '80s color. It's still disciplined enough that the only thing shouting is the thing that needs you.
