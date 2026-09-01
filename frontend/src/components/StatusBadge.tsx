import type { Action, FailureClass, RouteState } from "../lib/types";

const STATE_COLOR: Record<RouteState, string> = {
  HEALTHY: "text-healthy border-healthy/40 bg-healthy/10",
  DEGRADING: "text-degrading border-degrading/40 bg-degrading/10",
  DOWN: "text-down border-down/40 bg-down/10",
  RECOVERING: "text-recovering border-recovering/40 bg-recovering/10",
};

const ACTION_COLOR: Record<Action, string> = {
  RETRY: "text-recovering border-recovering/40 bg-recovering/10",
  LINK: "text-rescued border-rescued/40 bg-rescued/10",
  HOLD: "text-degrading border-degrading/40 bg-degrading/10",
  STOP: "text-fg-muted border-line bg-ink-600",
};

const CLASS_COLOR: Record<FailureClass, string> = {
  TD: "text-recovering border-recovering/40 bg-recovering/10",
  BD: "text-degrading border-degrading/40 bg-degrading/10",
  UNKNOWN: "text-fg-muted border-line bg-ink-600",
};

function Badge({ label, cls }: { label: string; cls: string }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-mono font-medium border ${cls}`}
    >
      {label}
    </span>
  );
}

export const StateBadge = ({ state }: { state: RouteState }) => (
  <Badge label={state} cls={STATE_COLOR[state]} />
);
export const ActionBadge = ({ action }: { action: Action }) => (
  <Badge label={action} cls={ACTION_COLOR[action]} />
);
export const ClassBadge = ({ c }: { c: FailureClass }) => (
  <Badge label={c} cls={CLASS_COLOR[c]} />
);
