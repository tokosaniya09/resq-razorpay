import type { PipelineFrame, RouteState } from "../lib/types";
import { RouteHealthTrack } from "../components/RouteHealthTrack";
import { ClassBadge, ActionBadge } from "../components/StatusBadge";
import { shortId } from "../lib/format";

// Center pane — the brain. Route-health state machine on top (the differentiator),
// then the classify -> decide chain lighting up per event.
export function DecisionPipeline({
  frames,
  routes,
  diagnoses,
}: {
  frames: PipelineFrame[];
  routes: Record<string, { state: RouteState; failure_rate: number; samples: number }>;
  diagnoses: Record<string, PipelineFrame["diagnosis"]>;
}) {
  const activeDiagnoses = Object.values(diagnoses).filter(
    (d) => d && (d.state === "DEGRADING" || d.state === "DOWN")
  );
  const anyDown = Object.values(routes).some((r) => r.state === "DOWN");
  return (
    <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-ink-800">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="text-sm font-semibold">Decision pipeline</h2>
        <span className="font-mono text-xs text-fg-muted">
          classify → detect → decide
        </span>
      </header>

      {/* Route health stays pinned — it's the signature element. */}
      <div className="max-h-[42%] shrink-0 space-y-2 overflow-y-auto border-b border-line p-3">
        {Object.keys(routes).length === 0 && (
          <p className="text-sm text-fg-faint">Route health appears here.</p>
        )}
        {Object.entries(routes).map(([route, r]) => (
          <RouteHealthTrack
            key={route}
            route={route}
            state={r.state}
            failureRate={r.failure_rate}
            samples={r.samples}
          />
        ))}
      </div>

      {/* Everything below scrolls together, so it can never overflow the pane. */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {activeDiagnoses.map((d) => (
          <div
            key={d!.route}
            className="border-b border-recovering/30 bg-recovering/5 px-4 py-2.5"
          >
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <span className="rounded bg-recovering/15 px-1.5 py-0.5 font-mono text-[10px] font-medium text-recovering">
                AI ROOT-CAUSE
              </span>
              <span className="font-mono text-[10px] text-fg-faint">
                {d!.route} · {d!.generated_by} · n={d!.sample_size}
              </span>
            </div>
            <p className="text-xs leading-relaxed text-fg-muted break-words">
              {d!.body}
            </p>
          </div>
        ))}

        {anyDown && (
          <div className="pulse-down border-b border-down/40 bg-down/10 px-4 py-2 text-xs text-down">
            Rail DOWN — retries suspended. Holding technical failures to prevent
            duplicate charges; will drain when healthy.
          </div>
        )}

        {frames
          .filter((f) => f.event.status === "failed")
          .map((f) => (
            <div
              key={f.event.event_id}
              className="row-in border-b border-line/60 px-4 py-2.5"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] text-fg-faint">
                  {shortId(f.event.transaction_id)}
                </span>
                <div className="flex items-center gap-1.5">
                  <ClassBadge c={f.classification.class} />
                  <span className="text-fg-faint">→</span>
                  <ActionBadge action={f.decision.action} />
                </div>
              </div>
              <p className="mt-1 text-xs text-fg-muted">{f.decision.reason}</p>
              <div className="mt-1 font-mono text-[10px] text-fg-faint">
                {f.decision.rule_fired}
              </div>
            </div>
          ))}
      </div>
    </section>
  );
}
