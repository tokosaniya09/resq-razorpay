"""Pydantic schemas for the HTTP/WS boundary.

These validate what crosses the wire. Domain dataclasses (models/domain.py)
stay framework-free; these are the request/response shapes only.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SyntheticEventIn(BaseModel):
    event_id: str
    transaction_id: str
    amount: int = Field(gt=0, description="amount in paise")
    currency: str = "INR"
    status: str = "failed"
    error_code: str | None = None
    route: str = "UPI-HDFC"
    customer_name: str | None = None


class HealthOut(BaseModel):
    route: str
    state: str
    failure_rate: float
    samples: int


class MetricsOut(BaseModel):
    total_events: int
    recoverable: int
    recovered: int
    recovery_rate: float
    rupees_rescued: float
    retries_fired: int
    retries_avoided_degraded: int
    wasted_retries_avoided: int
    links_issued: int
    unrecoverable: int


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
