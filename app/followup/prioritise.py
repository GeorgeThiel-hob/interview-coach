"""Follow-up runs (spec 5.9): pick which previous weak points to re-test.

1. Relevance: Jev ``f_relevant`` per previous focus item against the new vacancy.
2. Priority (code): severity x relevance x recency weight.
3. The top items become the run's focus list; the plan re-tests them with new questions.
Mastery per item is judged after each re-tested answer (``f_mastery``, see evaluation.py).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import Requirement, Run
from app.ingest.pseudonymise import PiiMapping, pseudonymise, stored
from app.judgments.cascade import Asked, ask, thresholds
from app.judgments.catalog import get
from app.llm.gateway import Gateway
from app.llm.text import fence, join
from app.report.schema import Report


def priority(severity: float, relevance: float, history: list[str], decay: float) -> float:
    # older weak points (seen in more previous runs without being mastered) weigh less,
    # recent ones more; an item that regressed gets a boost
    age = max(0, len(history) - 1)
    boost = 1.2 if history and history[-1] == "regressed" else 1.0
    return round(severity * relevance * (decay**age) * boost, 4)


async def select_focus_items(
    gateway: Gateway, engine: Engine, run_id: str, previous: Report, mapping: PiiMapping
) -> list[dict[str, Any]]:
    cfg = thresholds()["followup"]
    with Session(engine) as s:
        reqs = s.exec(select(Requirement).where(Requirement.run_id == run_id)).all()
    vacancy = "\n".join(f"{r.id} ({r.kind}): {r.text}" for r in reqs)
    items = list(previous.focus_items)
    if not items:
        return []
    entry = get("f_relevant")
    selected: list[dict[str, Any]] = []
    # one call per item keeps each state focused (the weak point + the new vacancy)
    for item in items:
        # the previous report holds restored real names: run the full pseudonymiser (Qwen too),
        # sharing this run's mapping so the same person keeps the same token
        label_text = await pseudonymise(gateway, item.label, mapping, run_id=run_id)
        state = join([fence("weak_point", label_text), fence("new_vacancy", stored(vacancy))])
        out = await ask(
            gateway,
            engine,
            state,
            [Asked("f_relevant", entry, entry.build(), subject=item.id)],
            run_id=run_id,
        )
        relevance = float(out["f_relevant"].value)
        if relevance < float(cfg["min_relevance"]):
            continue
        selected.append(
            {
                **item.model_dump(),
                "label": label_text.text,
                "previous_answer": (
                    await pseudonymise(gateway, item.previous_answer, mapping, run_id=run_id)
                ).text
                if item.previous_answer
                else "",
                "previous_questions": [
                    (await pseudonymise(gateway, q, mapping, run_id=run_id)).text
                    for q in item.previous_questions
                ],
                "relevance": round(relevance, 3),
                "priority": priority(
                    item.severity, relevance, item.history, float(cfg["recency_decay"])
                ),
            }
        )
    selected.sort(key=lambda f: f["priority"], reverse=True)
    top = selected[: int(cfg["max_focus_items"])]
    with Session(engine) as s:
        run = s.get(Run, run_id)
        if run:
            run.focus_items = top
            s.add(run)
            s.commit()
    return top
