import type { PipelineFrame } from "../lib/types";
import { rupees, shortId, clock } from "../lib/format";

// Left pane — raw incoming payment failures as they arrive.
export function EventStream({ frames }: { frames: PipelineFrame[] }) {
  return (
    <section className="flex min-h-0 flex-col rounded-lg border border-line bg-ink-800">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="text-sm font-semibold">Event stream</h2>
        <span className="font-mono text-xs text-fg-muted">
          {frames.length} events
        </span>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {frames.length === 0 && (
          <p className="p-4 text-sm text-fg-faint">
            Waiting for events. Start the generator to see the stream.
          </p>
        )}
        {frames.map((f) => {
          const failed = f.event.status === "failed";
          return (
            <div
              key={f.event.event_id}
              className="row-in border-b border-line/60 px-4 py-2.5"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-fg">
                  {f.event.route}
                </span>
                <span
                  className={`font-mono text-xs ${
                    failed ? "text-down" : "text-healthy"
                  }`}
                >
                  {f.event.status}
                </span>
              </div>
              <div className="mt-1 flex items-center justify-between">
                <span className="font-mono text-xs text-fg-muted">
                  {f.event.error_code ?? "—"}
                </span>
                <span className="font-mono text-xs text-fg-muted">
                  {rupees(f.event.amount)}
                </span>
              </div>
              <div className="mt-0.5 flex items-center justify-between">
                <span className="font-mono text-[11px] text-fg-faint">
                  {shortId(f.event.transaction_id)}
                </span>
                <span className="font-mono text-[11px] text-fg-faint">
                  {clock(f.event.received_at)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
