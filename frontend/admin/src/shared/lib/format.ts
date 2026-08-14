export function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}

/**
 * Render an on-chain amount for humans. The API sends the ledger's full
 * NUMERIC(38,18) precision as a string ("31.500000000000000000") so no value is
 * ever lost in transit; operators only need the significant digits. Kept as
 * string maths — parseFloat would silently round large/precise amounts.
 */
export function formatCryptoAmount(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  if (!/^-?\d+(\.\d+)?$/.test(value)) return value; // unexpected shape — show as-is
  if (!value.includes(".")) return value;
  const trimmed = value.replace(/0+$/, "").replace(/\.$/, "");
  return trimmed === "" || trimmed === "-" ? "0" : trimmed;
}

/**
 * Proper display names for chains and rails. A blanket CSS `capitalize` would
 * render "Bsc" and "Trc20" — these are acronyms, not words, so they need a map.
 * Unknown values fall back to first-letter-uppercase rather than disappearing.
 */
const CHAIN_LABELS: Record<string, string> = {
  tron: "Tron",
  ethereum: "Ethereum",
  bsc: "BSC",
  solana: "Solana",
  bitcoin: "Bitcoin",
  litecoin: "Litecoin",
};

const NETWORK_LABELS: Record<string, string> = {
  trc20: "TRC-20",
  erc20: "ERC-20",
  bep20: "BEP-20",
  spl: "SPL",
  native: "native",
};

function titleCase(value: string): string {
  return value ? value[0].toUpperCase() + value.slice(1) : value;
}

export function formatChain(chain: string | null | undefined): string {
  if (!chain) return "—";
  return CHAIN_LABELS[chain.toLowerCase()] ?? titleCase(chain);
}

// ── audit log ────────────────────────────────────────────────────────────
// The log stores machine keys — `app_setting`, `access.revoke` — and used to print them
// raw, which asked the reader to parse punctuation to find out what happened. These turn
// a key into the sentence it stands for. Derived rather than looked up in a table of
// forty, so an action added on the backend tomorrow still reads as English.

/** Words that are shouted, not capitalised. */
const AUDIT_ACRONYMS: Record<string, string> = { ip: "IP", faq: "FAQ", tos: "ToS", url: "URL" };

/** Verbs the -ed rules would get wrong. */
const AUDIT_IRREGULAR: Record<string, string> = { send: "sent" };

/** Keys whose natural English reverses the order of the words in them. Every word here
 * still occurs in the key, so searching for what you can read still finds the row. */
const AUDIT_PHRASES: Record<string, string> = {
  "settings.referral.update": "Referral settings updated",
  "notifications.settings.update": "Notification settings updated",
};

const VOWELS = "aeiou";

/** `revoke` → revoked, `ban` → banned, `send` → sent. */
function pastTense(verb: string): string {
  if (verb in AUDIT_IRREGULAR) return AUDIT_IRREGULAR[verb];
  if (verb.endsWith("e")) return `${verb}d`;
  const tail = verb.slice(-3);
  // consonant-vowel-consonant doubles the last letter: ban → banned. `extend` and `mark`
  // are excluded by the vowel test on the first letter, which is what stops "extendded".
  if (
    tail.length === 3 &&
    !VOWELS.includes(tail[0]) &&
    VOWELS.includes(tail[1]) &&
    !VOWELS.includes(tail[2]) &&
    !"wxy".includes(tail[2])
  ) {
    return `${verb}${tail[2]}ed`;
  }
  return `${verb}ed`;
}

const auditWord = (word: string) => AUDIT_ACRONYMS[word] ?? word;

/** `app_setting` → "App setting". */
export function formatAuditEntity(entity: string | null | undefined): string {
  if (!entity) return "—";
  return titleCase(entity.split(/[._]/).map(auditWord).join(" "));
}

/** `access.revoke` → "Access revoked", `order.mark_paid` → "Order marked paid".
 *
 * Subject first, then the verb in the past — a record of something that happened, not an
 * instruction. The last dotted segment is the verb phrase; everything before it is what
 * the verb was done to.
 */
export function formatAuditAction(action: string | null | undefined): string {
  if (!action) return "—";
  if (action in AUDIT_PHRASES) return AUDIT_PHRASES[action];
  const segments = action.split(".");
  const verbPhrase = (segments.pop() ?? "").split("_");
  const verb = verbPhrase.shift() ?? "";
  const words = [
    ...segments.flatMap((s) => s.split("_")).map(auditWord),
    pastTense(verb),
    ...verbPhrase.map(auditWord),
  ].filter(Boolean);
  return titleCase(words.join(" "));
}

export function formatNetwork(network: string | null | undefined): string {
  if (!network) return "—";
  return NETWORK_LABELS[network.toLowerCase()] ?? network.toUpperCase();
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const diffMs = Date.now() - d.getTime();
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay}d ago`;
}

/**
 * "Boston, MA" — or just "Boston" when there is no state to show.
 *
 * sync_pool assigns every reported city a Location even when the city isn't in its state
 * lookup table, with state_code "" rather than null (Postgres would let a NULL state_code
 * duplicate an existing city, defeating the city+state uniqueness this is supposed to
 * have). "" reaching this far and being joined naively would print a dangling "Boston, ".
 */
export function formatCityState(city: string, stateCode: string): string {
  return stateCode ? `${city}, ${stateCode}` : city;
}

export function initials(name: string | null | undefined): string {
  if (!name) return "—";
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "—";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}
