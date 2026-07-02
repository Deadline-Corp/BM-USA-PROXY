// Shared API DTO types. Mirrors the endpoint contracts in the task spec.
// ASSUMPTION: exact field names/shapes on nested objects (invoice, events,
// dossier sub-lists) are inferred from the spec's plain-English description
// where the spec didn't give a literal JSON shape. Documented per-type below.

export type AdminRole = "owner" | "admin" | "support";

export interface Admin {
  id: string;
  email: string;
  display_name: string;
  role: AdminRole;
}

export interface Paginated<T> {
  items: T[];
  total: number;
}

export type ListParams = Record<string, string | number | boolean | undefined>;

// ---------- Auth ----------

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  admin: Admin;
}

export interface RefreshResponse {
  access_token: string;
}

// ---------- Dashboard ----------

export interface DashboardSummary {
  revenue: {
    today: number;
    d7: number;
    d30: number;
  };
  active_accesses: number;
  free_pool: number;
  pending_manual_review: number;
  new_requests: number;
}

export interface RevenuePoint {
  date: string;
  revenue: number;
}

// ---------- Clients ----------

export interface Client {
  id: string;
  telegram_username: string | null;
  telegram_id: string | number;
  display_name: string | null;
  created_at: string;
  has_active_access: boolean;
  banned: boolean;
  operator_note: string | null;
}

export interface ClientTos {
  accepted: boolean;
  accepted_at: string | null;
  version: string | null;
}

export interface ClientAccess {
  id: string;
  tariff_code: string;
  status: string;
  city: string | null;
  carrier: string | null;
  ip: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface ClientOrder {
  id: string;
  status: string;
  provider: string;
  amount_usd: number;
  created_at: string;
}

export interface ClientReferral {
  code: string;
  clicks: number;
  attached: number;
  balance_usd: number;
}

export interface ClientRequest {
  id: string;
  status: string;
  subject: string;
  created_at: string;
}

export interface ClientDossier {
  profile: Client;
  tos: ClientTos;
  accesses: ClientAccess[];
  orders: ClientOrder[];
  referral: ClientReferral | null;
  requests: ClientRequest[];
}

export interface IssueAccessRequest {
  tariff_code: string;
  connection_id?: string;
  location_id?: string;
  carrier?: string;
}

// ---------- Tariffs ----------

export interface Tariff {
  id: string;
  code: string;
  name: string;
  price_usd: number;
  duration_days: number;
  max_user_swaps: number;
  is_active: boolean;
}

export type TariffInput = Omit<Tariff, "id">;

// ---------- Pool / Connections ----------

export interface Connection {
  id: string;
  external_id: string;
  city: string;
  state: string;
  carrier: string;
  online: boolean;
  is_sellable: boolean;
  tier: string | null;
  location_id: string | null;
  health_note: string | null;
  slots_total: number;
  slots_used: number;
  last_rotated_at: string | null;
}

export interface ConnectionUpdate {
  is_sellable?: boolean;
  tier?: string;
  location_id?: string;
  carrier?: string;
  health_note?: string;
}

export interface PoolCitySummary {
  city: string;
  state: string;
  carrier: string;
  slots_total: number;
  slots_used: number;
  online_nodes: number;
  offline_nodes: number;
  full_nodes: number;
}

export interface PoolSummary {
  slots_total: number;
  slots_used: number;
  slots_free: number;
  cities: PoolCitySummary[];
}

// ---------- Packages / Accesses ----------

export interface AccessRow {
  id: string;
  user: string;
  status: string;
  city: string | null;
  carrier: string | null;
  ip: string | null;
  tariff_code: string;
  expires_at: string | null;
  created_at: string;
}

// ---------- Orders / Payments ----------

export interface OrderInvoice {
  id: string;
  amount_usd: number;
  currency: string;
  wallet_address: string | null;
  memo: string | null;
}

export interface OrderEvent {
  id: string;
  type: string;
  message: string;
  created_at: string;
}

export interface Order {
  id: string;
  user: string;
  status: string;
  provider: string;
  amount_usd: number;
  created_at: string;
  invoice?: OrderInvoice;
  events?: OrderEvent[];
}

export interface RefundRequest {
  amount_usd: number;
  reason: string;
  wallet_address?: string;
  tx_hash?: string;
}

export interface ResolveOrderRequest {
  action: "approve" | "fail" | "refund";
}

export interface MarkPaidRequest {
  reason: string;
}

// ---------- Requests ----------

export type RequestStatus = "new" | "in_progress" | "waiting" | "done";

export interface SupportRequest {
  id: string;
  user: string;
  subject: string;
  status: RequestStatus;
  assignee_id: string | null;
  created_at: string;
}

export interface RequestComment {
  id: string;
  body: string;
  author: string;
  created_at: string;
}

// ---------- Referrals ----------

export interface ReferralSummary {
  total_referrers: number;
  total_clicks: number;
  total_attached: number;
  total_paid_usd: number;
  pending_payouts: number;
}

export interface ReferralLedgerEntry {
  id: string;
  referrer_user_id: string;
  referrer: string;
  status: string;
  amount_usd: number;
  created_at: string;
}

export interface Payout {
  id: string;
  referrer: string;
  amount_usd: number;
  status: string;
  requested_at: string;
}

export interface ReferralSettings {
  commission_pct: number;
  min_payout_usd: number;
  cookie_days: number;
}

// ---------- Broadcasts ----------

export interface Broadcast {
  id: string;
  title: string;
  body: string;
  audience_filter: Record<string, unknown>;
  status: string;
  scheduled_at: string | null;
  sent_at: string | null;
}

export interface BroadcastInput {
  title: string;
  body: string;
  audience_filter: Record<string, unknown>;
}

export interface BroadcastProgress {
  total: number;
  delivered: number;
  failed: number;
  status: string;
}

// ---------- Publications ----------

export interface Channel {
  id: string;
  name: string;
  handle: string;
  is_active: boolean;
}

export interface Post {
  id: string;
  channel_id: string;
  title: string;
  body: string;
  status: string;
  published_at: string | null;
  views: number | null;
  clicks: number | null;
}

export interface PostAttribution {
  post_id: string;
  views: number;
  clicks: number;
  conversions: number;
}

// ---------- FAQ ----------

export interface FaqItem {
  id: string;
  question: string;
  answer: string;
  is_published: boolean;
}

// ---------- Notifications ----------

export interface NotificationLogEntry {
  id: string;
  user: string;
  type: string;
  status: string;
  created_at: string;
}

export interface NotificationSettingEntry {
  event_key: string;
  label: string;
  description: string;
  telegram: boolean;
  email: boolean;
}

// ---------- System ----------

export interface AppSettings {
  [key: string]: string | number | boolean;
}

export interface TermsQuestion {
  id: string;
  text: string;
  required: boolean;
}

export interface Terms {
  version: string;
  published: boolean;
  questions: TermsQuestion[];
}

export interface AdminAccount {
  id: string;
  email: string;
  display_name: string;
  role: AdminRole;
  is_active: boolean;
}

export interface AdminAccountInput {
  email: string;
  display_name: string;
  role: AdminRole;
  password?: string;
}

export interface AuditLogEntry {
  id: string;
  admin: string;
  entity: string;
  action: string;
  created_at: string;
}
