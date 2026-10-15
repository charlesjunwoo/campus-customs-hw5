import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, API_BASE } from "./api";
import type { ApprovalRequest, Cash, Draft, Health, Ticket, Turn } from "./api";
import { AGENTS, SPECIALISTS, TICKET_TYPE, money } from "./agents";
import { TopBar } from "./components/TopBar";
import { TicketList, StatusPill, STAGE_LABEL } from "./components/TicketList";
import { WorkflowGraph } from "./components/WorkflowGraph";
import { LiveFeed } from "./components/LiveFeed";
import { RunSummary } from "./components/RunSummary";
import { ApprovalCard, DraftCard } from "./components/Approvals";
import { CashCard } from "./components/CashCard";
import { AgentGlyph } from "./components/AgentGlyph";

const SLOW_MS = 4000; // idle refresh
const FAST_MS = 1200; // while agents are running

interface Toast { id: number; kind: "ok" | "bad" | "info"; text: string }

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [cash, setCash] = useState<Cash | null>(null);
  const [requests, setRequests] = useState<ApprovalRequest[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selected, setSelected] = useState<number | null>(() => Number(localStorage.getItem("cc.selected")) || null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [approver, setApprover] = useState(() => localStorage.getItem("cc.approver") ?? "");
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [starting, setStarting] = useState(false);
  const wasRunning = useRef<Set<number>>(new Set());

  const toast = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5200);
  }, []);

  const running = tickets.some((t) => t.agents_running);
  const ticket = tickets.find((t) => t.id === selected) ?? null;

  // --- data -------------------------------------------------------------------------------
  const refresh = useCallback(async () => {
    try {
      const [h, t, c, b] = await Promise.all([api.health(), api.tickets(), api.cash(), api.board()]);
      setHealth(h); setTickets(t.tickets); setCash(c); setRequests(b.approval_requests); setDrafts(b.drafts);
      setOffline(false);
      // Toast when a run finishes.
      const nowRunning = new Set(t.tickets.filter((x) => x.agents_running).map((x) => x.id));
      for (const id of wasRunning.current) {
        if (!nowRunning.has(id)) {
          const done = t.tickets.find((x) => x.id === id);
          if (done) toast(done.status === "resolved" ? "ok" : "info",
            `Ticket ${id}: ${done.status === "resolved" ? "resolved" : STAGE_LABEL[done.stage].toLowerCase()}${done.pending_approvals ? `. ${done.pending_approvals} approval(s) need you ✋` : ""}`);
        }
      }
      wasRunning.current = nowRunning;
    } catch (e) {
      setOffline(e instanceof ApiError);
    }
  }, [toast]);

  const loadActivity = useCallback(async (t: Ticket | null) => {
    if (!t) return setTurns([]);
    try {
      const a = t.active_run_id
        ? await api.activity({ run_id: t.active_run_id, limit: 50 })
        : await api.activity({ ticket_id: t.id, since_reset: true, limit: 50 });
      const runId = t.active_run_id ?? a.latest_run_id;
      setTurns(a.turns.filter((x) => x.run_id === runId).reverse()); // chronological
    } catch { /* offline banner covers it */ }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    const id = setInterval(refresh, running ? FAST_MS : SLOW_MS);
    return () => clearInterval(id);
  }, [refresh, running]);
  useEffect(() => { loadActivity(ticket); }, [ticket?.id, ticket?.active_run_id, ticket?.stage, tickets, loadActivity]);

  useEffect(() => { if (!selected && tickets.length) setSelected(tickets[0].id); }, [tickets, selected]);
  useEffect(() => { if (selected) localStorage.setItem("cc.selected", String(selected)); }, [selected]);
  useEffect(() => { localStorage.setItem("cc.approver", approver); }, [approver]);

  // --- actions ----------------------------------------------------------------------------
  async function startRun(id: number) {
    setStarting(true);
    try {
      await api.run(id);
      toast("info", `Agent team started on ticket ${id}`);
      await refresh();
    } catch (e) {
      toast("bad", (e as Error).message);
    } finally {
      setStarting(false);
    }
  }

  async function decide(req: ApprovalRequest, action: "approve" | "reject"): Promise<string | null> {
    try {
      const r = await api.decide(req.id, action, approver.trim());
      toast("ok", r.cash_before !== r.cash_after
        ? `${r.message} Checking ${money(r.cash_before)} → ${money(r.cash_after)}`
        : r.message);
      await refresh();
      return null;
    } catch (e) {
      toast("bad", (e as Error).message);
      return (e as Error).message;
    }
  }

  async function reset() {
    try {
      const r = await api.reset();
      toast("info", `${r.message} Checking ${money(r.balance)}.`);
      setTurns([]);
      await refresh();
    } catch (e) {
      toast("bad", (e as Error).message);
    }
  }

  const pending = requests.filter((r) => r.status === "pending_human");
  const ticketRequests = useMemo(
    () => requests.filter((r) => r.ticket_id === selected).sort((a, b) => Number(b.status === "pending_human") - Number(a.status === "pending_human") || a.id - b.id),
    [requests, selected],
  );
  const ticketDrafts = drafts.filter((d) => d.ticket_id === selected);
  const live = !!ticket?.agents_running;
  const bossDone = turns.some((t) => t.agent === "boss" && t.status !== "running");

  return (
    <div className="app">
      <TopBar health={health} offline={offline} approver={approver} onApprover={setApprover} onReset={reset} running={running} />

      {offline && (
        <div className="offline">
          Can't reach the ops API at <code>{API_BASE}</code>. Start it from <code>backend/</code> with <code>uvicorn main:app --reload --port 8000</code>.
        </div>
      )}

      <div className="layout">
        {/* ---------------- left: tickets ---------------- */}
        <aside className="rail left">
          <div className="rail-head">
            <h2>Tickets</h2>
            <span className="muted small">{tickets.filter((t) => t.status === "resolved").length}/{tickets.length} resolved</span>
          </div>
          <TicketList tickets={tickets} selected={selected} onSelect={setSelected} />
          <div className="legend-card">
            <div className="eyebrow">The team</div>
            {(["boss", ...SPECIALISTS] as const).map((a) => (
              <div key={a} className="legend-row">
                <AgentGlyph agent={a} size={24} />
                <div><b>{AGENTS[a].label}</b><span>{AGENTS[a].role}</span></div>
              </div>
            ))}
          </div>
        </aside>

        {/* ---------------- center: workspace ---------------- */}
        <main className="workspace">
          {ticket ? (
            <>
              <section className="ticket-head">
                <div className="th-main">
                  <div className="th-title">
                    <span className="th-id">#{ticket.id}</span>
                    <h1>{ticket.subject}</h1>
                    <StatusPill t={ticket} />
                  </div>
                  <div className="th-sub">
                    {(TICKET_TYPE[ticket.type] ?? { emoji: "🎫", label: ticket.type }).emoji} {(TICKET_TYPE[ticket.type] ?? { label: ticket.type }).label}
                    {" · "}from <b>{ticket.requester}</b>
                    {ticket.sku && <> · <code>{ticket.sku}</code> size <b>{ticket.size}</b> × <b>{ticket.qty}</b></>}
                    {ticket.invoice_id && <> · invoice <b>{ticket.invoice_id}</b></>}
                    {ticket.lease_id && <> · lease <b>{ticket.lease_id}</b></>}
                  </div>
                  {ticket.notes && <blockquote>“{ticket.notes}”</blockquote>}
                </div>
                <div className="th-action">
                  <button className="btn primary big" disabled={running || starting || offline} onClick={() => startRun(ticket.id)}>
                    {live ? <><span className="spinner" /> Agents working…</> : starting ? "Starting…" : ticket.stage === "not_started" ? "▶ Run agent team" : "↻ Run again"}
                  </button>
                  <span className="muted small">{running && !live ? "Another ticket is running" : STAGE_LABEL[ticket.stage]}</span>
                </div>
              </section>

              <div className="grid-2">
                <section className="panel">
                  <div className="panel-head">
                    <h3>Workflow</h3>
                    {live ? <span className="live-dot">LIVE</span> : <span className="muted small">{turns.length ? "Last run" : "Planned route"}</span>}
                  </div>
                  <WorkflowGraph ticketId={ticket.id} turns={turns} live={live} />
                </section>
                <section className="panel feed-panel">
                  <div className="panel-head">
                    <h3>Activity</h3>
                    <span className="muted small">What each agent is doing and saying</span>
                  </div>
                  <LiveFeed turns={turns} live={live} />
                </section>
              </div>

              {(ticketRequests.length > 0 || ticketDrafts.length > 0) && (
                <section className="panel">
                  <div className="panel-head">
                    <h3>On the board for #{ticket.id}</h3>
                    <span className="muted small">Agents prepare. You decide.</span>
                  </div>
                  <div className="board-grid">
                    {ticketRequests.map((r) => (
                      <ApprovalCard key={r.id} req={r} approver={approver} locked={running} onDecide={decide} />
                    ))}
                  </div>
                  {ticketDrafts.length > 0 && (
                    <div className="drafts">
                      {ticketDrafts.map((d) => <DraftCard key={d.id} draft={d} />)}
                    </div>
                  )}
                </section>
              )}

              {bossDone && (
                <section className="panel">
                  <div className="panel-head">
                    <h3>Run summary</h3>
                    <span className="muted small">What each agent completed on this ticket</span>
                  </div>
                  <RunSummary ticketId={ticket.id} turns={turns} decision={ticket.latest_decision} />
                </section>
              )}
            </>
          ) : (
            <div className="empty big">Loading tickets…</div>
          )}
        </main>

        {/* ---------------- right: money ---------------- */}
        <aside className="rail right">
          <CashCard cash={cash} />
          <section className="panel inbox">
            <div className="panel-head">
              <h3>Needs you {pending.length > 0 && <span className="count">{pending.length}</span>}</h3>
            </div>
            {pending.length ? pending.map((r) => (
              <ApprovalCard key={r.id} req={r} approver={approver} locked={running} onDecide={decide} compact onOpen={() => setSelected(r.ticket_id)} />
            )) : <div className="empty small">Nothing waiting on you. Agents can't approve payments; they land here.</div>}
          </section>
        </aside>
      </div>

      <div className="toasts" role="status">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}
      </div>
    </div>
  );
}
