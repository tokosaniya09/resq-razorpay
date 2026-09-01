import { useCallback, useEffect, useState } from "react";
import type { Metrics, PipelineFrame, RouteState } from "./lib/types";
import { useWebSocket } from "./hooks/useWebSocket";
import { fetchMetrics } from "./lib/api";
import { EventStream } from "./panes/EventStream";
import { DecisionPipeline } from "./panes/DecisionPipeline";
import { Outcomes } from "./panes/Outcomes";
import { StateBadge } from "./components/StatusBadge";
import { AskLedger } from "./components/AskLedger";

const EMPTY_METRICS: Metrics = {
  total_events: 0,
  recoverable: 0,
  recovered: 0,
  recovery_rate: 0,
  rupees_rescued: 0,
  retries_avoided_degraded: 0,
  wasted_retries_avoided: 0,
  links_issued: 0,
  unrecoverable: 0,
};

export default function App() {
  const [frames, setFrames] = useState<PipelineFrame[]>([]);
  const [routes, setRoutes] = useState<
    Record<string, { state: RouteState; failure_rate: number; samples: number }>
  >({});
  const [metrics, setMetrics] = useState<Metrics>(EMPTY_METRICS);
  const [diagnoses, setDiagnoses] = useState<Record<string, PipelineFrame["diagnosis"]>>({});
  const [escalations, setEscalations] = useState<NonNullable<PipelineFrame["escalation"]>[]>([]);

  const onFrame = useCallback((f: PipelineFrame) => {
    setFrames((prev) => [f, ...prev].slice(0, 200));
    setRoutes((prev) => ({
      ...prev,
      [f.health.route]: {
        state: f.health.state,
        failure_rate: f.health.failure_rate,
        samples: f.health.samples,
      },
    }));
    if (f.diagnosis) {
      setDiagnoses((prev) => ({ ...prev, [f.diagnosis!.route]: f.diagnosis }));
    }
    if (f.escalation) {
      setEscalations((prev) => [f.escalation!, ...prev].slice(0, 20));
    }
  }, []);

  const status = useWebSocket(onFrame);

  // Poll metrics (authoritative, from the persisted ledger).
  useEffect(() => {
    const tick = () => fetchMetrics().then(setMetrics).catch(() => {});
    tick();
    const id = setInterval(tick, 2000);
    return () => clearInterval(id);
  }, []);

  const worst = Object.values(routes).reduce<RouteState>((acc, r) => {
    const rank = { HEALTHY: 0, RECOVERING: 1, DEGRADING: 2, DOWN: 3 };
    return rank[r.state] > rank[acc] ? r.state : acc;
  }, "HEALTHY");

  return (
    <div className="flex h-screen flex-col bg-ink-900">
      <header className="flex items-center justify-between border-b border-line px-5 py-3">
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-lg font-semibold tracking-tight text-fg">
            ResQ<span className="text-rescued">·</span>Pay
          </span>
          <span className="text-xs text-fg-muted">
            payment-rail reliability console
          </span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-xs text-fg-muted">
            worst rail <StateBadge state={worst} />
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className={`h-2 w-2 rounded-full ${
                status === "open" ? "bg-healthy" : "bg-degrading"
              }`}
            />
            <span className="font-mono text-xs text-fg-muted">{status}</span>
          </div>
        </div>
      </header>

      <div className="px-3 pt-3">
        <AskLedger />
      </div>

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-3">
        <EventStream frames={frames} />
        <DecisionPipeline frames={frames} routes={routes} diagnoses={diagnoses} />
        <Outcomes frames={frames} metrics={metrics} escalations={escalations} />
      </main>

      <footer className="border-t border-line px-5 py-2 text-center font-mono text-[11px] text-fg-faint">
        Razorpay Test Mode · synthetic data · outreach generated, not delivered ·
        every money decision is deterministic and logged
      </footer>
    </div>
  );
}
