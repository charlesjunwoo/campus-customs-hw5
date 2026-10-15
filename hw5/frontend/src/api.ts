// Typed client for the Campus Customs ops API (backend/main.py).
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type AgentName = "boss" | "inventory" | "accounting" | "facilities" | "customer_service";

export interface Decision {
  id: number;
  ticket_id: number;
  decision: "awaiting_human_approval" | "blocked" | "resolved" | "needs_more_info";
  summary: string;
  approval_ids: number[];
  draft_ids: number[];
  next_steps_for_human: string[];
  decided_by: string;
  created_at: string;
}

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  sku: string | null;
  size: string | null;
  qty: number | null;
  lease_id: number | null;
  invoice_id: number | null;
  notes: string | null;
  created_at: string;
  status: "open" | "resolved";
  stage: "not_started" | "running" | "needs_approval" | "complete" | "blocked" | "needs_more_info";
  latest_decision: Decision | null;
  pending_approvals: number;
  agents_running: boolean;
  active_run_id: string | null;
}

export interface ApprovalRequest {
  id: number;
  ticket_id: number;
  kind: "invoice_payment" | "rent_payment" | "purchase_order" | "price_quote";
  ref_id: number | null;
  vendor_id: number | null;
  sku: string | null;
  size: string | null;
  qty: number | null;
  unit_price: number | null;
  amount: number;
  cash_out: 0 | 1;
  blocked_by: string | null;
  detail: string | null;
  reason: string;
  requested_by: AgentName;
  status: "pending_human" | "approved" | "rejected";
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
}

export interface Draft {
  id: number;
  ticket_id: number;
  audience: "customer" | "landlord" | "city" | "vendor";
  recipient: string;
  subject: string;
  body: string;
  author: AgentName;
  status: string;
  sent: number;
  updated_at: string;
}

export interface Payment {
  id: number;
  kind: string;
  ref_id: number;
  amount: number;
  account: string;
  paid_at: string;
  approved_by: string;
}

export interface Cash {
  account: string;
  balance: number;
  balance_date: string;
  as_of: string;
  payments_recorded: Payment[];
  obligations: { unpaid_invoices: number; rent_due_30_days: number; pending_purchase_orders: number; total: number };
  projected_balance_after_obligations: number;
  shortfall: number;
}

export interface ToolCall {
  ts: string;
  tool: string;
  args: Record<string, unknown> | null;
  ok: boolean;
  ms: number | null;
  error: string | null;
  result: unknown;
}

export interface Delegation {
  ts: string;
  to: AgentName;
  task: string;
  refused: boolean;
  reason: string | null;
}

export interface SpecialistSaid {
  summary: string;
  recommendation?: string;
  analysis?: string;
  board_items_created?: string[];
  blockers?: string[];
  needs_human?: string[];
  facts?: { label: string; value: string; source_tool: string }[];
  // BossDecision fields
  decision?: Decision["decision"];
  next_steps_for_human?: string[];
  delegated_to?: AgentName[];
}

export interface Turn {
  run_id: string;
  ticket_id: number;
  agent: AgentName;
  depth: number;
  asked_by: AgentName | "backend";
  task: string;
  started: string;
  ended: string | null;
  status: "running" | "done" | "failed";
  tools: ToolCall[];
  delegations: Delegation[];
  said: SpecialistSaid | null;
  usage: { requests: number; tool_calls: number; total_tokens: number } | null;
  error: string | null;
}

export interface HumanEvent {
  ts: string;
  event: "human_decision" | "db_reset";
  ticket_id?: number;
  request_id?: number;
  action?: "approve" | "reject";
  decided_by?: string;
  ok?: boolean;
  kind?: ApprovalRequest["kind"];
  amount?: number;
  cash_before?: number;
  cash_after?: number;
  error?: string;
}

export interface Activity {
  agent_run_in_progress: boolean;
  latest_run_id: string | null;
  turns: Turn[];
  human_and_system_events: HumanEvent[];
}

export interface RunStatus {
  run_id: string;
  ticket_id: number;
  status: "queued" | "running" | "done" | "failed";
  started_at: string;
  finished_at: string | null;
  result: { ok?: boolean; error?: string; usage?: { requests: number; total_tokens: number } } | null;
}

export interface Health {
  ok: boolean;
  model: string;
  mcp: string;
  shop_date: string;
  agent_run_in_progress: boolean;
}

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(`Can't reach the ops API at ${API_BASE}.`);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail;
    throw new ApiError(typeof detail === "string" ? detail : `Request failed (${res.status}).`);
  }
  return body as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  tickets: () => request<{ as_of: string; tickets: Ticket[] }>("/api/tickets"),
  cash: () => request<Cash>("/api/cash"),
  board: () => request<{ approval_requests: ApprovalRequest[]; drafts: Draft[] }>("/api/approvals?status=all"),
  activity: (q: { ticket_id?: number; run_id?: string; since_reset?: boolean; limit?: number }) => {
    const p = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => v !== undefined && p.set(k, String(v)));
    return request<Activity>(`/api/activity?${p}`);
  },
  run: (ticketId: number) =>
    request<{ run_id: string; ticket_id: number }>(`/api/tickets/${ticketId}/run`, { method: "POST" }),
  runStatus: (runId: string) => request<RunStatus>(`/api/runs/${runId}`),
  decide: (requestId: number, action: "approve" | "reject", decidedBy: string) =>
    request<{ message: string; cash_before: number; cash_after: number }>(`/api/approvals/${requestId}/${action}`, {
      method: "POST",
      body: JSON.stringify({ decided_by: decidedBy }),
    }),
  reset: () => request<{ message: string; balance: number }>("/api/reset", { method: "POST" }),
};
