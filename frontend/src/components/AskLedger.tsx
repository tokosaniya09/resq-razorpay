import { useState } from "react";
import { askLedger, type AskResponse } from "../lib/api";

// "Ask the ledger" — type a plain-English question; the backend answers from
// the recorded audit trail only. Read-only: it explains, never changes anything.
const SUGGESTIONS = [
  "How much did we rescue, and how many risky retries did we avoid?",
  "Why did we hold payments during the outage?",
  "Which rail is least reliable right now?",
  "How many payments were unrecoverable and why?",
];

export function AskLedger() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AskResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const run = async (question: string) => {
    const query = question.trim();
    if (!query || busy) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(await askLedger(query));
    } catch {
      setErr("Couldn't reach the backend. Is it running on :8000?");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-line bg-ink-800">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <span className="rounded bg-rescued/15 px-1.5 py-0.5 font-mono text-[10px] font-medium text-rescued">
          ASK THE LEDGER
        </span>
        <span className="text-xs text-fg-muted">
          plain-English questions, answered from the audit trail
        </span>
      </div>

      <div className="p-3">
        <div className="flex gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run(q)}
            placeholder="e.g. how much did we rescue during the outage?"
            className="min-w-0 flex-1 rounded-md border border-line bg-ink-900 px-3 py-2 font-mono text-sm text-fg placeholder:text-fg-faint focus:border-rescued/50 focus:outline-none"
          />
          <button
            onClick={() => run(q)}
            disabled={busy || !q.trim()}
            className="shrink-0 rounded-md border border-rescued/40 bg-rescued/10 px-3 py-2 text-sm font-medium text-rescued disabled:opacity-40"
          >
            {busy ? "…" : "Ask"}
          </button>
        </div>

        <div className="mt-2 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => {
                setQ(s);
                run(s);
              }}
              className="rounded border border-line bg-ink-700 px-2 py-1 text-left text-[11px] text-fg-muted hover:bg-ink-600"
            >
              {s}
            </button>
          ))}
        </div>

        {err && <p className="mt-3 text-xs text-down">{err}</p>}

        {res && !err && (
          <div className="row-in mt-3 rounded-md border border-line bg-ink-700 p-3">
            <p className="text-sm leading-relaxed text-fg">{res.answer}</p>
            <div className="mt-2 flex items-center gap-2">
              <span className="rounded bg-ink-600 px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
                {res.generated_by}
              </span>
              <span className="font-mono text-[10px] text-fg-faint">
                answered only from recorded ledger facts
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
