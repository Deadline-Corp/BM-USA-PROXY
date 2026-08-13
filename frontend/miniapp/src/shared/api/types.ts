// Types mirroring the /api/twa contract exactly.
// Verified against backend/app/api/twa/router.py and backend/app/services/*.py.

export type Carrier = "AT&T" | "T-Mobile" | "Verizon";

// ── /me ──────────────────────────────────────────────────────────────────
export interface Me {
  tg_user_id: number;
  first_name: string;
  active_accesses: number;
  referral: {
    code: string;
    available_usd: number;
  };
  trial_available: boolean;
  tos_accepted: boolean;
}

// ── /catalog ─────────────────────────────────────────────────────────────
export interface Tariff {
  code: string;
  name: string;
  description: string;
  duration_minutes: number;
  price_usd: number;
  max_user_swaps: number;
}

export interface LocationFree {
  "AT&T": number;
  "T-Mobile": number;
  Verizon: number;
  any: number;
}

export interface CatalogLocation {
  id: number;
  city: string;
  state_code: string;
  free: LocationFree;
}

export interface Catalog {
  tariffs: Tariff[];
  carriers: Carrier[];
  locations: CatalogLocation[];
  any_city_free: LocationFree;
  trial_available: boolean;
}

// ── /orders ──────────────────────────────────────────────────────────────
export type OrderStatus =
  | "awaiting_payment"
  | "confirming"
  | "provisioning"
  | "completed"
  | "expired"
  | "manual_review"
  | "cancelled";

export type InvoiceStatus = string;

export interface Invoice {
  provider: string;
  status: InvoiceStatus;
  amount_usd: number;
  crypto_currency: string | null;
  crypto_network: string | null;
  /**
   * Exact quoted amount as a STRING. The watcher matches a payment by this value to the
   * last digit, so it must never round-trip through a JS number: BTC/ETH/LTC are quoted
   * to 8 decimals and used to lose their tail, leaving the buyer paying an amount that
   * could never match.
   */
  crypto_amount: string | null;
  pay_address: string | null;
  /** Wallet deep link for the QR (EIP-681 / BIP-21 / Solana Pay), or the bare address. */
  pay_uri: string | null;
  /**
   * An https URL that redirects into `pay_uri`. Null where the chain has no deep link at
   * all. Inside Telegram this is the only usable target: the WebView cannot navigate to a
   * wallet scheme, but the client can open this in a real browser, which can.
   */
  pay_open_url: string | null;
  payment_url: string | null;
  expires_at: string;
}

export interface OrderSummary {
  public_id: string;
  status: OrderStatus;
  amount_usd: number;
}

export interface CreateOrderResponse {
  order: OrderSummary;
  invoice: Invoice | null;
}

export interface CreateOrderBody {
  tariff_code: string;
  location_id?: number;
  carrier?: Carrier | "any";
  /** Rail to quote the invoice in; omitted falls back to the server's first rail. */
  asset?: string;
  network?: string;
}

export interface OrderStatusResponse {
  status: OrderStatus;
  invoice_status: InvoiceStatus | null;
  access_public_id: string | null;
  /** Payment details, so checkout survives a reload or a reopened mini app. */
  invoice: Invoice | null;
}

/** An order still in flight — shown on Home so an unpaid one is never lost. */
export interface ActiveOrder {
  public_id: string;
  status: OrderStatus;
  tariff_code: string;
  amount_usd: number;
  created_at: string | null;
  invoice: Invoice | null;
}

export interface ActiveOrdersResponse {
  orders: ActiveOrder[];
}

/** A rail the buyer may pay on. Order matches the server's configured order. */
export interface PaymentMethod {
  asset: string;
  network: string;
  chain: string;
  /** "Tron", "BNB Chain (BSC)" — what the first dropdown shows. */
  chain_label: string;
  /** "USDT — TRC-20", "BTC — native coin" — what the second dropdown shows. */
  coin_label: string;
  label: string;
  min_amount_usd: number;
}

export interface PaymentMethodsResponse {
  methods: PaymentMethod[];
}

// ── /accesses ────────────────────────────────────────────────────────────
export type AccessStatus =
  | "provisioning"
  | "active"
  | "expiring"
  | "expired"
  | "cancelled"
  | string;

export interface AccessSummary {
  public_id: string;
  tariff_code: string;
  status: AccessStatus;
  city: string | null;
  state_code: string | null;
  carrier: string | null;
  expires_at: string | null;
  rotations_count: number;
}

export interface AccessesResponse {
  active: AccessSummary[];
  history: AccessSummary[];
}

export interface AccessCredentials {
  host: string | null;
  http_port: number | null;
  socks5_port: number | null;
  login: string | null;
  password: string | null;
}

export type ConfigType = "ovpn" | "wg";

export interface AccessDetail extends AccessSummary {
  current_ip: string | null;
  credentials: AccessCredentials;
  swap_left: number;
  configs_available: ConfigType[];
}

export interface SwapBody {
  location_id?: number;
  carrier?: Carrier | "any";
}

export interface SwapResponse {
  status: "swapped";
  swap_left: number;
}

export interface ExtendBody {
  tariff_code: string;
}

export interface ConfigBody {
  type: ConfigType;
}

export interface ConfigResponse {
  status: "sending";
}

// ── /referral ────────────────────────────────────────────────────────────
export interface ReferralBalances {
  hold: number;
  available: number;
  requested: number;
  paid: number;
}

/** A rail we actually pay out on — the form is built from these, never hardcoded. */
export interface PayoutRail {
  network: string;
  asset: string;
  /** Full "USDT TRC-20 (Tron)" — used where coin and network are named together. */
  label: string;
  /** Network alone, "Tron (TRC-20)" — the payout form asks for it by itself. */
  network_label: string;
}

export interface Referral {
  code: string;
  /** Arrivals at the bot through this link — including people we could not bind, which is
   *  exactly what makes it different from `signups`. */
  link_opens: number;
  signups: number;
  balances: ReferralBalances;
  min_payout_usd: number;
  /** Commission rate the ledger applies — operator-editable, so the copy reads it. */
  pct: number;
  payout_rails: PayoutRail[];
}

export interface ReferralPayoutBody {
  wallet_address: string;
  network: string;
}

export interface ReferralPayoutResponse {
  status: string;
}

// ── /faq ─────────────────────────────────────────────────────────────────
export interface FaqItem {
  category: string;
  question: string;
  answer: string;
}

// ── /requests ────────────────────────────────────────────────────────────
export type RequestType = "reseller" | "support" | "custom";

export interface RequestItem {
  id: number;
  type: RequestType;
  subject: string;
  status: string;
}

export interface NewRequestBody {
  type: RequestType;
  subject: string;
  body: string;
}

export interface CreateRequestResponse {
  id: number;
  status: string;
}

// ── /terms ───────────────────────────────────────────────────────────────
export interface TermsQuestion {
  id: string;
  label: string;
  type: string;
  required: boolean;
}

export interface Terms {
  version: number;
  text_md: string;
  questions: TermsQuestion[];
}

export interface AcceptTermsBody {
  version: number;
  answers: Record<string, string>;
}

export interface AcceptTermsResponse {
  accepted: boolean;
}

// ── API error shape ──────────────────────────────────────────────────────
// The backend renders domain errors as `{ error: { code, message } }`; FastAPI's
// own validation errors use `detail`. Both are modelled here so the client can read
// either, and detect specific codes (e.g. `account_banned`).
export interface ApiErrorBody {
  error?: { code?: string; message?: string };
  detail?: string | { message?: string } | Array<{ msg?: string }>;
  message?: string;
}
