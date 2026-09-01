import type { Metrics, PipelineFrame } from "../lib/types";
import { MetricStat } from "../components/MetricStat";
import { rupees, pct } from "../lib/format";

// Right pane — outcomes, live metrics, audit ledger, and simulated outreach.
export function Outcomes({
  frames,
  metrics,
  escalations,
}: {
  frames: PipelineFrame[];
  metrics: Metrics;
  escalations: NonNullable<PipelineFrame["escalation"]>[];
}) {
  const outreach = frames.filter((f) => f.outreach).slice(0, 6);
  return (
    <section className="flex min-h-0 flex-col rounded-lg border border-line bg-ink-800">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="text-sm font-semibold">Outcomes</h2>
        <span className="font-mono text-xs text-fg-muted">vs naive baseline</span>
      </header>

      <div className="grid grid-cols-2 gap-2 border-b border-line p-3">
        <MetricStat
          label="₹ Rescued"
          value={rupees(metrics.rupees_rescued * 100)}
          accent="text-rescued"
          sub={`${metrics.recovered} captured on re-attempt`}
        />
        <MetricStat
          label="Risky retries avoided"
          value={String(metrics.retries_avoided_degraded)}
          accent="text-healthy"
          sub="held while rail unhealthy"
        />
        <MetricStat
          label="Retry success"
          value={
            metrics.retries_fired > 0
              ? pct(metrics.recovered / metrics.retries_fired)
              : "—"
          }
          accent="text-healthy"
          sub={`${metrics.recovered}/${metrics.retries_fired} retries captured`}
        />
        <MetricStat
          label="Links issued"
          value={String(metrics.links_issued)}
          accent="text-recovering"
          sub={`${metrics.unrecoverable} unrecoverable`}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <div className="mb-2 text-[11px] uppercase tracking-wide text-fg-muted">
          Outreach (simulated — generated, not delivered)
        </div>
        {outreach.length === 0 && (
          <p className="text-sm text-fg-faint">
            Messages appear when a recovery link is issued.
          </p>
        )}
        <div className="space-y-2">
          {outreach.map((f) => (
            <div
              key={f.event.event_id}
              className="row-in rounded-md border border-line bg-ink-700 p-3"
            >
              <p className="text-sm text-fg">{f.outreach!.body}</p>
              <div className="mt-1.5 flex items-center gap-2">
                <span className="rounded bg-ink-600 px-1.5 py-0.5 font-mono text-[10px] text-fg-muted">
                  {f.outreach!.generated_by}
                </span>
                <span className="font-mono text-[10px] text-fg-faint">
                  {f.event.route}
                </span>
              </div>
            </div>
          ))}
        </div>

        {escalations.length > 0 && (
          <>
            <div className="mb-2 mt-4 text-[11px] uppercase tracking-wide text-fg-muted">
              AI escalation notes (unrecovered → for merchant ops)
            </div>
            <div className="space-y-2">
              {escalations.slice(0, 5).map((e, i) => (
                <div
                  key={e.transaction_id + i}
                  className="row-in rounded-md border border-degrading/30 bg-degrading/5 p-3"
                >
                  <p className="text-sm text-fg">{e.body}</p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <span className="rounded bg-degrading/15 px-1.5 py-0.5 font-mono text-[10px] text-degrading">
                      {e.generated_by}
                    </span>
                    <span className="font-mono text-[10px] text-fg-faint">
                      {e.transaction_id}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
