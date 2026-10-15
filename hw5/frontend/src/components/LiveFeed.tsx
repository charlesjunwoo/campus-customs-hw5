import type { AgentName, Turn } from "../api";
import { AGENTS, TOOL_VERBS, WRITE_TOOLS, clock, fmtArgs } from "../agents";
import { AgentGlyph } from "./AgentGlyph";

interface FeedItem {
  ts: string;
  agent: AgentName;
  kind: "start" | "tool" | "delegate" | "said" | "error";
  title: string;
  detail?: string;
  ok?: boolean;
  write?: boolean;
}

// Flatten agent turns into one chronological stream: who was asked, each tool call, each hand-off, what they said.
function toItems(turns: Turn[]): FeedItem[] {
  const items: FeedItem[] = [];
  for (const t of turns) {
    const from = t.asked_by === "backend" ? "Dashboard" : AGENTS[t.asked_by].label;
    items.push({ ts: t.started, agent: t.agent, kind: "start", title: `Picked up the task from ${from}`, detail: t.task });
    for (const c of t.tools) {
      items.push({
        ts: c.ts, agent: t.agent, kind: "tool", ok: c.ok, write: WRITE_TOOLS.has(c.tool),
        title: TOOL_VERBS[c.tool] ?? c.tool,
        detail: c.ok ? `${c.tool}(${fmtArgs(c.args)})${c.ms != null ? ` · ${c.ms} ms` : ""}` : `${c.tool} refused: ${c.error}`,
      });
    }
    for (const d of t.delegations) {
      items.push({
        ts: d.ts, agent: t.agent, kind: "delegate", ok: !d.refused,
        title: d.refused ? `Hand-off to ${AGENTS[d.to].label} refused` : `Handed off to ${AGENTS[d.to].label}`,
        detail: d.refused ? d.reason ?? "" : d.task,
      });
    }
    if (t.ended && t.said) {
      items.push({ ts: t.ended, agent: t.agent, kind: "said", title: t.agent === "boss" ? "Final call" : "Reported back", detail: t.said.summary });
    }
    if (t.ended && t.status === "failed") {
      items.push({ ts: t.ended, agent: t.agent, kind: "error", title: "Run failed", detail: t.error ?? "" });
    }
  }
  return items.sort((a, b) => (a.ts < b.ts ? 1 : -1)); // newest first
}

export function LiveFeed({ turns, live }: { turns: Turn[]; live: boolean }) {
  const items = toItems(turns);
  if (!items.length) {
    return <div className="empty">No agent activity yet for this ticket. Start the team to watch it work here.</div>;
  }
  return (
    <ol className="feed">
      {live && (
        <li className="feed-item typing">
          <span className="dots"><i /><i /><i /></span> Agents are working. This feed updates live.
        </li>
      )}
      {items.map((it, i) => (
        <li key={`${it.ts}-${i}`} className={`feed-item k-${it.kind} ${it.write ? "is-write" : ""} ${it.ok === false ? "is-bad" : ""}`}
            style={{ ["--c" as string]: AGENTS[it.agent].color }}>
          <AgentGlyph agent={it.agent} size={22} />
          <div className="feed-body">
            <div className="feed-title">
              <b>{AGENTS[it.agent].label}</b> {it.title}
              {it.write && <span className="tag">board write</span>}
            </div>
            {it.detail && <div className={`feed-detail ${it.kind === "tool" ? "mono" : ""}`}>{it.detail}</div>}
          </div>
          <time>{clock(it.ts)}</time>
        </li>
      ))}
    </ol>
  );
}
