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

export interface AskResponse {
  question: string;
  answer: string;
  generated_by: string;
  snapshot: unknown;
}

export async function askLedger(question: string): Promise<AskResponse> {
  const r = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!r.ok) throw new Error("ask failed");
  return r.json();
}
