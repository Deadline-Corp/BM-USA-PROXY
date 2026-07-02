import type { Invoice } from "../api/types";

// GET /orders/{id} intentionally does not return invoice payment details
// (amount, crypto_amount, pay_address, expires_at) — only {status,
// invoice_status, access_public_id}. Those fields are only ever present in
// the POST /orders response. We cache them here, keyed by order public_id,
// so the Checkout screen survives a page reload mid-flow (sessionStorage
// rather than router state, which does not survive a reload).
const PREFIX = "bm_invoice_";

export function cacheInvoice(orderId: string, invoice: Invoice | null): void {
  if (!invoice) return;
  try {
    sessionStorage.setItem(`${PREFIX}${orderId}`, JSON.stringify(invoice));
  } catch {
    // sessionStorage unavailable (e.g. private mode edge cases) — non-fatal,
    // the checkout screen simply won't have amount/address to show.
  }
}

export function readCachedInvoice(orderId: string): Invoice | null {
  try {
    const raw = sessionStorage.getItem(`${PREFIX}${orderId}`);
    return raw ? (JSON.parse(raw) as Invoice) : null;
  } catch {
    return null;
  }
}
