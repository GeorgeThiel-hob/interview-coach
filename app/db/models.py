"""Database tables. M0 only needs ``model_calls``; the rest of section 8.1 arrives in M1."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class ModelCall(SQLModel, table=True):
    """One row per provider call. Never stores prompt or response content."""

    __tablename__ = "model_calls"

    id: int | None = Field(default=None, primary_key=True)
    run_id: str | None = Field(default=None, index=True)
    role: str
    provider: str
    model: str  # what we asked for
    served_model: str | None = None  # what answered (e.g. jev-1.13.0), if reported
    attempt: int = 1
    tokens_in: int = 0
    tokens_out: int = 0
    cost_eur: float = 0.0
    latency_ms: int = 0
    status: str  # ok | error | transient_error | blocked
    escalation_reason: str | None = None
    error_type: str | None = None
    created_at: datetime = Field(default_factory=_now, index=True)
