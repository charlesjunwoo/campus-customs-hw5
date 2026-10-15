// How each agent is represented everywhere in the UI: one color, one shape, one emoji, one verb.
import type { AgentName, ApprovalRequest } from "./api";

export interface AgentMeta {
  name: AgentName;
  label: string;
  short: string;
  emoji: string;
  shape: "circle" | "square" | "triangle" | "arch" | "bubble";
  color: string; // CSS variable
  role: string;
}

export const AGENTS: Record<AgentName, AgentMeta> = {
  boss: { name: "boss", label: "Boss", short: "Boss", emoji: "👑", shape: "circle", color: "var(--boss)", role: "Reads the ticket, routes it, makes the final call" },
  inventory: { name: "inventory", label: "Inventory", short: "Inventory", emoji: "📦", shape: "square", color: "var(--inventory)", role: "Stock by SKU and size, restock vendor, lead time" },
  accounting: { name: "accounting", label: "Accounting", short: "Accounting", emoji: "🧮", shape: "triangle", color: "var(--accounting)", role: "Cash, invoices, margins; prepares approvals" },
  facilities: { name: "facilities", label: "Facilities", short: "Facilities", emoji: "🏢", shape: "arch", color: "var(--facilities)", role: "Lease, rent, landlord and City" },
  customer_service: { name: "customer_service", label: "Customer Service", short: "Cust. Service", emoji: "💬", shape: "bubble", color: "var(--cs)", role: "Drafts every customer message" },
};

export const SPECIALISTS: AgentName[] = ["inventory", "accounting", "facilities", "customer_service"];

// Expected routing from output/desk_tickets.html (Problem 6), used for the "route check".
export const EXPECTED_ROUTE: Record<number, AgentName[]> = {
  101: ["inventory", "accounting", "customer_service"],
  102: ["facilities", "accounting"],
  103: ["inventory", "accounting", "customer_service"],
};

export const TOOL_VERBS: Record<string, string> = {
  list_open_tickets: "Listed open tickets",
  get_ticket: "Read the ticket",
  list_board: "Checked the board",
  check_inventory: "Checked stock",
  find_restock_vendor: "Found the restock vendor",
  find_unpaid_invoices: "Looked up unpaid invoices",
  check_lease_obligations: "Checked the lease",
  get_pricing: "Ran the margin math",
  get_cash_position: "Checked cash",
  submit_payment_request: "Prepared a payment for approval",
  submit_purchase_order: "Prepared a purchase order",
  submit_price_quote: "Proposed a price quote",
  save_draft: "Saved a draft",
  record_ticket_decision: "Recorded the decision",
};

export const WRITE_TOOLS = new Set(["submit_payment_request", "submit_purchase_order", "submit_price_quote", "save_draft"]);

export const REQUEST_META: Record<ApprovalRequest["kind"], { emoji: string; label: string }> = {
  invoice_payment: { emoji: "💸", label: "Vendor payment" },
  rent_payment: { emoji: "🏠", label: "Rent payment" },
  purchase_order: { emoji: "📦", label: "Purchase order" },
  price_quote: { emoji: "🏷️", label: "Price quote" },
};

export const TICKET_TYPE: Record<string, { emoji: string; label: string }> = {
  customer_order: { emoji: "👕", label: "Customer order" },
  rent_notice: { emoji: "🏠", label: "Rent notice" },
  price_override: { emoji: "🏷️", label: "Price override" },
};

export const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

export const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function fmtArgs(args: Record<string, unknown> | null): string {
  if (!args) return "";
  return Object.entries(args)
    .filter(([k, v]) => k !== "requested_by" && k !== "reason" && k !== "body" && v !== null && v !== undefined)
    .map(([k, v]) => `${k}=${typeof v === "string" ? JSON.stringify(v) : JSON.stringify(v)}`)
    .join(", ");
}
