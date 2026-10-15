import { useEffect, useRef, useState } from "react";
import type { Cash } from "../api";
import { money } from "../agents";

// Tween the balance so a payment visibly "drains" the number instead of silently swapping it.
// The first value and any change while the tab is hidden (browsers pause animation frames) jump straight to the target.
function useTween(target: number | null, ms = 900) {
  const [value, setValue] = useState(target ?? 0);
  const from = useRef<number | null>(null);
  useEffect(() => {
    if (target == null) return;
    const a = from.current;
    from.current = target;
    if (a == null || document.visibilityState !== "visible") {
      setValue(target);
      return;
    }
    const start = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const p = Math.min(1, (now - start) / ms);
      setValue(a + (target - a) * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    const settle = setTimeout(() => setValue(target), ms + 200); // never leave a half-finished number on screen
    return () => { cancelAnimationFrame(raf); clearTimeout(settle); setValue(target); };
  }, [target, ms]);
  return value;
}

export function CashCard({ cash }: { cash: Cash | null }) {
  const shown = useTween(cash?.balance ?? null);
  const prev = useRef<number | null>(null);
  const [delta, setDelta] = useState<{ v: number; key: number } | null>(null);

  useEffect(() => {
    if (cash == null) return;
    if (prev.current !== null && Math.abs(prev.current - cash.balance) > 0.004) {
      setDelta({ v: cash.balance - prev.current, key: Date.now() });
    }
    prev.current = cash.balance;
  }, [cash?.balance]);

  if (!cash) return <section className="panel cash"><div className="skeleton" /></section>;

  const o = cash.obligations;
  const scale = Math.max(cash.balance, o.total, 1);
  const seg = (v: number) => `${(v / scale) * 100}%`;

  return (
    <section className="panel cash">
      <div className="eyebrow">Checking · as of {cash.balance_date}</div>
      <div className="balance-row">
        <div className="balance">{money(shown)}</div>
        {delta && (
          <span key={delta.key} className={`delta ${delta.v < 0 ? "neg" : "pos"}`}>
            {delta.v < 0 ? "−" : "+"}{money(Math.abs(delta.v))}
          </span>
        )}
      </div>
      <div className="muted small">Cash only goes out. Revenue isn't modeled.</div>

      <div className="bars" aria-label="Cash versus obligations">
        <div className="bar-label"><span>Cash</span><b>{money(cash.balance)}</b></div>
        <div className="bar"><i className="b-cash" style={{ width: seg(cash.balance) }} /></div>
        <div className="bar-label"><span>Owed</span><b>{money(o.total)}</b></div>
        <div className="bar stacked">
          <i className="b-inv" style={{ width: seg(o.unpaid_invoices) }} title={`Unpaid invoices ${money(o.unpaid_invoices)}`} />
          <i className="b-rent" style={{ width: seg(o.rent_due_30_days) }} title={`Rent due ≤30 days ${money(o.rent_due_30_days)}`} />
          <i className="b-po" style={{ width: seg(o.pending_purchase_orders) }} title={`Pending POs ${money(o.pending_purchase_orders)}`} />
        </div>
        <div className="legend">
          <span><i className="b-inv" />Invoices {money(o.unpaid_invoices)}</span>
          <span><i className="b-rent" />Rent {money(o.rent_due_30_days)}</span>
          <span><i className="b-po" />POs {money(o.pending_purchase_orders)}</span>
        </div>
      </div>

      <div className={`projected ${cash.shortfall > 0 ? "short" : ""}`}>
        {cash.shortfall > 0
          ? <>⚠ Obligations exceed cash by <b>{money(cash.shortfall)}</b></>
          : <>After everything owed: <b>{money(cash.projected_balance_after_obligations)}</b></>}
      </div>

      {cash.payments_recorded.length > 0 && (
        <div className="payments">
          <div className="eyebrow">Payments you approved</div>
          {cash.payments_recorded.slice().reverse().map((p) => (
            <div key={p.id} className="payment">
              <span>{p.kind === "rent" ? "🏠" : p.kind === "invoice" ? "💸" : "📦"} {p.kind.replace("_", " ")} #{p.ref_id}</span>
              <span className="mono">−{money(p.amount)}</span>
              <span className="muted small">{p.approved_by}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
