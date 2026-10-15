# AI Prompts Log — Campus Customs Agent Team (HW5)

Running log of the prompts I gave the AI coding assistant for this assignment. Each problem has its own section with the prompt I used. If I had to send a follow-up, it's included with one sentence on what went wrong with the first attempt.

---

## Problem 1 — Kickoff: Multi-Agent Team Setup & Prompt Log

**Prompt:**

> For the last homework (HW 4) we built the Campus Customs website with an an accompanying chatbot that will help Campus Customs Today we're going to be assembling the multi-agent team that will manage and run Campus Customs autonomously. This will comprise of three pieces that communicate with one another: MCP Server, a FastAPI backend and a dashboard in React hat will enable me, TA, professor or other humans to see the agent workflow and approval process. The dashbaord is operational and for approvals not just a visualization tool. Same rules as always, we must Kickoff with our AI_prompts.md and update that throughout the assignment with prompts I used and a sentence explaining what was wrong with the first attempt if i had to send a followup prompt.  Do not jump ahead and build the whole assignment yet.
>
> We want agent-to-agent delegation, with a big boss owning the final decision making layer. The team must have the agents asfollows.
> 1. Boss who reads each ticket, decides who to delegate to and make final calls 2. Inventory: checks stock by SKU and size, spots shortfalls, figures out which vendor is able to restock 3. Accounting: monitor cash and invoices, check margins, prepare payments or purhcase orders for HUMAN (my) approval 4. Facilities: handles shop space side for IRL business such as leases, rent, landlord or City comms and contracts and 5. Customer Services: drafts messages for customers
>
> Rules for this shop are as follows.
> The field desk.date_today is "today" for the shop. Use this date to determine what is overdue. Vendor lead times come from the vendors table. A vendor will not ship new product while they still have an unpaid invoice. Human approval is needed for any payment and this is non-neogitable. It is my job as the human overseer to update the relevant table, not yours. Cash only goes out in this  assignment; we did not model revenue so no money comes in. Before a full run to resolve ticekts the database must be reset to original values. Do not email any real addresses or call actual/real vendors or customers. Drafts stay on the board. You must only use gpt-6-luna through Portkey for every agent.
>
> Use my PORTKEY_API_KEY for agent's calls. You will push this project to a public GitHub repo and give me the URL when we are finsihed so I can submit to my professor/TA.

---

## Problem 2 — Working Database Copy & Harness (Data Section)

**Prompt:**

> Ensuring we use gpt-6-luna through Portkey as specified, let's get into Problem 2.  If it errors when you test it, tell me the exact error and don't switch models without asking me.
>
> Now, Problem 2: use the original shop database we set up in Problem 1 as the source of truth and create a working copy at data/campus_customs_new.db. This is the copy we will update in later problems. Do not modify the original database. Observe the open tickets to see how they link to other tables. Start output/harness.md and for each table please list the fields and a short descriptor (1 setnence max) on the significance of that table and why it matters for the agents, how it impacts them. We will be growing this harnesss files as we progress through the assignment.

*Note:* the opening line restated the model choice because in Problem 1 the assistant questioned `gpt-6-luna`: it conflicted with the course AGENTS.md default (`gpt-5.6-luna`), and the assistant asked which one to use instead of testing the specified model first. When tested, `gpt-6-luna` worked.

---

## Problem 3 — MCP Server (FastMCP) with First Three Tools

**Prompt:**

> write an MCP server in mcp_server/ using FastMCP. This will talk to data/campus_customs_new.db. Every agent will be using the tools in this MCP server.
> For now, we just want to start with three tools we know we will need based on the current tickets: one to check inventory by SKU/size, one to find unpaid vendor invoices, and one to check lease/rent obligations. Only return information that actually exists in the database and do not hallucinate or make up any data.
> In output/harness.md list those tools and include for each tool: what table it reads, which ticket it helps unlock 101, 102 or 103, and one sentence on why that tool is the right one for that particular ticket. We will be scored for precision here so vague lines like "reads inventory" are not sufficient.
> Also add a short mcp_server/README.md file that explains what the MCP server is for, which database file it uses and the three tools it currently has.
> We do not need to connect or run the MCP server yet.

---

## Problem 4 — Connect the MCP Server & Smoke Test

**Prompt:**

> ok problem 4: connect the MCP server to this project. Save the MCP connection JSON text in .mcp.json at the project root. I am going to test each of the three MCP tools, and ensure that they are functioning for each tool with a series of prompts. Save those prompts and corresponding  tool name and tool output (which must match values in data/campus_customs_new.db) in output/mcp_smoke.json.

