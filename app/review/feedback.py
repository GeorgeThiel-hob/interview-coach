"""Grounded per-answer feedback (spec 5.5, 9.4).

Claude writes feedback with source references; code then enforces the integrity rules:
* unknown sources are removed, and strengths/add/outline items without a source are dropped;
* explore items must be questions (they may not assert experience);
* the Jev ``fb_grounded`` check removes items it cannot ground in the cited sources.
"""

from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session

from app.db.models import Feedback, PlanTopic, Requirement, Turn
from app.ingest.pseudonymise import stored
from app.ingest.service import chunks
from app.judgments.cascade import Asked, ask, thresholds
from app.judgments.catalog import get
from app.llm.errors import BudgetExceeded, ProviderError
from app.llm.gateway import Gateway
from app.llm.prompts import prompt
from app.llm.text import SafeText, TrustedText, fence, join, label
from app.llm.types import Message
from app.report.build import load, qa_pairs

_REF = re.compile(r"^(cv:[\w:]+|turn:[0-9a-f]+)$")


class Item(BaseModel):
    text: str
    sources: list[str] = Field(default_factory=list)


class FeedbackOut(BaseModel):
    strengths: list[Item] = Field(default_factory=list)
    add: list[Item] = Field(default_factory=list)
    explore: list[Item] = Field(default_factory=list)
    outline: list[Item] = Field(default_factory=list)


def clean(out: FeedbackOut, known: set[str], answer_ref: str) -> FeedbackOut:
    def fix(items: list[Item], need_source: bool) -> list[Item]:
        kept = []
        for it in items:
            sources = [s for s in it.sources if s in known and _REF.match(s)]
            if need_source and not sources:
                continue
            kept.append(it.model_copy(update={"sources": sources or [answer_ref]}))
        return kept

    explore = [it for it in out.explore if it.text.strip().endswith("?")]
    return FeedbackOut(
        strengths=fix(out.strengths, True),
        add=fix(out.add, True),
        explore=fix(explore, False),
        outline=fix(out.outline, True),
    )


def _sources_text(refs: set[str], cv: dict[str, str], turns: dict[str, str]) -> str:
    lines = []
    for ref in sorted(refs):
        if ref in cv:
            lines.append(f"[{ref}] {cv[ref]}")
        elif ref in turns:
            lines.append(f"[{ref}] {turns[ref]}")
    return "\n".join(lines)


async def grounding_check(
    gateway: Gateway,
    engine: Engine,
    run_id: str,
    turn_id: str,
    fb: FeedbackOut,
    cv: dict[str, str],
    turns: dict[str, str],
) -> tuple[FeedbackOut, int]:
    checked = [("strengths", fb.strengths), ("add", fb.add), ("outline", fb.outline)]
    items = [(section, i, it) for section, lst in checked for i, it in enumerate(lst)]
    if not items:
        return fb, 0
    entry = get("fb_grounded")
    parts: list[SafeText] = []
    asked: list[Asked] = []
    for n, (_section, _i, it) in enumerate(items, 1):
        tag = f"fb{n}"
        parts.append(fence(f"item-{tag}", stored(it.text)))
        parts.append(fence(f"sources-{tag}", stored(_sources_text(set(it.sources), cv, turns))))
        asked.append(Asked(tag, entry, entry.build(label=label(f"item-{tag}")), subject=tag))
    try:
        out = await ask(gateway, engine, join(parts), asked, run_id=run_id, turn_id=turn_id)
    except (ProviderError, BudgetExceeded):
        return fb, 0  # keep the source-checked items; the report marks nothing as grounded
    keep = {a.key for a in asked if out[a.key].yes}
    result = {"strengths": [], "add": [], "outline": []}  # type: dict[str, list[Item]]
    for n, (section, _i, it) in enumerate(items, 1):
        if f"fb{n}" in keep:
            result[section].append(it)
    dropped = len(items) - len(keep)
    return fb.model_copy(update=result), dropped


async def feedback_for_answer(
    gateway: Gateway,
    engine: Engine,
    run_id: str,
    question: Turn,
    answer: Turn,
    topic: PlanTopic | None,
    reqs: list[Requirement],
    language: str,
    cv: dict[str, str],
    turn_texts: dict[str, str],
) -> Feedback:
    answer_ref = f"turn:{answer.id}"
    linked = [r for r in reqs if topic and r.id in topic.requirement_ids]
    material = join(
        [
            TrustedText("Interview language: {lang}.").render(lang=label(language)),
            fence("question", stored(question.text_pseudonymised)),
            fence("answer", stored(f"[{answer_ref}] {answer.text_pseudonymised}")),
            fence("topic_goal", stored(topic.goal if topic else "")),
            fence(
                "linked_requirements",
                stored("\n".join(f"{r.id}: {r.text}" for r in linked) or "none"),
            ),
            fence("cv_fragments", stored("\n".join(f"[{k}] {v}" for k, v in cv.items()))),
        ]
    )
    out = await gateway.generate(
        "feedback",
        [Message("system", prompt("feedback")), Message("user", material)],
        FeedbackOut,
        run_id=run_id,
    )
    assert isinstance(out.parsed, FeedbackOut)
    known = set(cv) | set(turn_texts)
    cleaned = clean(out.parsed, known, answer_ref)
    grounded, dropped = await grounding_check(
        gateway, engine, run_id, answer.id, cleaned, cv, turn_texts
    )
    removed_by_rules = sum(
        len(getattr(out.parsed, k)) for k in ("strengths", "add", "explore", "outline")
    ) - sum(len(getattr(cleaned, k)) for k in ("strengths", "add", "explore", "outline"))
    return Feedback(
        turn_id=answer.id,
        run_id=run_id,
        strengths=[i.model_dump() for i in grounded.strengths],
        add=[i.model_dump() for i in grounded.add],
        explore=[i.model_dump() for i in grounded.explore],
        outline=[i.model_dump() for i in grounded.outline],
        dropped=dropped + removed_by_rules,
    )


async def write_feedback(
    gateway: Gateway, engine: Engine, run_id: str, *, concurrency: int = 3
) -> int:
    d = load(engine, run_id)
    lang = str(d["run"].settings.get("language", "nl"))
    cv = {c.chunk_ref: c.text_pseudonymised for c in chunks(engine, run_id, "cv:")}
    turn_texts = {f"turn:{t.id}": t.text_pseudonymised for t in d["turns"] if t.role == "candidate"}
    sem = asyncio.Semaphore(concurrency)
    pairs = [p for p in qa_pairs(d["turns"]) if p[1].id not in d["feedback"]]

    async def one(q: Turn, a: Turn) -> Feedback | None:
        async with sem:
            try:
                return await feedback_for_answer(
                    gateway,
                    engine,
                    run_id,
                    q,
                    a,
                    d["topics"].get(a.topic_id or ""),
                    d["reqs"],
                    lang,
                    cv,
                    turn_texts,
                )
            except (ProviderError, BudgetExceeded):
                return None

    results = await asyncio.gather(*(one(q, a) for q, a in pairs))
    with Session(engine) as s:
        for fb in results:
            if fb is not None:
                s.merge(fb)
        s.commit()
    return sum(r is not None for r in results)


def noul_yes() -> float:
    return float(thresholds()["noul_yes"])
