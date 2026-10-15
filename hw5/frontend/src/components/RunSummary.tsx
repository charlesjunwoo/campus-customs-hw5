import type { AgentName, Decision, ToolCall, Turn } from "../api";
import { AGENTS, EXPECTED_ROUTE, TOOL_VERBS, WRITE_TOOLS, money } from "../agents";
import { AgentGlyph } from "./AgentGlyph";

// What a write tool produced, read from its result (e.g. "request #2 · $840.00", "draft #1 to Tauhid Zaman").
function outcome(c: ToolCall): string | null {
  if (!c.ok) return `refused: ${c.error}`;
  const r = typeof c.result === "string" ? safeParse(c.result) : c.result;
  if (!r || typeof r !== "object") return null;
  const o = r as { request?: { id: number; amount: number; blocked_by?: string | null }; draft?: { id: number; recipient: string }; created?: boolean };
  if (o.request) return `request #${o.request.id} · ${money(o.request.amount)}${o.created === false ? " (reused)" : ""}${o.request.blocked_by ? " · blocked" : ""}`;
  if (o.draft) return `draft #${o.draft.id} to ${o.draft.recipient}${o.created === false ? " (updated)" : ""}`;
  return null;
}

function safeParse(s: string): unknown {
  try { return JSON.parse(s); } catch { return null; }
}

const DECISION_LABEL: Record<Decision["decision"], string> = {
  awaiting_human_approval: "Resolved: awaiting your approval",
  resolved: "Resolved",
  blocked: "Blocked",
  needs_more_info: "Needs more info",
};

export function RunSummary({ ticketId, turns, decision }: { ticketId: number; turns: Turn[]; decision: Decision | null }) {
  const boss = turns.find((t) => t.agent === "boss");
  const specialists = turns.filter((t) => t.agent !== "boss");
  const route = (boss?.delegations ?? []).filter((d) => !d.refused).map((d) => d.to);
  const expected = EXPECTED_ROUTE[ticketId] ?? [];
  const matches = route.length === expected.length && route.every((a, i) => a === expected[i]);
  const tokens = boss?.usage?.total_tokens;

  return (
    <div className="summary">
      {decision && (
        <div className="decision-card">
          <div className="decision-top">
            <AgentGlyph agent="boss" size={34} />
            <div>
              <div className="eyebrow">Boss's final call</div>
              <div className={`decision-pill d-${decision.decision}`}>{DECISION_LABEL[decision.decision]}</div>
            </div>
            {tokens != null && <div className="cost">{boss?.usage?.requests} model calls · {tokens.toLocaleString()} tokens</div>}
          </div>
          <p>{decision.summary}</p>
          {decision.next_steps_for_human.length > 0 && (
            <>
              <div className="eyebrow">Next steps for you</div>
              <ol className="steps">{decision.next_steps_for_human.map((s, i) => <li key={i}>{s}</li>)}</ol>
            </>
          )}
        </div>
      )}

      {boss && (
        <div className={`route-check ${matches ? "ok" : "warn"}`}>
          <span>{matches ? "✓ Route matches the plan" : "⚠ Route differs from the plan"}</span>
          <RouteChips label="Planned" agents={expected} />
          <RouteChips label="Actual" agents={route} />
        </div>
      )}

      <div className="agent-cards">
        {specialists.map((t, i) => (
          <AgentCard key={`${t.agent}-${i}`} turn={t} />
        ))}
      </div>
    </div>
  );
}

function RouteChips({ label, agents }: { label: string; agents: AgentName[] }) {
  return (
    <span className="route">
      <em>{label}</em>
      {agents.length ? agents.map((a, i) => (
        <span key={i} className="route-step" style={{ ["--c" as string]: AGENTS[a].color }}>
          {i > 0 && <b>→</b>}{AGENTS[a].emoji} {AGENTS[a].short}
        </span>
      )) : <span className="muted">none</span>}
    </span>
  );
}

function AgentCard({ turn }: { turn: Turn }) {
  const m = AGENTS[turn.agent];
  const said = turn.said;
  return (
    <article className="agent-card" style={{ ["--c" as string]: m.color }}>
      <header>
        <AgentGlyph agent={turn.agent} size={30} />
        <div>
          <h4>{m.label}</h4>
          <span className="muted small">{turn.status === "done" ? "Completed" : turn.status === "failed" ? "Failed" : "Working…"}
            {turn.usage ? ` · ${turn.usage.tool_calls} tool calls` : ""}</span>
        </div>
      </header>
      <ul className="actions">
        {turn.tools.map((c, i) => {
          const out = WRITE_TOOLS.has(c.tool) ? outcome(c) : null;
          return (
            <li key={i} className={`${WRITE_TOOLS.has(c.tool) ? "write" : ""} ${c.ok ? "" : "bad"}`}>
              <span className="check">{c.ok ? "✓" : "✕"}</span>
              {TOOL_VERBS[c.tool] ?? c.tool}
              {out && <span className="out">{out}</span>}
            </li>
          );
        })}
        {turn.delegations.map((d, i) => (
          <li key={`d${i}`} className="deleg"><span className="check">↗</span>Asked {AGENTS[d.to].label}{d.refused ? " (refused)" : ""}</li>
        ))}
      </ul>
      {said && (
        <div className="said">
          <p>“{said.summary}”</p>
          {said.recommendation && <p className="rec"><b>Recommends:</b> {said.recommendation}</p>}
        </div>
      )}
      {turn.error && <p className="error-text">{turn.error}</p>}
    </article>
  );
}