*Note:* the first smoke-test run hit a `gpt-6-luna` error (Chat Completions doesn't allow function tools on this model), so the assistant switched to the Responses API and kept the same model.

**Follow-up prompt:**

> we'reg onna start a new session to ensure we can actually run mcp and test the tools

*Why:* the first attempt only tested the server through a script that launched it from `.mcp.json`. A Claude Code session loads `.mcp.json` only at startup, so the session that wrote the file couldn't attach the `campus-customs` server and call its tools as real MCP tools. A new session opened in the project folder was needed. That session loaded the server, made 8 live MCP tool calls, and all 8 matched the database (`output/mcp_live_test.md`).

---

## Problem 5 — Build the Agent Team (PydanticAI) & Grow the MCP Server

**Prompt:**

> Problem 4: we're gonna build the team and grow our MCP capabilities now they've been proven to work right. Use PydanticAI to build out each team member I first listed out. Include prompts, models, agent loops so they can delegate to each other with full connectivity. Put the agent prompts in backend/prompts/ allocating a file for each agent. Put data types in backend/models.py and the agent files under backend/ with roles clearly delineated, and use my PORTKEY_API_KEY. Use only gpt-6-luna for every agent.
> I. need every agent prompt to contain enough context to comprehensively define scope of its work and the shop rules that apply to it, no generic fluff.
> Grow the MCP server with whatever additional tools these agents actually need to work through the open tickets. All shop facts need to come from the MCP server reading data/campus_customs_new.db — do not build another shop/database tool layer in the backend that bypasses MCP.
> As the agents run, append their agent-loop activity to output/audit_trail.json so we have enough information to audit what happened later. Do not wipe the file between runs.
> In the harness file list every agent and MCP tool inlcuding new ones added along with the corresponding tables they draw from. Please also add a safety section that contains guardrails a real business would need when it has real customers as well as limits to ensure we're using tokens responsibly. Then update mcp_server/README.md so its tool list matches the newly developed MCP server.

*Note:* I typed "Problem 4" in this prompt, but it's the fifth step, so it's logged as Problem 5 (Problem 4 was connecting the MCP server). I first sent a shorter version of this prompt, then interrupted it before any work started and resent it with the requirements above. No follow-up was needed after the full version.

---

## Problem 6 — Desk Tickets Page (Expected Workflows)

**Prompt:**

> Problem 6 now.
>
> Build output/desk_tickets.html a webpage that I can double click with one tab per ticket (101, 102 and 103). Add empty Cash and Reflection tabs for later problems (they can be left blank for now). On each ticket tab we need an "Expected" section (an "Actual" section will be filled by me after I run the agents and see theh outcomes)
> This is what I expect each team to do on each open ticket:
> For each ticket's "Expected" section we must determine the distributive workflow for three tickets according to the following flow:
> Ticket 101:  Boss to Inventory to Accounting to Customer SErvices
> Ticket 102: Boss to Facilities to Accounting
> Ticket 103: Boss to Inventory to Accounting to Customer Services
> All agent delegations we expect and which MCP tools we should expect the run in question to utilize. Importantly we don't want a situation where very agent gets sent every ticket.

---

## Problem 7 — FastAPI Backend for the Dashboard

**Prompt:**

> Problem 7 now: The dashboard needs a backend now so in backend/main.py we must use FastAPI and have routes for: 1. returning tickets 101, 102, 103 and indicating whether each is open/resolved 2. taking a ticket ID and running the agent team on that ticket 3. returning recent agent activity including what each agent said and which tools they used so the dashboard can refresh 4. processing human approval for a payment or purchase, with the agents only preparing it and this route being what actually changes cash 5. returning the current checking balance from cash_accounts and 6. resetting the database to its original values for each fresh run.
> In the backend folder start with:
> uvicorn main:app --reload --port 8000
> and in output/harness.md have one line per route that describes the URL and what it does.

*Note:* no follow-up was needed. While testing the run route, the assistant found that the Boss had delegated to Facilities and Accounting at the same time on ticket 102, so Accounting acted before Facilities verified the lease. It fixed this by making the Boss hand off one specialist at a time.

---

## Problem 8 — React Agent Dashboard

**Prompt:**

> Ok for Problem 8: build the frontend agent dashboard in frontend/ using React, Vite and TypeScript. This should talk to the FastAPI backend from Problem 7 at http://localhost:8000 On the dashboard please show all three tickets and whether they are open or resolved. I/TA/prof should be able to pick one ticket and start the agent team on it visualize workflow in realtime , including which agents are active and what they are saying/doing. Mark ticket as resolved when runs are finsihed and display  a log/short summary of what actions each agent completed on that ticket. If the agents prepare a payment that needs human approval, show that on the dashboard with a Emoji and let me approve or reject it myself. The agents cannot apporve this on their own. Also show  checking balance and make sure it updates after I approve a payment.
>
> Make the dashboard actually look good and feel like a real operations paltform someone would want to use with simplicity and good design princniples.
>
> The frontend should start with npm run dev
> Also in output/design.md explain design choices, how the different agents are represented, how resolved tickets and cash are shown, and why those aesthetic choices make the dashboard cracked.

*Note:* no follow-up was needed. During the assistant's live test, the dashboard's route check flagged that the Boss skipped Customer Service on ticket 101, so the customer got no reply. The assistant added a hard rule that customer-facing tickets must end with a customer draft. It also fixed a stale "vendor blocked" warning that stayed on the PO after the invoice was paid. Per this prompt, "resolved" now means the agent run finished, and pending approvals are shown separately as "Needs your approval."

---

## Problem 9 — Full Run, Actuals, Cash Ledger & Resolved Board

**Prompt:**

> Problem 9 now: time to actually run the full system and resolve all three tickets but before doing so reset the database data/campus_customs_new.db to start clean then run each ticket 101,102,103 to ensure they're resolved. Open output/desk_tickets.html from Problem 6. Each ticket tab, pls fill the "Actual" section from this run saying what happened which agents worked, delgations, tools used, etc. Keep all of my Expected sections exactly as they are though.
> Then we must itemize the money on the Cash tab.nclude the starting checking balance after the reset, then for each ticket show exactly how cash changed when that ticket was resolved and why, including the payment or purchase and exact dollar amount. Finish with the ending  balance and verify that it exactly matches cash_accounts in the working database no mistaskes on these transcations at all. This must be correct.
> Save output/resolved_tickets.json with an entry for each ticket containing the ticket id, final status, short outcome, what each agent contributed and any human approvals involved. Also create output/resolved_board.html that I can double click and open. Include a screenshot of the React dashboard for each resolved ticket. Append these runs to output/audit_trail.json and do not wipe history. Update harness accordingly.Finally update output/harness.md so it fully covers the database tables, MCP tools, all five agents, API routes, dashboard and safety rules.

*Note:* before approving anything, the assistant asked how the pending payments should be decided, since human approval is non-negotiable. I chose to approve or reject them myself in the dashboard as Charles Park, so the assistant ran the three tickets and waited. I approved the $840 invoice, the $8 tee PO, the $2,400 rent, and the $52/hoodie quote. My attempt to approve the $264 hoodie PO was refused as an overdraft ($152 left), so I rejected it. Ending checking: $152.00, verified against `cash_accounts`. While taking dashboard screenshots, the assistant found and fixed a balance animation that could freeze mid-count in a hidden tab.

**Follow-up prompt:**

> I rejected 5 because cash was insufficient and did not want to go ovedraft

*Why:* this wasn't a fix. The assistant had reported request #5 as still pending, and I was telling it that I had since rejected it, so the Cash tab and reports would show the final decision.

---

## Problem 10 — Reflection

**Prompt:**

> Great. Problem 10 now. Fill in the Reflection tab in output/desk_tickets.html based on what actually happened in the full run. Keep it in my own voice and tie it directly to the Expected vs Actual sections and the Cash tab:
> Ticket 101 worked basically as intended. The Boss routed it to Inventory, then Accounting, then Customer Service, which matched my expected workflow. Inventory established that the size S tee was out of stock and found the vendor issue, Accounting turned that into the invoice payment and purchase-order requests, and Customer Service drafted the customer update. All hadnoffs were smooth and made sense to me as a viewer of the dashboard. Ticket 102 also matched what I expected: Boss to Facilities to Accounting. It was a  clean flow as no unnecessary agents got pulled into it. Ticket 103 was more complex. The flow was correct, but Accounting handed work  back to Inventory, which I had not expected. Accounting also tried to submit invoice 501 again even though it already existed. The MCP/server guardrails caught that and returned the existing request instead of creating a duplicate. In other words the agents were not perfectly efficient, but the system was able to self-regulate, which is cybernetic, like Norbert Wiener would have said.
> Three new problems I think the current team and tools could solve:
>
> 1. An order where a size is out of stock and a vendor restock is required. Inventory can check the SKU and size, identify issues and avaiability with vendors accordingly then and then pass the result into Accounting for any needed payment/approval.
> 2. An order where Accounting has to appeal to a human for approval
> 3. An order requiring Customer Service directly. If the operational work is already understood but the customer needs an update.
>
> And for the three problems it could not solve:
>
> 1. Employee shifts or payroll. We do not have employee, scheduling, timesheet or payroll data, so the current agents and MCP tools have nothing to work with.
> 2. Financial forecasting. Accounting can inspect current cash, invoices, rent, pricing and purchase requests, but it cannot really forecast the future because there is no historical sales or revenue data whcih we would need at minimum.
> 3. Real communications beyond drafts. Customer Service and Facilities can prepare drafts, but the system  does not presentlyu send real emails or messages . To do that safely, we would need controlled communication tools and maybe another  human approval step.

---

## Problem 11 — Package as hw5/ and Publish to GitHub

**Prompt:**

> Final Proble: put the whole project inside a folder called hw5 and push it to a public GitHub repo. We need to submit the repo URL like we did in hw4.
> Make sure hw5 contains AI_prompts.md with all prompts!
> Do not put my real .env. Save URL to output/github_url.txt and please include both database files under data/
> Include .env.example with placeholder values only and no real API keys or secrets.
> README.md should explain how to run everything: copy/reset the original DB into the working copy for a clean run, start the MCP server, FastAPI backend, React frontend
> and reset the DB before a full run of al ltickets.
> Before pushing, check that all the required files are there, the repo does not contain the real .env, database or product images, and that .env.example only has placeholders.
> Then push it to a public GitHub repo and give me the repo URL.

*Note:* "no database" was read as no HW4 store database or product images, because this same prompt asks for both HW5 databases under `data/`. Both HW5 databases are included, and nothing from HW4 is.

---
