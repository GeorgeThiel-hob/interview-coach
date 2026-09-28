"""Interview plan (Claude) and pre-interview briefing (Claude), spec 5.2.

The model proposes; code enforces the rules: every eis is covered, only allowed personas and
question types are used, the interview ends with a closing topic, and the topic count fits
the chosen length.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import PlanTopic, Requirement, Run
from app.ingest.pseudonymise import stored
from app.ingest.service import chunks
from app.llm.gateway import Gateway
from app.llm.prompts import prompt
from app.llm.text import SafeText, TrustedText, fence, join, label
from app.llm.types import Message

INTERVIEW_CONFIG = Path(__file__).resolve().parents[2] / "config" / "interview.yaml"

QuestionType = Literal["motivation", "behavioural", "technical", "gap", "situational", "closing"]
Persona = Literal["intake_account_manager", "technical_lead", "hiring_manager"]


@lru_cache
def interview_config() -> dict[str, Any]:
    with INTERVIEW_CONFIG.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


class TopicOut(BaseModel):
    goal: str
    requirement_ids: list[str] = Field(default_factory=list)
    question_type: QuestionType
    persona: Persona
    opening_question: str
    follow_up_angles: list[str] = Field(default_factory=list)
    focus_item_id: str | None = None


class PlanOut(BaseModel):
    topics: list[TopicOut]


class EvidencePoint(BaseModel):
    requirement_id: str
    summary: str
    chunk_refs: list[str] = Field(default_factory=list)


class GapAdvice(BaseModel):
    requirement_id: str
    advice: str


class BriefingOut(BaseModel):
    likely_questions: list[str]
    strongest_evidence: list[EvidencePoint]
    gaps: list[GapAdvice]
    prepare: list[str]


def prepare_items(b: BriefingOut) -> list[str]:
    """Three things to prepare; when the model left the list empty, use the gap advice."""
    items = [p for p in b.prepare if p.strip()] or [g.advice for g in b.gaps if g.advice.strip()]
    return items[:3]


def _requirements(engine: Engine, run_id: str) -> list[Requirement]:
    with Session(engine) as s:
        return list(s.exec(select(Requirement).where(Requirement.run_id == run_id)).all())


def _material(engine: Engine, run: Run, reqs: list[Requirement]) -> SafeText:
    s = run.settings
    lines = [
        f"- {r.id} ({r.kind}, evidence in CV: {r.evidence_strength}"
        + (f", supporting fragments: {', '.join(r.evidence_refs)}" if r.evidence_refs else "")
        + f"): {r.text}"
        for r in reqs
    ]
    parts: list[SafeText] = [
        TrustedText("Settings:"),
        TrustedText(
            "- interview type: {t}\n- language: {lang}\n- length: {m} minutes "
            "(about {n} topics)\n- difficulty: {d}\n- allowed personas: {p}\n"
            "- allowed question types: {q}"
        ).render(
            t=label(s.get("interview_type", "mixed")),
            lang=label(s.get("language", "nl")),
            m=label(s.get("length", 30)),
            n=label(topic_count(s)),
            d=label(s.get("difficulty", "realistic")),
            p=label(",".join(allowed_personas(s))),
            q=label(",".join(interview_config()["question_types"])),
        ),
        fence("vacancy_context", stored(_context_text(run))),
        fence("requirements", stored("\n".join(lines))),
        fence(
            "cv",
            stored(
                "\n".join(
                    f"[{c.chunk_ref}] {c.text_pseudonymised}" for c in chunks(engine, run.id, "cv:")
                )
            ),
        ),
    ]
    if run.focus_items:
        focus = "\n".join(
            f"- {f['id']}: {f['label']} (previous result: {f.get('history', ['?'])[-1]}; "
            f"linked requirements: {', '.join(f.get('linked_requirements', []))}; "
            f"questions asked last time: {' | '.join(f.get('previous_questions', []))})"
            for f in run.focus_items
        )
        parts.append(fence("focus_items", stored(focus)))
    return join(parts)


def _context_text(run: Run) -> str:
    c = run.context or {}
    return "\n".join(f"{k}: {v}" for k, v in c.items() if v)


def topic_count(settings: dict[str, Any]) -> int:
    counts = interview_config()["topics_per_length"]
    return int(counts.get(int(settings.get("length", 30)), 7))


def allowed_personas(settings: dict[str, Any]) -> list[str]:
    return list(interview_config()["personas"][settings.get("interview_type", "mixed")])


def _attach(topics: list[TopicOut], rid: str) -> None:
    """Add a requirement to the non-opening topic with the fewest requirements."""
    if not topics:
        return
    pool = topics[1:] or topics
    target = min(pool, key=lambda t: len(t.requirement_ids))
    if rid not in target.requirement_ids:
        target.requirement_ids.append(rid)


def enforce_plan(
    plan: PlanOut, reqs: list[Requirement], settings: dict[str, Any], focus_ids: set[str]
) -> list[TopicOut]:
    """Apply the plan rules in code; returns the corrected topic list."""
    valid_ids = {r.id for r in reqs}
    personas = allowed_personas(settings)
    topics: list[TopicOut] = []
    for t in plan.topics:
        t = t.model_copy(
            update={
                "requirement_ids": [r for r in t.requirement_ids if r in valid_ids],
                "persona": t.persona if t.persona in personas else personas[0],
                "focus_item_id": t.focus_item_id if t.focus_item_id in focus_ids else None,
            }
        )
        topics.append(t)
    closings = [t for t in topics if t.question_type == "closing"]
    topics = [t for t in topics if t.question_type != "closing"]
    # the topic count per length is a code rule: keep the first topics (the opening stays first)
    # and move the requirements of the dropped ones onto the kept topics, so coverage is kept
    limit = max(1, topic_count(settings) - 1)  # minus the closing topic
    dropped_reqs = [r for t in topics[limit:] for r in t.requirement_ids]
    topics = topics[:limit]
    for rid in dropped_reqs:
        _attach(topics, rid)
    covered = {r for t in topics for r in t.requirement_ids}
    missing = [r for r in reqs if r.kind == "eis" and r.id not in covered]
    for r in missing:
        if len(topics) >= limit:
            _attach(topics, r.id)
            continue
        topics.append(
            TopicOut(
                goal=f"Test requirement {r.id}: {r.text}",
                requirement_ids=[r.id],
                question_type="gap" if r.evidence_strength == "none" else "behavioural",
                persona=personas[-1],
                opening_question="",  # generated live by the interviewer from the goal
            )
        )
    closing = (
        closings[0]
        if closings
        else TopicOut(
            goal="Give the candidate room to ask their own questions and close the interview.",
            question_type="closing",
            persona=personas[0],
            opening_question="",
        )
    )
    return [*topics, closing]


async def make_plan(gateway: Gateway, engine: Engine, run_id: str) -> list[PlanTopic]:
    with Session(engine) as s:
        run = s.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run {run_id}")
    reqs = _requirements(engine, run_id)
    out = await gateway.generate(
        "plan",
        [Message("system", prompt("plan")), Message("user", _material(engine, run, reqs))],
        PlanOut,
        run_id=run_id,
    )
    assert isinstance(out.parsed, PlanOut)
    focus_ids = {f["id"] for f in run.focus_items}
    topics = enforce_plan(out.parsed, reqs, run.settings, focus_ids)
    rows = [
        PlanTopic(
            run_id=run_id,
            order=i,
            persona=t.persona,
            question_type=t.question_type,
            goal=t.goal,
            requirement_ids=t.requirement_ids,
            opening_question=t.opening_question,
            follow_up_angles=t.follow_up_angles,
            focus_item_id=t.focus_item_id,
        )
        for i, t in enumerate(topics)
    ]
    with Session(engine) as s:
        for old in s.exec(select(PlanTopic).where(PlanTopic.run_id == run_id)).all():
            s.delete(old)
        for r in rows:
            s.add(r)
        s.commit()
        for r in rows:
            s.refresh(r)
    return rows


async def make_briefing(gateway: Gateway, engine: Engine, run_id: str) -> BriefingOut:
    with Session(engine) as s:
        run = s.get(Run, run_id)
    if run is None:
        raise ValueError(f"unknown run {run_id}")
    reqs = _requirements(engine, run_id)
    out = await gateway.generate(
        "briefing",
        [Message("system", prompt("briefing")), Message("user", _material(engine, run, reqs))],
        BriefingOut,
        run_id=run_id,
    )
    assert isinstance(out.parsed, BriefingOut)
    known = {c.chunk_ref for c in chunks(engine, run_id, "cv:")}
    valid_reqs = {r.id for r in reqs}
    briefing = out.parsed.model_copy(
        update={
            # drop citations that do not exist, and evidence for unknown requirements
            "strongest_evidence": [
                e.model_copy(update={"chunk_refs": [c for c in e.chunk_refs if c in known]})
                for e in out.parsed.strongest_evidence
                if e.requirement_id in valid_reqs
            ],
            "prepare": prepare_items(out.parsed),
        }
    )
    with Session(engine) as s:
        row = s.get(Run, run_id)
        if row:
            row.briefing = briefing.model_dump()
            s.add(row)
            s.commit()
    return briefing
