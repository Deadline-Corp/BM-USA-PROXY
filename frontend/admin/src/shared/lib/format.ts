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

export function initials(name: string | null | undefined): string {
  if (!name) return "—";
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "—";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}
