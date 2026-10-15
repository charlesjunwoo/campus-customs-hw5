import type { Ticket } from "../api";
import { TICKET_TYPE } from "../agents";

export const STAGE_LABEL: Record<Ticket["stage"], string> = {
  not_started: "Not started",
  running: "Agents working",
  needs_approval: "Needs your approval",
  complete: "Complete",
  blocked: "Blocked",
  needs_more_info: "Needs more info",
};

export function StatusPill({ t }: { t: Ticket }) {
  return t.status === "resolved"
    ? <span className="status resolved">✓ Resolved</span>
    : <span className={`status open ${t.agents_running ? "running" : ""}`}>{t.agents_running ? "● Running" : "Open"}</span>;
}

export function TicketList({ tickets, selected, onSelect }: { tickets: Ticket[]; selected: number | null; onSelect: (id: number) => void }) {
  return (
    <nav className="tickets" aria-label="Tickets">
      {tickets.map((t) => {
        const type = TICKET_TYPE[t.type] ?? { emoji: "🎫", label: t.type };
        return (
          <button key={t.id} className={`ticket-item ${selected === t.id ? "selected" : ""} st-${t.status}`} onClick={() => onSelect(t.id)}>
            <div className="ti-top">
              <span className="ti-id">#{t.id}</span>
              <StatusPill t={t} />
            </div>
            <div className="ti-subject">{type.emoji} {t.subject}</div>
            <div className="ti-meta">{type.label} · {t.requester}</div>
            <div className="ti-foot">
              <span className={`stage stage-${t.stage}`}>{STAGE_LABEL[t.stage]}</span>
              {t.pending_approvals > 0 && <span className="needs">✋ {t.pending_approvals}</span>}
            </div>
          </button>
        );
      })}
    </nav>
  );
}
