// Shared API DTO types. Mirrors the endpoint contracts in the task spec.
// ASSUMPTION: exact field names/shapes on nested objects (invoice, events,
// dossier sub-lists) are inferred from the spec's plain-English description
// where the spec didn't give a literal JSON shape. Documented per-type below.

export interface Admin {
  id: string;
  email: string;
  display_name: string;
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

/** Step one either signs you in or asks for the code that was just sent to Telegram.
 *  Which of the two comes back depends on whether that account has a Telegram chat
 *  bound — the console never has to be told, and there is no setting to get wrong. */
export type LoginResponse =
  | { otp_required?: false; access_token: string; admin: Admin }
  | { otp_required: true; ticket: string; expires_in: number; sent_to: string | null };

export interface OtpRequest {
  ticket: string;
  code: string;
}

export interface SignedIn {
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
  unread_messages: number;
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
  /** Inbound messages from this client still unread by an operator — same read_at the
   *  sidebar "Clients" badge counts and the dossier clears on open. */
  unread_messages: number;
  /** Accepted the currently published Terms of Use version — see ClientTos for the
   *  full picture (version, answers) shown in the dossier. */
  terms_accepted: boolean;
  terms_accepted_at: string | null;
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
  /** The iproxy connection serving it — pasted straight into the iproxy console. */
  connection_id: string | null;
  revoked_at: string | null;
  revoke_reason: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface ClientOrder {
  id: string;
  number: number;
  status: string;
  provider: string;
  amount_usd: number;
  created_at: string;
}

export interface ClientReferral {
  code: string;
  /** Arrivals at the bot through this person's link — see the mini-app tile of the same name. */
  link_opens: number;
  attached: number;
  balance_usd: number;
}

export interface ClientRequest {
  id: string;
  status: string;
  subject: string;
  created_at: string;
}

export interface ConversationMessage {
  id: string;
  /** "in" = client → bot, "out" = operator → client. */
  direction: "in" | "out";
  text: string;
  /** Display name of the operator who sent an "out" message; null for "in". */
  admin: string | null;
  /** An "out" message written by the AI assistant rather than a person or the canned ack. */
  via_ai: boolean;
  created_at: string;
}

export interface ClientDossier {
  profile: Client;
  tos: ClientTos;
  accesses: ClientAccess[];
  orders: ClientOrder[];
  referral: ClientReferral | null;
  requests: ClientRequest[];
  messages: ConversationMessage[];
}

export interface PoolCarrierAvailability {
  carrier: string;
  free: number;
}

/** A city that can be issued from right now. Only cities with something free are
 *  returned, so an empty list means the pool has nothing to sell at all. */
export interface PoolLocation {
  id: string;
  city: string;
  state_code: string;
  free: number;
  carriers: PoolCarrierAvailability[];
}

/** One state and the city it is sold as. The state is the key — one city per state. */
export interface StateCity {
  state_code: string;
  city: string;
  /** Phones whose name declares this state right now. Zero is legitimate: a row can be
   *  prepared before the batch it covers arrives. */
  connections: number;
  updated_at: string | null;
}

export interface StateCityList {
  items: StateCity[];
  /** States already written into phone names with no city mapped — what the pool is asking
   *  the operator for. Sorted by how many phones each one covers. */
  unmapped: { state_code: string; connections: number }[];
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
  duration_minutes: number;
  max_user_swaps: number;
  is_active: boolean;
}

export type TariffInput = Omit<Tariff, "id">;

// ---------- Locations (cities) ----------

export interface Location {
  id: string;
  city: string;
  state_code: string;
  is_active: boolean;
  sort_order: number;
  /** How many connections currently have this location assigned — drives the delete guard:
   *  a location with any connections on it can only be deactivated, not deleted. */
  connections_count: number;
}

export type LocationInput = Omit<Location, "id" | "connections_count">;

// ---------- Pool / Connections ----------

export interface Connection {
  id: string;
  external_id: string;
  /** What this connection is sold as — resolved server-side from location_id, which
   *  sync_pool re-resolves from iproxy's reported city on every pass. state can be "" for
   *  a city outside the known state map; render it as absent, not a dangling ", ". */
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
  /** Proxy-accesses on this phone in iproxy that we did not issue — created by hand in
   *  the iproxy console. Non-zero means occupied even when slots_used is 0. */
  external_holds: number;
  /** Order number this phone is held for while its invoice is unpaid, or null. */
  reserved_for_order: number | null;
  external_checked_at: string | null;
  last_rotated_at: string | null;
}

export interface ConnectionUpdate {
  is_sellable?: boolean;
  tier?: string;
  location_id?: string | null;
  carrier?: string;
  health_note?: string;
}

/** The three buckets always add up to slots_total — see pool_summary on the backend. */
export interface PoolCitySummary {
  city: string;
  state: string;
  carrier: string;
  slots_total: number;
  slots_used: number;
  /** Sellable, online, nothing on it — what can be handed out right now. */
  nodes_free: number;
  /** An access is live on it. */
  nodes_busy: number;
  /** Held by an access made in the iproxy console. */
  nodes_held: number;
  nodes_reserved: number;
  /** Offline, silent, or withheld by an operator. */
  nodes_unavailable: number;
}

export interface PoolSummary {
  slots_total: number;
  slots_used: number;
  slots_free: number;
  /** Occupied by a proxy-access created inside the iproxy console rather than sold by us.
   *  Its own bucket: releasing it means going into iproxy, not anything in this console. */
  slots_held: number;
  slots_reserved: number;
  slots_unavailable: number;
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
  /** The iproxy connection serving this access — the id an operator pastes into the
   *  iproxy console, plus the phone's name as shown in the pool. */
  connection_id: string | null;
  connection_name: string | null;
  /** Minutes between scheduled rotations; null means off. Set from the actions column. */
  auto_rotate_minutes: number | null;
  /** Why the access ended and who ended it. `revoked_at` is also stamped on expiry, so a
   *  null reason there means time ran out rather than somebody deciding. */
  revoked_at: string | null;
  revoke_reason: string | null;
  revoked_by: string | null;
  tariff_code: string;
  /** The order this access was bought with. The number is what an operator reads and
   * types; the id is what actions take. Null only if the order row is somehow gone. */
  order_number: number | null;
  order_public_id: string | null;
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
  /** Sequential, human-quotable. `id` stays the UUID every action takes. */
  number: number;
  user: string;
  status: string;
  provider: string;
  amount_usd: number;
  /** Which plan, and how many of it — the amount alone does not say. */
  tariff_code: string;
  quantity: number;
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

// ---------- On-chain deposit ledger (append-only) ----------

export interface DepositCandidate {
  order_number: number;
  order_public_id: string;
  order_status: string;
  invoice_status: string;
  user: string;
  amount_usd: number;
  crypto_amount: string | null;
  /** How far this order's quote is from what actually arrived. "0" = exact. */
  difference: string | null;
  created_at: string | null;
}

export interface DepositCandidates {
  deposit_amount: string;
  asset: string;
  candidates: DepositCandidate[];
}

/** An invoice raised for an order, whether or not money ever arrived for it.
 *
 *  The deposit ledger answers "what came in"; this answers "what is owed", which is the
 *  question an operator could previously only reach by opening clients one at a time. */
export interface InvoiceRow {
  id: string;
  order_number: number;
  order_public_id: string;
  user: string | null;
  /** Invoice status: created / pending / confirming / paid / expired / … */
  status: string;
  /** The order's own status — an invoice can be paid while provisioning is still running. */
  order_status: string;
  amount_usd: number;
  crypto_amount: number | null;
  crypto_currency: string | null;
  crypto_network: string | null;
  chain: string | null;
  pay_address: string | null;
  /** How many proxies the order buys — one invoice can cover several. */
  quantity: number;
  tariff_code: string;
  created_at: string;
  expires_at: string;
  paid_at: string | null;
}

export interface DepositLedgerEntry {
  id: string;
  /**
   * Whether this row is the deposit's current state rather than a historical snapshot.
   * The ledger is append-only: a row that once said "unmatched" says so forever, so
   * actions must key off this and not off the row's own status.
   */
  is_current: boolean;
  created_at: string;
  status: string;
  chain: string;
  asset: string;
  network: string;
  txid: string;
  log_index: number;
  from_address: string | null;
  to_address: string;
  amount: string;
  amount_usd: number | null;
  confirmations: number;
  block_number: number | null;
  invoice_id: string | null;
  /**
   * The order the buyer sees, resolved from the invoice. This — not `invoice_id` — is
   * what a customer quotes, what the Orders screen searches by, and what the resolve
   * dialog accepts.
   */
  order_public_id: string | null;
  /** The same order, as an operator refers to it. */
  order_number: number | null;
  user: string | null;
  user_id: string | null;
}

export interface DepositLedgerSummary {
  by_status: Record<string, number>;
  events_24h: number;
  unmatched_total: number;
}

// ---------- Wallets ----------

export interface PaymentRail {
  asset: string;
  network: string;
  chain: string;
  /** The address a customer's payment lands on. Empty = this coin is not accepted. */
  address: string;
  confirmations: number;
  /** Contract (EVM/Tron) or mint (Solana); null for native coins. */
  token_contract: string | null;
  is_stablecoin: boolean;
}

/** A wallet we SEND referral payouts from. Not a receiving address — it is watched so
 * a payout an operator sends by hand gets its real transaction hash attached
 * automatically. Three rails, fixed: USDT on TRC-20, ERC-20, BEP-20. */
export interface PayoutWallet {
  network: string;
  chain: string;
  asset: string;
  /** "USDT TRC-20 (Tron)" — the full rail name, as the payout instructions show it. */
  label: string;
  address: string;
}

export interface PaymentRails {
  provider: string;
  network: string;
  /** False when PAYMENT_PROVIDER is not "onchain" — the addresses exist but nothing
   * is watching them, which the page has to say out loud. */
  watching: boolean;
  /** False while ONCHAIN_METHODS in the deploy environment is still in charge; the
   * first save from this screen takes over from it. */
  console_managed: boolean;
  supported_count: number;
  /** Every rail the watcher has an engine for, configured or not. */
  rails: PaymentRail[];
  payout_wallets: PayoutWallet[];
  /** Set when the stored rail list itself is malformed. */
  error: string | null;
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

export interface RequestDetail extends SupportRequest {
  type?: string;
  body: string;
  comments: RequestComment[];
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
  /** The referrer's code — the thing the search box accepts, now also visible. */
  referral_code: string;
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
  network: string;
  wallet_address: string;
  tx_hash: string | null;
}

/** Everything needed to send a payout by hand without retyping anything. */
export interface PayoutInstruction {
  payout_id: string;
  status: string;
  asset: string;
  network: string;
  network_label: string;
  to_address: string;
  amount: string;
  token_contract: string | null;
  /** EIP-681 link that opens an EVM wallet prefilled; null on Tron (no such standard). */
  wallet_uri: string | null;
  qr_payload: string;
  auto_confirm: boolean;
  hint: string;
}

export interface ReferralSettings {
  // field names must match the backend contract (GET/PATCH /settings/referral) exactly —
  // extra keys are silently dropped by the Pydantic model, so a mismatch saves nothing
  referral_pct: number;
  referral_min_payout_usd: number;
  referral_hold_days: number;
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

/** Body for registering a Telegram channel (matches the backend POST /channels). */
export interface ChannelCreateInput {
  tg_chat_id: number;
  title: string;
  username?: string;
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
  /** Shown as a card in the mini app's FAQ. */
  is_published: boolean;
  /** Given to the support assistant, which treats it as authoritative. Independent of
   *  is_published: an answer can go to one, the other, or both. */
  use_in_bot: boolean;
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

/** Response to a welcome-image upload — see systemApi.uploadWelcomeImage. */
export interface WelcomeImageUploadResult {
  content_type: string;
  size_bytes: number;
  updated_at: string;
}

export interface TermsQuestion {
  /** Stable key the answer is stored under; renaming one orphans past answers. */
  id: string;
  /** What the client reads above the field. The mini-app renders `label` — the admin
   * used to call this `text`, so a question added here reached the client blank. */
  label: string;
  /** `email` is format-checked on both sides; anything else is free text. */
  type: "text" | "email";
  required: boolean;
}

export interface Terms {
  /** Bumped only by Publish. Clients must re-accept when it changes. */
  version: number;
  /** The agreement itself, Markdown, rendered by the mini-app above the questions. */
  text_md: string;
  questions: TermsQuestion[];
}

export interface TermsInput {
  text_md: string;
  questions: TermsQuestion[];
  /** True bumps the version and puts every client back through the gate. */
  publish?: boolean;
}

export interface AdminAccount {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  /** The handle the owner wrote down. Where sign-in codes are meant to go. */
  telegram_username: string | null;
  /** Whether that handle has an inbox behind it yet — true only once the person has
   * opened the bot, which is the only way a bot may write to a private user. */
  telegram_linked: boolean;
}

export interface AdminAccountInput {
  email: string;
  display_name: string;
  password?: string;
  telegram_username?: string | null;
}

export interface AuditLogEntry {
  id: string;
  admin: string;
  entity: string;
  action: string;
  created_at: string;
}
