"""Database tables (spec section 8.1). SQLite via SQLModel; Postgres-ready.

Everything user-derived is stored pseudonymised. The only way back to real names is the
encrypted ``pii_maps`` row of the run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


def _id() -> str:
    return uuid4().hex


def _json(default: Any = None) -> Any:
    factory = (
        (lambda: dict(default)) if isinstance(default, dict) else (lambda: list(default or []))
    )
    return Field(default_factory=factory, sa_column=Column(JSON))


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: str = Field(default_factory=_id, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    role: str = "candidate"  # candidate | admin | coach
    created_at: datetime = Field(default_factory=_now)
    invited_by: str | None = None


class Invite(SQLModel, table=True):
    __tablename__ = "invites"
    code: str = Field(primary_key=True)
    created_by: str
    role: str = "candidate"
    expires_at: datetime
    used_by: str | None = None


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    id: str = Field(default_factory=_id, primary_key=True)
    user_id: str | None = Field(default=None, index=True)
    status: str = "created"  # created|preparing|ready|interviewing|paused|reviewing|done|failed
    settings: dict[str, Any] = _json({})
    briefing: dict[str, Any] = _json({})
    context: dict[str, Any] = _json({})  # vacancy summary / organisation / domain
    focus_items: list[dict[str, Any]] = _json([])
    interview_state: dict[str, Any] = _json({})
    error: str | None = None
    created_at: datetime = Field(default_factory=_now, index=True)
    finished_at: datetime | None = None
    schema_version: str = "report/v1"


class Document(SQLModel, table=True):
    __tablename__ = "documents"
    id: str = Field(default_factory=_id, primary_key=True)
    run_id: str = Field(index=True)
    kind: str  # vacancy | cv | report | motivation | notes
    filename: str
    sha256: str
    text_pseudonymised: str
    injection_flag: bool = False
    detected_kind: str | None = None
    created_at: datetime = Field(default_factory=_now)


class PiiMap(SQLModel, table=True):
    __tablename__ = "pii_maps"
    run_id: str = Field(primary_key=True)
    encrypted_mapping: bytes


class Chunk(SQLModel, table=True):
    __tablename__ = "chunks"
    id: int | None = Field(default=None, primary_key=True)
    document_id: str = Field(index=True)
    run_id: str = Field(index=True)
    chunk_ref: str = Field(index=True)  # cv:role2:b3, vac:p4
    text_pseudonymised: str
    embedding: list[float] = _json([])


class Requirement(SQLModel, table=True):
    __tablename__ = "requirements"
    id: str = Field(primary_key=True)  # eis_1, wens_2, resp_1 (unique per run via run_id)
    run_id: str = Field(primary_key=True)
    kind: str  # eis | wens | responsibility
    text: str
    source_chunk_ref: str | None = None
    evidence_strength: str = "none"  # strong | partial | none
    evidence_refs: list[str] = _json([])


class PlanTopic(SQLModel, table=True):
    __tablename__ = "plan_topics"
    id: str = Field(default_factory=_id, primary_key=True)
    run_id: str = Field(index=True)
    order: int
    persona: str
    question_type: str
    goal: str
    requirement_ids: list[str] = _json([])
    opening_question: str = ""
    follow_up_angles: list[str] = _json([])
    focus_item_id: str | None = None


class Turn(SQLModel, table=True):
    __tablename__ = "turns"
    id: str = Field(default_factory=_id, primary_key=True)
    run_id: str = Field(index=True)
    topic_id: str | None = None
    seq: int
    role: str  # interviewer | candidate
    persona: str | None = None
    text_pseudonymised: str
    audio_duration_s: float | None = None
    next_move: str | None = None  # the move that produced this interviewer turn
    practice_of: str | None = None  # turn id when this is a re-answer in practice mode
    created_at: datetime = Field(default_factory=_now)


class Judgment(SQLModel, table=True):
    __tablename__ = "judgments"
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    turn_id: str | None = Field(default=None, index=True)
    subject: str | None = (
        None  # e.g. chunk ref / requirement id / focus item for non-turn judgments
    )
    question_id: str
    question_version: int
    provider: str  # jev | claude
    answer: dict[str, Any] = _json({})  # {"value": ..., "probabilities": {...}, "rationale": ...}
    confidence: float | None = None
    uncertain: bool = False
    escalated: bool = False
    latency_ms: int = 0


class Feedback(SQLModel, table=True):
    __tablename__ = "feedback"
    turn_id: str = Field(primary_key=True)
    run_id: str = Field(index=True)
    strengths: list[dict[str, Any]] = _json([])
    add: list[dict[str, Any]] = _json([])
    explore: list[dict[str, Any]] = _json([])
    outline: list[dict[str, Any]] = _json([])
    dropped: int = 0  # items removed by the fb_grounded check


class Event(SQLModel, table=True):
    """Guardrail and safety events for the admin metrics page (spec 10.1). No content."""

    __tablename__ = "events"
    id: int | None = Field(default=None, primary_key=True)
    run_id: str | None = Field(default=None, index=True)
    kind: str  # question_regenerated | question_escalated | question_blocked | injection_flag ...
    detail: str | None = None
    created_at: datetime = Field(default_factory=_now, index=True)


class Report(SQLModel, table=True):
    __tablename__ = "reports"
    id: str = Field(default_factory=_id, primary_key=True)
    run_id: str = Field(index=True)
    report_json: dict[str, Any] = _json({})  # pseudonymised
    created_at: datetime = Field(default_factory=_now)


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
    status: str  # ok | error | transient_error | offline
    escalation_reason: str | None = None
    error_type: str | None = None
    created_at: datetime = Field(default_factory=_now, index=True)
