"""Retention (spec 9.2): delete a run completely, and purge runs older than N days."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, select

from app.db.models import (
    Chunk,
    Document,
    Event,
    Feedback,
    Judgment,
    ModelCall,
    PiiMap,
    PlanTopic,
    Report,
    Requirement,
    Run,
    Turn,
)

_PER_RUN: list[type[SQLModel]] = [
    Chunk,
    Document,
    Feedback,
    Judgment,
    PlanTopic,
    Report,
    Requirement,
    Turn,
    Event,
]


def delete_run(engine: Engine, run_id: str) -> None:
    """Remove all content of a run. Content-free model_calls rows are kept for cost metrics,
    unlinked from the run."""
    with Session(engine) as s:
        for table in _PER_RUN:
            for row in s.exec(select(table).where(table.run_id == run_id)).all():  # type: ignore[attr-defined]
                s.delete(row)
        for call in s.exec(select(ModelCall).where(ModelCall.run_id == run_id)).all():
            call.run_id = None
            s.add(call)
        pii = s.get(PiiMap, run_id)
        if pii:
            s.delete(pii)
        run = s.get(Run, run_id)
        if run:
            s.delete(run)
        s.commit()


def purge_old_runs(engine: Engine, days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with Session(engine) as s:
        old = [r.id for r in s.exec(select(Run)).all() if r.created_at.replace(tzinfo=UTC) < cutoff]
    for run_id in old:
        delete_run(engine, run_id)
    return len(old)
