// Shared types for the dashboard — mirror the backend broadcast frame.

export type RouteState = "HEALTHY" | "DEGRADING" | "DOWN" | "RECOVERING";
export type FailureClass = "TD" | "BD" | "UNKNOWN";
export type Action = "RETRY" | "LINK" | "HOLD" | "STOP";

export interface PipelineFrame {
  type: "pipeline_event";
  event: {
    event_id: string;
    transaction_id: string;
    amount: number; // paise
    route: string;
    status: string;
    error_code: string | null;
    source: string;
    received_at: string;
  };
  classification: { class: FailureClass; is_soft: boolean; reason: string } | null;
  health: {
    route: string;
    state: RouteState;
    previous_state: RouteState;
    failure_rate: number;
    samples: number;
    changed: boolean;
  };
  decision: {
    action: Action;
    rule_fired: string;
    reason: string;
    attempt_number: number;
    route_state: RouteState;
  } | null;
  outcome: { result: string; amount_recovered: number; detail: string } | null;
  outreach: { body: string; generated_by: string; channel: string } | null;
  diagnosis: {
    route: string;
    state: RouteState;
    body: string;
    generated_by: string;
    failure_rate: number;
    sample_size: number;
  } | null;
  escalation: {
    transaction_id: string;
    body: string;
    generated_by: string;
  } | null;
}

export interface Metrics {
  total_events: number;
  recoverable: number;
  recovered: number;
  recovery_rate: number;
  rupees_rescued: number;
  retries_fired: number;
  retries_avoided_degraded: number;
  wasted_retries_avoided: number;
  links_issued: number;
  unrecoverable: number;
}
