# Campus Customs — HW5: Autonomous Agent Team

The whole project is in **[`hw5/`](hw5/)**. Start with [`hw5/README.md`](hw5/README.md) (setup and how to run everything), then [`hw5/output/harness.md`](hw5/output/harness.md) (how the system works).

- **What it is:** a five-agent team (Boss, Inventory, Accounting, Facilities, Customer Service) that runs the Campus Customs shop. The agents work through an MCP server and are monitored and approved from a React dashboard over a FastAPI backend. Agents prepare payments; only a human approves them.
- **Prompt log:** [`hw5/AI_prompts.md`](hw5/AI_prompts.md)
- **Full-run results:** [`hw5/output/resolved_board.html`](hw5/output/resolved_board.html) and [`hw5/output/desk_tickets.html`](hw5/output/desk_tickets.html) (Expected / Actual / Cash / Reflection)

Both HW5 databases are included under `hw5/data/`. No API keys are in this repository: copy `hw5/.env.example` to `hw5/.env` and add your own key.
