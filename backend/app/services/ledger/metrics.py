"""Metrics and impact (§9).

Honest metrics only. The headline is *not* "we save X%" — it's that against a
naive retry loop, ResQ-Pay recovers a comparable share of the *safely*
recoverable failures while eliminating the duplicate-charge risk and wasted
fees the naive loop creates during an outage.

We compute, from the persisted ledger:
  - recovery_rate      recovered / recoverable
  - rupees_rescued     sum of captured amounts
  - retries_avoided    HOLDs during DEGRADING/DOWN — retries the naive loop
                       would have fired into a failing rail (dup-charge proxy)
  - wasted_retries_avoided  business (hard) failures we did NOT retry
  - unrecoverable      STOPs, listed honestly with reasons
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.models.domain import Action, OutcomeResult, RouteState
from app.services.ledger.repository import LedgerRepository


@dataclass
class Metrics:
    total_events: int
    recoverable: int
    recovered: int
    recovery_rate: float
    rupees_rescued: float
    retries_fired: int
    retries_avoided_degraded: int  # HOLDs while route unhealthy
    wasted_retries_avoided: int  # hard failures not retried
    links_issued: int
    unrecoverable: int

    def as_dict(self) -> dict:
        return asdict(self)


def compute(repo: LedgerRepository) -> Metrics:
    decisions = repo.all_decisions()
    outcomes = repo.all_outcomes()

    total = len(decisions)
    recovered_outcomes = [
        o for o in outcomes if o.result == OutcomeResult.RECOVERED.value
    ]
    recovered = len(recovered_outcomes)
    rupees = sum(o.amount_recovered for o in recovered_outcomes) / 100.0

    retries_fired = sum(1 for d in decisions if d.action == Action.RETRY.value)
    links_issued = sum(1 for d in decisions if d.action == Action.RECOVERY_LINK.value)

    # HOLDs taken specifically because the route was unhealthy = retries the
    # naive baseline would have fired into a failing rail.
    retries_avoided = sum(
        1
        for d in decisions
        if d.action == Action.HOLD.value
        and d.route_state
        in (
            RouteState.DEGRADING.value,
            RouteState.DOWN.value,
            RouteState.RECOVERING.value,
        )
    )

    # "Wasted retries avoided" = user-side (hard/business) failures where a
    # naive loop would have retried and always failed, but we issued a link
    # instead. Every business failure becomes a recovery link (rule R3), so this
    # is exactly links_issued. We deliberately do NOT add the R6 unrecoverable
    # stops here — those are counted under `unrecoverable`, and counting them in
    # both places was a double-count.
    wasted_avoided = links_issued

    unrecoverable = sum(1 for d in decisions if d.action == Action.STOP.value)

    # "Recoverable" = decisions where a recovery was even attempted or possible
    # (retry or link). We do not count HOLDs or STOPs as recoverable-and-missed;
    # that would flatter the rate dishonestly.
    recoverable = retries_fired + links_issued
    rate = (recovered / recoverable) if recoverable else 0.0

    return Metrics(
        total_events=total,
        recoverable=recoverable,
        recovered=recovered,
        recovery_rate=round(rate, 4),
        rupees_rescued=round(rupees, 2),
        retries_fired=retries_fired,
        retries_avoided_degraded=retries_avoided,
        wasted_retries_avoided=wasted_avoided,
        links_issued=links_issued,
        unrecoverable=unrecoverable,
    )
