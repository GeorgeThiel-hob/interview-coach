"""Run orchestration shared by the CLI and the web app.

create_run -> add_document (x N) -> prepare -> interview (app/interview/engine.py) -> finish
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from app.db.models import Run
from app.followup.prioritise import select_focus_items
from app.ingest.parse import ParsedFile
from app.ingest.service import IngestResult, ingest_document, load_mapping, save_mapping
from app.llm.gateway import Gateway
from app.prep.evidence import build_evidence_map
from app.prep.extract import extract_requirements
from app.prep.plan import make_briefing, make_plan
from app.report.build import build_report
from app.report.schema import Report
from app.review.feedback import write_feedback
from app.review.practice import write_practice_plan

Progress = Callable[[str], Awaitable[None] | None]

DEFAULT_SETTINGS: dict[str, Any] = {
    "interview_type": "mixed",  # intake | client | mixed
    "language": "nl",  # nl | en
    "length": 30,  # 15 | 30 | 45 minutes
    "answer_mode": "typed",  # typed | spoken
    "difficulty": "realistic",  # friendly | realistic | critical
}


def validate_settings(settings: dict[str, Any]) -> dict[str, Any]:
    s = {**DEFAULT_SETTINGS, **{k: v for k, v in settings.items() if v not in (None, "")}}
    allowed: dict[str, set[Any]] = {
        "interview_type": {"intake", "client", "mixed"},
        "language": {"nl", "en"},
        "length": {15, 30, 45},
        "answer_mode": {"typed", "spoken"},
        "difficulty": {"friendly", "realistic", "critical"},
    }
    s["length"] = int(s["length"])
    for key, values in allowed.items():
        if s[key] not in values:
            raise ValueError(f"invalid {key}: {s[key]!r}")
    return s


def create_run(engine: Engine, settings: dict[str, Any], user_id: str | None = None) -> str:
    with Session(engine) as s:
        run = Run(user_id=user_id, settings=validate_settings(settings))
        s.add(run)
        s.commit()
        return run.id


def set_status(engine: Engine, run_id: str, status: str, error: str | None = None) -> None:
    with Session(engine) as s:
        run = s.get(Run, run_id)
        if run:
            run.status = status
            run.error = error
            if status == "done":
                run.finished_at = datetime.now(UTC)
            s.add(run)
            s.commit()


async def _say(progress: Progress | None, message: str) -> None:
    if progress:
        result = progress(message)
        if result is not None:
            await result


async def add_document(
    gateway: Gateway,
    engine: Engine,
    run_id: str,
    kind: str,
    filename: str,
    parsed: ParsedFile,
    pii_key: str,
) -> IngestResult:
    return await ingest_document(
        gateway, engine, run_id=run_id, kind=kind, filename=filename, parsed=parsed, pii_key=pii_key
    )


async def prepare(
    gateway: Gateway,
    engine: Engine,
    run_id: str,
    pii_key: str,
    *,
    previous: Report | None = None,
    progress: Progress | None = None,
) -> None:
    set_status(engine, run_id, "preparing")
    try:
        await _say(progress, "extracting requirements")
        await extract_requirements(gateway, engine, run_id)
        await _say(progress, "matching CV evidence")
        await build_evidence_map(gateway, engine, run_id)
        if previous is not None:
            await _say(progress, "selecting weak points from your previous report")
            mapping = load_mapping(engine, run_id, pii_key)
            await select_focus_items(gateway, engine, run_id, previous, mapping)
            save_mapping(engine, run_id, mapping, pii_key)
        await _say(progress, "writing the interview plan")
        await make_plan(gateway, engine, run_id)
        await _say(progress, "writing your briefing")
        await make_briefing(gateway, engine, run_id)
    except Exception as e:
        set_status(engine, run_id, "failed", f"preparation failed: {type(e).__name__}")
        raise
    set_status(engine, run_id, "ready")


async def finish(
    gateway: Gateway, engine: Engine, run_id: str, pii_key: str, *, progress: Progress | None = None
) -> Report:
    """Feedback, practice plan and the stored report. Returns the report with real names."""
    set_status(engine, run_id, "reviewing")
    await _say(progress, "writing feedback per answer")
    await write_feedback(gateway, engine, run_id)
    draft = build_report(engine, run_id, store=False)
    await _say(progress, "writing your practice plan")
    await write_practice_plan(gateway, engine, draft)
    mapping = load_mapping(engine, run_id, pii_key)
    report = build_report(engine, run_id, mapping=mapping, store=True)
    set_status(engine, run_id, "done")
    return report
