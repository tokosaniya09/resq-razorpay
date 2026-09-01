"""Degradation detector — the differentiator (§6.3).

Most recovery tools look at one failed payment at a time. This looks at the
*health of the whole rail*. For each route/acquirer it keeps a rolling window
of recent outcomes and runs a small, explicit state machine:

    HEALTHY     normal handling
    DEGRADING   failure rate crossed the warning line -> be cautious
    DOWN        failure rate crossed the critical line -> STOP retrying
    RECOVERING  failures are dropping -> drain the hold queue gradually

Why a state machine and not a model: health decisions gate whether we fire
money into a rail. They must be predictable, explainable and tunable — never
probabilistic. Thresholds come from config so they can be tuned live in the
demo. Everything here is deterministic given the same event sequence.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

from app.core.config import Settings
from app.models.domain import PaymentEvent, RouteState, utcnow


@dataclass
class RouteWindow:
    """Rolling record of recent outcomes for a single route.

    Each entry is True for a failure, False for a success. We derive the
    failure rate from the window and never store more than `window_size`.
    """

    route: str
    window_size: int
    outcomes: deque[bool]
    state: RouteState = RouteState.HEALTHY
    entered_state_at: datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.entered_state_at is None:
            self.entered_state_at = utcnow()

    @property
    def samples(self) -> int:
        return len(self.outcomes)

    @property
    def failure_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(self.outcomes) / len(self.outcomes)


@dataclass(frozen=True)
class HealthSnapshot:
    route: str
    state: RouteState
    previous_state: RouteState
    failure_rate: float
    samples: int
    changed: bool
    at: datetime


class DegradationDetector:
    """Owns one RouteWindow per route and advances its state machine."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._routes: dict[str, RouteWindow] = {}

    # -- public API --------------------------------------------------------- #
    def observe(self, event: PaymentEvent) -> HealthSnapshot:
        """Record one event's outcome and return the (possibly new) health."""
        win = self._window_for(event.route)
        is_failure = event.status.lower() == "failed"
        win.outcomes.append(is_failure)

        previous = win.state
        new_state = self._next_state(win)
        changed = new_state != previous
        if changed:
            win.state = new_state
            win.entered_state_at = utcnow()

        return HealthSnapshot(
            route=event.route,
            state=win.state,
            previous_state=previous,
            failure_rate=round(win.failure_rate, 4),
            samples=win.samples,
            changed=changed,
            at=utcnow(),
        )

    def state_of(self, route: str) -> RouteState:
        win = self._routes.get(route)
        return win.state if win else RouteState.HEALTHY

    def snapshot_all(self) -> list[HealthSnapshot]:
        now = utcnow()
        return [
            HealthSnapshot(
                route=w.route,
                state=w.state,
                previous_state=w.state,
                failure_rate=round(w.failure_rate, 4),
                samples=w.samples,
                changed=False,
                at=now,
            )
            for w in self._routes.values()
        ]

    # -- internals ---------------------------------------------------------- #
    def _window_for(self, route: str) -> RouteWindow:
        if route not in self._routes:
            self._routes[route] = RouteWindow(
                route=route,
                window_size=self._s.degradation_window_size,
                outcomes=deque(maxlen=self._s.degradation_window_size),
            )
        return self._routes[route]

    def _next_state(self, win: RouteWindow) -> RouteState:
        """Explicit transition rules. Hysteresis prevents flapping: we only
        declare RECOVERING/HEALTHY once the rate has clearly dropped, and we
        require a dwell time before returning to full HEALTHY."""
        s = self._s
        rate = win.failure_rate

        # Not enough evidence yet -> stay healthy, don't overreact.
        if win.samples < s.degradation_min_samples:
            return RouteState.HEALTHY

        if rate >= s.degradation_critical_threshold:
            return RouteState.DOWN

        if rate >= s.degradation_warn_threshold:
            # Coming down from DOWN we pass through DEGRADING, not straight home.
            return RouteState.DEGRADING

        # Rate is now below the warning line.
        if win.state in (RouteState.DOWN, RouteState.DEGRADING):
            if rate <= s.recovering_threshold:
                # Low enough to start recovering — but dwell before HEALTHY.
                dwell = (utcnow() - win.entered_state_at).total_seconds()
                if (
                    win.state == RouteState.RECOVERING
                    and dwell >= s.recovering_drain_after_seconds
                ):
                    return RouteState.HEALTHY
                return RouteState.RECOVERING
            return RouteState.DEGRADING

        if win.state == RouteState.RECOVERING:
            dwell = (utcnow() - win.entered_state_at).total_seconds()
            if dwell >= s.recovering_drain_after_seconds:
                return RouteState.HEALTHY
            return RouteState.RECOVERING

        return RouteState.HEALTHY
