"""Classifier service: PaymentEvent -> Classification.

A thin, pure wrapper around the rule table. No I/O, no state — which is why
it is trivial to unit-test exhaustively (see tests/test_classifier.py).
"""

from __future__ import annotations

from app.models.domain import Classification, PaymentEvent
from app.services.classifier.rules import lookup


def classify(event: PaymentEvent) -> Classification:
    rule = lookup(event.error_code)
    return Classification(
        event_id=event.event_id,
        failure_class=rule.failure_class,
        is_soft=rule.is_soft,
        mapped_reason=rule.reason,
    )
