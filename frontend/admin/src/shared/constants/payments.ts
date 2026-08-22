// Shared payment constants. LedgerScreen and InvoicesPanel both filter by
// chain and asset, and the two copies had already drifted once before; one
// source of truth keeps them identical and makes a new rail a one-line change.
//
// Only the truly duplicated arrays live here — per-screen status lists stay
// where they are, because the statuses a deposit can be in and the ones an
// invoice can be in are genuinely different sets.

/** Blockchains the watcher can observe deposits on. */
export const CHAINS = ["tron", "ethereum", "bsc", "solana", "bitcoin", "litecoin"];

/** Coins that can be paid into a receiving wallet. */
export const ASSETS = ["USDT", "USDC", "TRX", "ETH", "BNB", "SOL", "BTC", "LTC"];