import { useEffect, useState } from "react";
import type { ApprovalRequest, Draft } from "../api";
import { AGENTS, REQUEST_META, money } from "../agents";
import { AgentChip } from "./AgentGlyph";

interface CardProps {
  req: ApprovalRequest;
  approver: string;
  locked: boolean; // agents are running
  onDecide: (req: ApprovalRequest, action: "approve" | "reject") => Promise<string | null>;
  compact?: boolean;
  onOpen?: () => void;
}

// One request the agents prepared. Only a person can approve it, and approving takes two clicks.
export function ApprovalCard({ req, approver, locked, onDecide, compact, onOpen }: CardProps) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setError(null), [req.status]); // a stale refusal disappears once the request is decided
  const meta = REQUEST_META[req.kind];
  const pending = req.status === "pending_human";
  const moneyMoves = req.cash_out === 1;

  async function act(action: "approve" | "reject") {
    setBusy(true);
    setError(await onDecide(req, action));
    setBusy(false);
    setConfirming(false);
  }

  const disabledReason = !approver.trim() ? "Enter your name in the top bar to approve." : locked ? "Wait until the agents finish." : null;

  return (
    <article className={`approval ${pending ? "pending" : req.status} ${compact ? "compact" : ""}`}>
      <div className="approval-emoji" aria-hidden>{pending ? meta.emoji : req.status === "approved" ? "✅" : "🚫"}</div>
      <div className="approval-main">
        <div className="approval-top">
          <span className="eyebrow">{meta.label} · #{req.id}{compact ? ` · ticket ${req.ticket_id}` : ""}</span>
          <span className={`amount ${moneyMoves ? "out" : ""}`}>{moneyMoves ? "−" : ""}{money(req.amount)}</span>
        </div>
        <div className="approval-detail" onClick={onOpen} role={onOpen ? "button" : undefined}>{req.detail}</div>
        {!compact && <div className="approval-reason">“{req.reason}”</div>}
        {req.blocked_by && pending && <div className="blocked">⛔ Vendor won't ship until {req.blocked_by} is paid</div>}
        {!moneyMoves && <div className="note-line">No cash moves. This is a sign-off on the price.</div>}
        <div className="approval-meta">
          Prepared by <AgentChip agent={req.requested_by} />
          {!pending && <span className="decided">{req.status === "approved" ? "Approved" : "Rejected"} by {req.decided_by}</span>}
        </div>
        {pending && (
          <div className="approval-actions">
            {confirming ? (
              <>
                <button className="btn approve" disabled={busy} onClick={() => act("approve")}>
                  {busy ? "Working…" : moneyMoves ? `Confirm: pay ${money(req.amount)}` : "Confirm sign-off"}
                </button>
                <button className="btn ghost" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
              </>
            ) : (
              <>
                <button className="btn approve" disabled={!!disabledReason || busy} title={disabledReason ?? ""} onClick={() => setConfirming(true)}>
                  Approve
                </button>
                <button className="btn reject" disabled={!!disabledReason || busy} title={disabledReason ?? ""} onClick={() => act("reject")}>
                  Reject
                </button>
              </>
            )}
            {disabledReason && <span className="hint">{disabledReason}</span>}
          </div>
        )}
        {error && <div className="error-text">✕ {error}</div>}
      </div>
    </article>
  );
}

export function DraftCard({ draft }: { draft: Draft }) {
  const [open, setOpen] = useState(false);
  const icon = { customer: "✉️", landlord: "🏢", city: "🏛️", vendor: "📦" }[draft.audience];
  return (
    <article className={`draft ${open ? "open" : ""}`}>
      <button className="draft-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>{icon}</span>
        <span className="draft-to">To <b>{draft.recipient}</b> · {draft.subject}</span>
        <span className="never-sent">Draft · never sent</span>
        <span className="chev">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="draft-body">
          <pre>{draft.body}</pre>
          <div className="muted small">Written by {AGENTS[draft.author].label}. A human reviews and sends it.</div>
        </div>
      )}
    </article>
  );
}
