// Thin REST client for the dashboard's non-streaming reads.
import type { Metrics } from "./types";

export async function fetchMetrics(): Promise<Metrics> {
  const r = await fetch("/api/metrics");
  return r.json();
}

export async function fetchLedger(limit = 100) {
  const r = await fetch(`/api/ledger?limit=${limit}`);
  return r.json();
}
