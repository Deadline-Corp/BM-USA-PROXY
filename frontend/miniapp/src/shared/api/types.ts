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
  crypto_amount: number | null;
  pay_address: string | null;
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
}

export interface OrderStatusResponse {
  status: OrderStatus;
  invoice_status: InvoiceStatus | null;
  access_public_id: string | null;
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

export interface Referral {
  code: string;
  signups: number;
  balances: ReferralBalances;
  min_payout_usd: number;
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
