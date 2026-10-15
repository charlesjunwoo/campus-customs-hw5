import { useState } from "react";
import type { Health } from "../api";

interface Props {
  health: Health | null;
  offline: boolean;
  approver: string;
  onApprover: (v: string) => void;
  onReset: () => Promise<void>;
  running: boolean;
}

export function TopBar({ health, offline, approver, onApprover, onReset, running }: Props) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <header className="topbar">
      <div className="brand">
        <span className="logo" aria-hidden><i /><b /></span>
        <div>
          <div className="brand-name">Campus Customs <span>Ops</span></div>
          <div className="brand-sub">Agent desk · human approvals</div>
        </div>
      </div>

      <div className="top-meta">
        <span className={`conn ${offline ? "down" : "up"}`}>{offline ? "API offline" : "Live"}</span>
        {health && <span className="meta-chip">Shop date <b>{health.shop_date}</b></span>}
        {health && <span className="meta-chip">Model <b>{health.model}</b></span>}
      </div>

      <div className="top-actions">
        <label className="approver">
          <span>Approving as</span>
          <input value={approver} onChange={(e) => onApprover(e.target.value)} placeholder="Your name" maxLength={80} />
        </label>
        {confirm ? (
          <>
            <button className="btn danger" disabled={busy} onClick={async () => { setBusy(true); await onReset(); setBusy(false); setConfirm(false); }}>
              {busy ? "Resetting…" : "Confirm reset"}
            </button>
            <button className="btn ghost light" onClick={() => setConfirm(false)}>Cancel</button>
          </>
        ) : (
          <button className="btn ghost light" disabled={running} title={running ? "Wait for the run to finish" : "Restore the shop database to its original values"} onClick={() => setConfirm(true)}>
            ↺ Reset shop
          </button>
        )}
      </div>
    </header>
  );
}
