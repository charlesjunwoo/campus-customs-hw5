import type { AgentName } from "../api";
import { AGENTS } from "../agents";

// Each agent's identity: a Memphis shape in its color with its emoji. Used in the graph, feed, and cards.
export function AgentGlyph({ agent, size = 28 }: { agent: AgentName; size?: number }) {
  const m = AGENTS[agent];
  const s = size;
  const shape = (() => {
    switch (m.shape) {
      case "circle":
        return <circle cx={s / 2} cy={s / 2} r={s / 2 - 2} />;
      case "square":
        return <rect x={2} y={2} width={s - 4} height={s - 4} />;
      case "triangle":
        return <polygon points={`${s / 2},2 ${s - 2},${s - 2} 2,${s - 2}`} />;
      case "arch":
        return <path d={`M2 ${s - 2} V${s / 2} A${s / 2 - 2} ${s / 2 - 2} 0 0 1 ${s - 2} ${s / 2} V${s - 2} Z`} />;
      case "bubble":
        return <path d={`M3 3 H${s - 3} V${s * 0.72} H${s * 0.42} L${s * 0.22} ${s - 2} V${s * 0.72} H3 Z`} />;
    }
  })();
  return (
    <span className="glyph" style={{ width: s, height: s }} title={`${m.label}: ${m.role}`}>
      <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} aria-hidden>
        <g fill={m.color} stroke="var(--ink)" strokeWidth={2} strokeLinejoin="round">{shape}</g>
      </svg>
      <span className="glyph-emoji" style={{ fontSize: s * 0.42, top: m.shape === "triangle" ? s * 0.12 : 0 }}>
        {m.emoji}
      </span>
    </span>
  );
}

export function AgentChip({ agent }: { agent: AgentName | "backend" }) {
  if (agent === "backend") return <span className="agent-chip">⚙️ Backend</span>;
  const m = AGENTS[agent];
  return (
    <span className="agent-chip" style={{ ["--c" as string]: m.color }}>
      <i /> {m.label}
    </span>
  );
}
