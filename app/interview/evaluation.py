"""Per-answer evaluation (spec 5.4, catalog 7.4): runs in the background during the interview.

Counting (words, duration, words per minute, fillers) is done in code in app/review/metrics.py,
never by a model.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine
from sqlmodel import Session

from app.db.models import PlanTopic, Requirement, Run
from app.ingest.pseudonymise import stored
from app.judgments.cascade import Asked, Outcome, ask
from app.judgments.catalog import ANSWER_EVAL_IDS, get
from app.llm.errors import BudgetExceeded, ProviderError
from app.llm.gateway import Gateway
from app.llm.text import SafeText, fence, join, label

log = logging.getLogger(__name__)


def evaluation_questions(topic: PlanTopic, reqs: list[Requirement]) -> list[Asked]:
    asked = [Asked(q, get(q), get(q).build()) for q in ANSWER_EVAL_IDS if q != "next_move"]
    for r in reqs:
        asked.append(
            Asked(
                f"a_req_{r.id}",
                get("a_req"),
                get("a_req").build(requirement=label(r.id)),
                subject=r.id,
            )
        )
    if topic.focus_item_id:
        asked.append(
            Asked(
                "f_mastery", get("f_mastery"), get("f_mastery").build(), subject=topic.focus_item_id
            )
        )
    return asked


async def evaluate_answer(
    gateway: Gateway,
    engine: Engine,
    run_id: str,
    turn_id: str,
    topic: PlanTopic,
    context: SafeText,
    reqs: list[Requirement],
) -> dict[str, Outcome]:
    state = context
    if topic.focus_item_id:
        with Session(engine) as s:
            run = s.get(Run, run_id)
        item = next(
            (f for f in (run.focus_items if run else []) if f["id"] == topic.focus_item_id), None
        )
        if item:
            prev = (
                f"weak point: {item['label']}\nprevious result: {item.get('history', ['?'])[-1]}\n"
                f"previous answer summary: {item.get('previous_answer', '')}"
            )
            state = join([context, fence("previous_attempt", stored(prev))])
    try:
        return await ask(
            gateway,
            engine,
            state,
            evaluation_questions(topic, reqs),
            run_id=run_id,
            turn_id=turn_id,
        )
    except (ProviderError, BudgetExceeded) as e:
        log.warning("answer evaluation failed for turn %s: %s", turn_id, type(e).__name__)
        return {}
