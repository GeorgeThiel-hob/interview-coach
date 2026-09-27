"""The cascade (spec 6.2): Jev judges, low-confidence answers escalate to Claude.

Every judgment is stored in ``judgments`` with provider, confidence, whether it was uncertain
and whether it escalated, so each evaluation stays traceable in the review.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session

from app.db.models import Judgment
from app.judgments.catalog import CatalogQuestion
from app.llm.errors import BudgetExceeded, ProviderError
from app.llm.gateway import Gateway
from app.llm.prompts import prompt
from app.llm.text import SafeText, TrustedText, fence, join, label
from app.llm.types import JudgeAnswer, JudgeQuestion, Message

THRESHOLDS_PATH = Path(__file__).resolve().parents[2] / "config" / "thresholds.yaml"


@lru_cache
def thresholds() -> dict[str, Any]:
    with THRESHOLDS_PATH.open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def rule(qid: str, key: str) -> Any:
    t = thresholds()
    return t.get("per_question", {}).get(qid, {}).get(key, t["default"][key])


@dataclass(frozen=True)
class Asked:
    """One question in a cascade call: catalog entry + built question + storage key."""

    key: str  # unique within the call, e.g. "a_req_eis_2" or "evidence_f3"
    entry: CatalogQuestion
    question: JudgeQuestion
    subject: str | None = None  # requirement id / chunk ref / focus item, if any


@dataclass(frozen=True)
class Outcome:
    key: str
    question_id: str
    kind: str
    value: float | str
    confidence: float | None
    uncertain: bool
    escalated: bool
    provider: str
    probabilities: dict[str, float] = field(default_factory=dict)
    rationale: str | None = None

    @property
    def yes(self) -> bool:
        """For noul questions: the answer counts as yes."""
        cutoff = float(thresholds()["noul_yes"])
        return isinstance(self.value, float) and self.value >= cutoff


def is_uncertain(qid: str, answer: JudgeAnswer) -> bool:
    if answer.kind == "noul":
        lo, hi = rule(qid, "noul_uncertain_band")
        return float(lo) <= float(answer.value) <= float(hi)
    key = "choice_min_confidence" if answer.kind == "choice" else "score_min_confidence"
    return answer.confidence is not None and answer.confidence < float(rule(qid, key))


class _EscalatedAnswer(BaseModel):
    key: str
    answer: str
    rationale: str


class _Escalation(BaseModel):
    answers: list[_EscalatedAnswer]


def _describe(asked: Asked) -> SafeText:
    q = asked.question
    lines: list[SafeText] = [
        TrustedText("- id `{key}` ({kind}): ").render(key=label(asked.key), kind=label(q.kind))
        + q.instructions
    ]
    if isinstance(q.criteria, dict):
        for name, desc in q.criteria.items():
            opt = TrustedText("    option `{n}`").render(n=label(name))
            lines.append(opt + (TrustedText(": ") + desc if desc else TrustedText("")))
    elif isinstance(q.criteria, list):
        for i, desc in enumerate(q.criteria):
            lines.append(TrustedText("    level {i}: ").render(i=label(i)) + desc)
    return join(lines, "\n")


def _parse_escalated(asked: Asked, raw: str) -> float | str | None:
    raw = raw.strip().lower().strip("`'\" .")
    kind = asked.question.kind
    if kind == "noul":
        return (
            1.0
            if raw in {"yes", "ja", "true", "1"}
            else 0.0
            if raw in {"no", "nee", "false", "0"}
            else None
        )
    if kind == "choice":
        return raw if raw in asked.entry.options else None
    try:
        level = int(float(raw))
    except ValueError:
        return None
    n = len(asked.question.criteria or [])
    return float(level) if 0 <= level < n else None


async def ask(
    gateway: Gateway,
    engine: Engine,
    state: SafeText,
    asked: list[Asked],
    *,
    run_id: str | None,
    turn_id: str | None = None,
    allow_escalation: bool = True,
) -> dict[str, Outcome]:
    """Ask Jev, escalate uncertain answers to Claude, store and return every outcome."""
    started = time.monotonic()
    result = await gateway.judge(state, {a.key: a.question for a in asked}, run_id=run_id)
    jev_ms = int((time.monotonic() - started) * 1000)

    outcomes: dict[str, Outcome] = {}
    to_escalate: list[Asked] = []
    for a in asked:
        ans = result.answers[a.key]
        uncertain = is_uncertain(a.entry.id, ans)
        outcomes[a.key] = Outcome(
            key=a.key,
            question_id=a.entry.id,
            kind=ans.kind,
            value=ans.value,
            confidence=ans.confidence,
            uncertain=uncertain,
            escalated=False,
            provider="jev",
            probabilities=ans.probabilities,
        )
        if uncertain and allow_escalation and rule(a.entry.id, "escalate"):
            to_escalate.append(a)

    claude_ms = 0
    if to_escalate:
        started = time.monotonic()
        try:
            escalated = await _escalate(gateway, state, to_escalate, outcomes, run_id)
        except (ProviderError, BudgetExceeded):
            escalated = {}  # keep Jev's answers, still marked uncertain
        claude_ms = int((time.monotonic() - started) * 1000)
        outcomes.update(escalated)

    with Session(engine) as s:
        for a in asked:
            o = outcomes[a.key]
            s.add(
                Judgment(
                    run_id=run_id or "",
                    turn_id=turn_id,
                    subject=a.subject or a.key,
                    question_id=a.entry.id,
                    question_version=a.entry.version,
                    provider=o.provider,
                    answer={
                        "value": o.value,
                        "probabilities": o.probabilities,
                        "rationale": o.rationale,
                        "model": result.model,
                    },
                    confidence=o.confidence,
                    uncertain=o.uncertain,
                    escalated=o.escalated,
                    latency_ms=claude_ms if o.escalated else jev_ms,
                )
            )
        s.commit()
    return outcomes


async def _escalate(
    gateway: Gateway,
    state: SafeText,
    asked: list[Asked],
    jev: dict[str, Outcome],
    run_id: str | None,
) -> dict[str, Outcome]:
    listing = join([_describe(a) for a in asked], "\n")
    jev_view = join(
        [
            TrustedText("- `{k}`: {v} (confidence {c})").render(
                k=label(a.key),
                v=label(round(v, 3) if isinstance(v := jev[a.key].value, float) else v),
                c=label(jev[a.key].confidence),
            )
            for a in asked
        ],
        "\n",
    )
    user = join(
        [
            fence("material", state),
            TrustedText("Questions:"),
            listing,
            TrustedText("The fast classifier's uncertain answers, for context:"),
            jev_view,
        ]
    )
    result = await gateway.generate(
        "escalation",
        [Message("system", prompt("escalation")), Message("user", user)],
        _Escalation,
        run_id=run_id,
    )
    parsed = result.parsed if isinstance(result.parsed, _Escalation) else _Escalation(answers=[])
    by_key = {a.key: a for a in asked}
    out: dict[str, Outcome] = {}
    for item in parsed.answers:
        a = by_key.get(item.key)
        if a is None:
            continue
        value = _parse_escalated(a, item.answer)
        if value is None:
            continue
        out[a.key] = Outcome(
            key=a.key,
            question_id=a.entry.id,
            kind=a.question.kind,
            value=value,
            confidence=None,
            uncertain=False,
            escalated=True,
            provider="claude",
            probabilities=jev[a.key].probabilities,
            rationale=item.rationale,
        )
    return out
