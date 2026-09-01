import type { RouteState } from "../lib/types";
import { pct } from "../lib/format";

const ORDER: RouteState[] = ["HEALTHY", "DEGRADING", "DOWN", "RECOVERING"];
const DOT: Record<RouteState, string> = {
  HEALTHY: "bg-healthy",
  DEGRADING: "bg-degrading",
  DOWN: "bg-down",
  RECOVERING: "bg-recovering",
};

// The signature element: the rail-health state machine, one row per route.
// The active state is lit; the failure-rate bar shows how close it is to the
// next threshold. This is what turns "recovery bot" into "reliability controller".
export function RouteHealthTrack({
  route,
  state,
  failureRate,
  samples,
}: {
  route: string;
  state: RouteState;
  failureRate: number;
  samples: number;
}) {
  const barColor =
    state === "DOWN"
      ? "bg-down"
      : state === "DEGRADING"
      ? "bg-degrading"
      : state === "RECOVERING"
      ? "bg-recovering"
      : "bg-healthy";
  return (
    <div className="rounded-md border border-line bg-ink-700 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-sm text-fg">{route}</span>
        <span className="font-mono text-xs text-fg-muted">
          {pct(failureRate)} fail · n={samples}
        </span>
      </div>
      <div className="mb-2 h-1.5 w-full overflow-hidden rounded bg-ink-900">
        <div
          className={`h-full ${barColor} transition-all duration-500`}
          style={{ width: `${Math.min(100, failureRate * 100)}%` }}
        />
      </div>
      <div className="flex items-center gap-1">
        {ORDER.map((s) => {
          const active = s === state;
          return (
            <div key={s} className="flex flex-1 items-center gap-1">
              <span
                className={`h-2 w-2 rounded-full ${
                  active ? DOT[s] : "bg-ink-600"
                }`}
              />
              <span
                className={`font-mono text-[10px] ${
                  active ? "text-fg" : "text-fg-faint"
                }`}
              >
                {s}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
