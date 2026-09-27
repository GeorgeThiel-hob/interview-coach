"""Personal practice plan (spec 5.7): 3-5 actions ranked by impact, each linked to the
answers, statistics or tips it comes from. Links are validated in code."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session

from app.db.models import Run
from app.ingest.pseudonymise import stored
from app.llm.gateway import Gateway
from app.llm.prompts import prompt
from app.llm.text import TrustedText, fence, join, label
from app.llm.types import Message
from app.report.schema import Report
from app.review.tips import all_tips


class Action(BaseModel):
    action: str
    why: str
    links: list[str] = Field(default_factory=list)


class PracticePlanOut(BaseModel):
    actions: list[Action]


def valid_links(report: Report) -> set[str]:
    links = {f"turn:{a.turn_id}" for a in report.answers}
    links |= {f"tip:{t}" for t in all_tips()}
    links |= {f"stat:{k}" for k in report.stats}
    links |= {f"stat:star_{k.lower()}" for k in report.stats.get("star_rates", {})}
    return links


async def write_practice_plan(gateway: Gateway, engine: Engine, report: Report) -> list[Action]:
    weakest = sorted(
        (a for a in report.answers if "a_quality" in a.judgments),
        key=lambda a: float(a.judgments["a_quality"].value),
    )[:5]
    answers = "\n".join(
        f"turn:{a.turn_id} (quality {a.judgments['a_quality'].value}): Q: {a.question} A: {a.answer[:500]}"
        for a in weakest
    )
    focus = "\n".join(f"- {f.label} (severity {f.severity})" for f in report.focus_items)
    tips = "\n".join(f"tip:{t.id} - {t.title}" for t in all_tips().values())
    material = join(
        [
            TrustedText("Interview language: {lang}.").render(lang=label(report.language)),
            fence("statistics", stored(json.dumps(report.stats))),
            fence("weakest_answers", stored(answers or "none")),
            fence("weak_points", stored(focus or "none")),
            fence("tips_library", stored(tips)),
        ]
    )
    out = await gateway.generate(
        "feedback",
        [Message("system", prompt("practice_plan")), Message("user", material)],
        PracticePlanOut,
        run_id=report.run_id,
    )
    assert isinstance(out.parsed, PracticePlanOut)
    ok = valid_links(report)
    actions = [
        a.model_copy(update={"links": [link for link in a.links if link in ok]})
        for a in out.parsed.actions
    ][:5]
    with Session(engine) as s:
        run = s.get(Run, report.run_id)
        if run:
            run.briefing = {**run.briefing, "practice_plan": [a.model_dump() for a in actions]}
            s.add(run)
            s.commit()
    return actions
