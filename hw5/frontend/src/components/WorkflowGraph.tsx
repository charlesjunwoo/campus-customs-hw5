import { useLayoutEffect, useRef, useState } from "react";
import type { AgentName, Turn } from "../api";
import { AGENTS, EXPECTED_ROUTE, SPECIALISTS, TOOL_VERBS, fmtArgs } from "../agents";
import { AgentGlyph } from "./AgentGlyph";

type NodeState = "idle" | "expected" | "skipped" | "running" | "done" | "failed";

interface Props {
  ticketId: number;
  turns: Turn[]; // chronological, current run only
  live: boolean; // a run is in progress for this ticket
}

const ORDINAL = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧"];

function nodeState(agent: AgentName, turns: Turn[], expected: AgentName[], hasRun: boolean): NodeState {
  const mine = turns.filter((t) => t.agent === agent);
  if (mine.some((t) => t.status === "running")) return "running";
  if (mine.some((t) => t.status === "failed")) return "failed";
  if (mine.length) return "done";
  if (agent === "boss") return "idle";
  if (expected.includes(agent)) return hasRun ? "idle" : "expected";
  return "skipped";
}

function nowLine(agent: AgentName, turns: Turn[]): string {
  const mine = turns.filter((t) => t.agent === agent);
  const last = mine[mine.length - 1];
  if (!last) return "";
  if (last.status === "running") {
    const tool = last.tools[last.tools.length - 1];
    const del = last.delegations[last.delegations.length - 1];
    if (del && (!tool || del.ts > tool.ts)) return `Waiting on ${AGENTS[del.to].label}…`;
    if (tool) return `${TOOL_VERBS[tool.tool] ?? tool.tool} · ${tool.tool}(${fmtArgs(tool.args)})`;
    return "Reading the task…";
  }
  if (last.status === "failed") return last.error ?? "Failed";
  return last.said?.summary ?? "";
}

export function WorkflowGraph({ ticketId, turns, live }: Props) {
  const expected = EXPECTED_ROUTE[ticketId] ?? [];
  const hasRun = turns.length > 0;
  const boxRef = useRef<HTMLDivElement>(null);
  const bossRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [anchors, setAnchors] = useState<{ boss: [number, number]; rows: Record<string, [number, number]>; w: number; h: number }>();

  // Measure node positions so the SVG edges line up with the HTML cards at any width.
  useLayoutEffect(() => {
    const measure = () => {
      const box = boxRef.current?.getBoundingClientRect();
      const b = bossRef.current?.getBoundingClientRect();
      if (!box || !b) return;
      const rows: Record<string, [number, number]> = {};
      for (const a of SPECIALISTS) {
        const r = rowRefs.current[a]?.getBoundingClientRect();
        if (r) rows[a] = [r.left - box.left, r.top - box.top + r.height / 2];
      }
      setAnchors({ boss: [b.right - box.left, b.top - box.top + b.height / 2], rows, w: box.width, h: box.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (boxRef.current) ro.observe(boxRef.current);
    return () => ro.disconnect();
  }, [turns]);

  // Edges: every delegation that happened (in order), else the expected route as ghosts.
  const order: { from: AgentName; to: AgentName; n: number; refused: boolean; active: boolean }[] = [];
  let n = 0;
  for (const t of turns) {
    for (const d of t.delegations) {
      const child = turns.find((c) => c.agent === d.to && c.started >= d.ts && c.asked_by === t.agent);
      order.push({ from: t.agent, to: d.to, n: n++, refused: d.refused, active: child?.status === "running" });
    }
  }
  const edges = hasRun ? order : expected.map((to, i) => ({ from: "boss" as AgentName, to, n: i, refused: false, active: false }));

  const bossState = nodeState("boss", turns, expected, hasRun);
  const boss = turns.find((t) => t.agent === "boss");

  return (
    <div className={`graph ${live ? "is-live" : ""}`} ref={boxRef}>
      {anchors && (
        <svg className="edges" width={anchors.w} height={anchors.h} aria-hidden>
          {edges.map((e) => {
            const to = anchors.rows[e.to];
            const from = e.from === "boss" ? anchors.boss : anchors.rows[e.from];
            if (!to || !from) return null;
            const peer = e.from !== "boss";
            const [x1, y1] = peer ? [from[0], from[1]] : from;
            const [x2, y2] = to;
            const path = peer
              ? `M${x1} ${y1} C${x1 - 70} ${y1}, ${x2 - 70} ${y2}, ${x2} ${y2}`
              : `M${x1} ${y1} C${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2 - 6} ${y2}`;
            const cls = !hasRun ? "ghost" : e.refused ? "refused" : e.active ? "active" : "done";
            return (
              <g key={`${e.from}-${e.to}-${e.n}`} className={`edge ${cls}`} style={{ ["--c" as string]: AGENTS[e.to].color }}>
                <path d={path} />
                <circle cx={x2 - 6} cy={y2} r={4} />
              </g>
            );
          })}
        </svg>
      )}

      <div className="graph-boss">
        <div className={`node node-boss state-${bossState}`} ref={bossRef} style={{ ["--c" as string]: AGENTS.boss.color }}>
          <AgentGlyph agent="boss" size={56} />
          <div className="node-name">Boss</div>
          <div className="node-state">{stateLabel(bossState, true)}</div>
          {boss && <div className="node-now">{nowLine("boss", turns)}</div>}
          {!hasRun && <div className="node-now muted">Reads the ticket and routes it.</div>}
        </div>
      </div>

      <div className="graph-rows">
        {SPECIALISTS.map((a) => {
          const st = nodeState(a, turns, expected, hasRun);
          const idx = edges.filter((e) => e.to === a && !e.refused).map((e) => e.n);
          const asked = turns.find((t) => t.agent === a)?.asked_by;
          return (
            <div key={a} className={`row state-${st}`} ref={(el) => { rowRefs.current[a] = el; }} style={{ ["--c" as string]: AGENTS[a].color }}>
              <div className="row-order">{idx.map((i) => ORDINAL[i] ?? i + 1).join(" ")}</div>
              <AgentGlyph agent={a} size={40} />
              <div className="row-body">
                <div className="row-head">
                  <span className="row-name">{AGENTS[a].label}</span>
                  <span className={`state-pill s-${st}`}>{stateLabel(st, false)}</span>
                  {asked && asked !== "boss" && asked !== "backend" && <span className="peer-tag">asked by {AGENTS[asked].label}</span>}
                </div>
                <div className="row-now">{nowLine(a, turns) || <span className="muted">{AGENTS[a].role}</span>}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function stateLabel(s: NodeState, boss: boolean): string {
  switch (s) {
    case "running": return boss ? "Routing…" : "Working…";
    case "done": return boss ? "Decided" : "Done";
    case "failed": return "Failed";
    case "expected": return "Expected";
    case "skipped": return "Not needed";
    default: return "Idle";
  }
}
