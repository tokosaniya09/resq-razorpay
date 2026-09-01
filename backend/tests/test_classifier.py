"""Classifier tests.

The deterministic core is the most-tested part of the system. Every mapped
code is asserted, plus case-insensitivity and the conservative UNKNOWN path.
"""

from __future__ import annotations

import pytest

from app.models.domain import FailureClass
from app.services.classifier.rules import CLASSIFICATION_TABLE
from app.services.classifier.service import classify


@pytest.mark.parametrize("code", list(CLASSIFICATION_TABLE.keys()))
def test_every_mapped_code_classifies_to_its_family(make_event, code):
    rule = CLASSIFICATION_TABLE[code]
    result = classify(make_event(error_code=code))
    assert result.failure_class == rule.failure_class
    assert result.is_soft == rule.is_soft
    assert result.mapped_reason == rule.reason


def test_technical_examples(make_event):
    for code in ("GATEWAY_TIMEOUT", "NETWORK_TIMEOUT", "ISSUER_DOWN"):
        assert classify(make_event(error_code=code)).failure_class is FailureClass.TECHNICAL


def test_business_examples(make_event):
    for code in ("INSUFFICIENT_FUNDS", "CARD_EXPIRED", "INCORRECT_PIN"):
        c = classify(make_event(error_code=code))
        assert c.failure_class is FailureClass.BUSINESS
        assert c.is_soft is False


def test_case_insensitive(make_event):
    assert classify(make_event(error_code="gateway_timeout")).is_soft is True
    assert classify(make_event(error_code="  Insufficient_Funds ")).failure_class is FailureClass.BUSINESS


def test_unknown_is_conservative(make_event):
    for code in (None, "", "SOMETHING_NEW"):
        c = classify(make_event(error_code=code))
        assert c.failure_class is FailureClass.UNKNOWN
        assert c.is_soft is False  # never treated as blindly retryable
