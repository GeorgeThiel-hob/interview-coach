"""Deterministic stand-ins for the three providers, for end-to-end tests without network.

They answer by the requested schema's class name, so pipeline code runs unchanged.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel

from app.llm.config import RoleConfig
from app.llm.text import SafeText
from app.llm.types import (
    EmbedResult,
    GenerateResult,
    JudgeAnswer,
    JudgeQuestion,
    JudgeResult,
    Message,
    Usage,
)

Handler = Callable[[Sequence[Message], type[BaseModel]], dict[str, Any]]


def _text(m: Message) -> str:
    return m.content.text if isinstance(m.content, SafeText) else m.content


def all_text(messages: Sequence[Message]) -> str:
    return "\n".join(_text(m) for m in messages)


class FakeProvider:
    def __init__(self, name: str, external: bool, handlers: dict[str, Handler] | None = None):
        self.name = name
        self.external = external
        self.handlers = handlers or {}
        self.calls: list[tuple[str, Any]] = []
        self.online = True

    async def generate(
        self, role: RoleConfig, messages: Sequence[Message], schema: type[BaseModel] | None
    ) -> GenerateResult:
        self.calls.append(("generate", (role.model, schema.__name__ if schema else None)))
        if schema is None:
            handler = self.handlers.get("text")
            text = str(handler(messages, BaseModel)["text"]) if handler else "Wat heb je gedaan?"
            return GenerateResult(text, None, role.model, Usage(100, 12))
        handler = self.handlers.get(schema.__name__)
        if handler is None:
            raise AssertionError(f"{self.name} has no fake handler for {schema.__name__}")
        parsed = schema.model_validate(handler(messages, schema))
        return GenerateResult(parsed.model_dump_json(), parsed, role.model, Usage(200, 50))

    async def judge(
        self, role: RoleConfig, state: SafeText, questions: dict[str, JudgeQuestion]
    ) -> JudgeResult:
        self.calls.append(("judge", sorted(questions)))
        handler = self.handlers.get("judge")
        answers = {}
        for key, q in questions.items():
            override = handler(key, q, state) if handler else None
            answers[key] = override or default_answer(q)
        return JudgeResult(answers, "jev-1.13.0", Usage(300, 20))

    async def embed(self, role: RoleConfig, texts: Sequence[SafeText | str]) -> EmbedResult:
        self.calls.append(("embed", len(texts)))
        return EmbedResult(
            [bow_vector(t.text if isinstance(t, SafeText) else t) for t in texts],
            role.model,
            Usage(10 * len(texts), 0),
        )

    async def ping(self) -> bool:
        return self.online

    async def reachable(self) -> bool:
        return await self.ping()

    async def aclose(self) -> None:
        return None


def default_answer(q: JudgeQuestion) -> JudgeAnswer:
    if q.kind == "noul":
        return JudgeAnswer("noul", 0.8, None)
    if q.kind == "choice":
        assert isinstance(q.criteria, dict)
        first = next(iter(q.criteria))
        return JudgeAnswer(
            "choice",
            first,
            0.9,
            {k: (0.9 if k == first else 0.1 / (len(q.criteria) - 1)) for k in q.criteria},
        )
    assert isinstance(q.criteria, list)
    top = len(q.criteria) - 2 if len(q.criteria) > 2 else 0
    return JudgeAnswer(
        "score",
        float(top),
        0.9,
        {str(i): (0.9 if i == top else 0.0) for i in range(len(q.criteria))},
    )


def bow_vector(text: str, dims: int = 64) -> list[float]:
    vec = [0.0] * dims
    for word in re.findall(r"[a-zà-ÿ]{3,}", text.lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dims] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


# ---------------------------------------------------------------- default handlers


def local_handlers(people: dict[str, str] | None = None) -> dict[str, Handler]:
    people = people or {}

    def entities(messages: Sequence[Message], _: type[BaseModel]) -> dict[str, Any]:
        text = _text(messages[-1])
        return {"entities": [{"text": p, "type": t} for p, t in people.items() if p in text]}

    def extraction(messages: Sequence[Message], _: type[BaseModel]) -> dict[str, Any]:
        items = []
        for ref, kind, body in re.findall(
            r"\[(vac:[bp]\d+)\]\s*(Eis|Wens|Taak):\s*(.+)", all_text(messages)
        ):
            items.append(
                {
                    "kind": {"Eis": "eis", "Wens": "wens", "Taak": "responsibility"}[kind],
                    "text": body.strip(),
                    "source_ref": ref,
                }
            )
        return {
            "context": {"title": "AI Developer", "organisation": "Overheid", "summary": "Test."},
            "items": items,
        }

    counter = {"n": 0}

    def question(messages: Sequence[Message], _: type[BaseModel]) -> dict[str, Any]:
        counter["n"] += 1
        return {"text": f"Kun je voorbeeld {counter['n']} geven van wat je precies deed?"}

    return {"_Entities": entities, "Extraction": extraction, "text": question}


def claude_handlers() -> dict[str, Handler]:
    def plan(messages: Sequence[Message], _: type[BaseModel]) -> dict[str, Any]:
        text = all_text(messages)
        ids = sorted(set(re.findall(r"\b(eis_\d+)\b", text)))
        focus = (
            re.findall(r"^- ([a-z_0-9]+): ", text.split('name="focus_items"')[-1], re.M)
            if 'name="focus_items"' in text
            else []
        )
        focus_topics = [
            {
                "goal": f"Hertoets {f}",
                "question_type": "behavioural",
                "persona": "hiring_manager",
                "opening_question": f"Nieuwe vraag: vertel over een ander project ({f}).",
                "requirement_ids": [],
                "focus_item_id": f,
            }
            for f in focus
        ]
        topics = [
            *focus_topics,
            {
                "goal": "Motivatie",
                "question_type": "motivation",
                "persona": "intake_account_manager",
                "opening_question": "Waarom deze functie?",
                "requirement_ids": [],
            },
        ]
        # deliberately leave the last eis uncovered, so the enforcement rule is exercised
        for rid in ids[:-1]:
            topics.append(
                {
                    "goal": f"Toets {rid}",
                    "question_type": "behavioural",
                    "persona": "technical_lead",
                    "opening_question": f"Vertel over {rid}.",
                    "requirement_ids": [rid, "eis_999"],
                    "follow_up_angles": ["resultaat"],
                }
            )
        return {"topics": topics}

    def briefing(messages: Sequence[Message], _: type[BaseModel]) -> dict[str, Any]:
        return {
            "likely_questions": ["Waarom deze rol?"],
            "strongest_evidence": [
                {
                    "requirement_id": "eis_1",
                    "summary": "Python pipeline",
                    "chunk_refs": ["cv:role1:b1", "cv:made_up"],
                }
            ],
            "gaps": [{"requirement_id": "eis_2", "advice": "Wees eerlijk."}],
            "prepare": ["a", "b", "c", "d"],
        }

    def escalation(messages: Sequence[Message], _: type[BaseModel]) -> dict[str, Any]:
        keys = re.findall(r"- id `([^`]+)` \((noul|choice|score)\)", all_text(messages))
        answers = []
        for key, kind in keys:
            answers.append(
                {
                    "key": key,
                    "rationale": "Claude decided.",
                    "answer": {"noul": "yes", "score": "2"}.get(kind, "consistent"),
                }
            )
        return {"answers": answers}

    def feedback(messages: Sequence[Message], _: type[BaseModel]) -> dict[str, Any]:
        turn = re.search(r"\[(turn:[0-9a-f]+)\]", all_text(messages))
        ref = turn.group(1) if turn else "turn:0"
        return {
            "strengths": [{"text": "Je noemde de pipeline.", "sources": [ref]}],
            "add": [
                {"text": "Je noemde CI/CD niet.", "sources": ["cv:role1:b2"]},
                {"text": "Verzonnen ervaring.", "sources": ["cv:nope"]},
            ],
            "explore": [
                {"text": "Heb je een voorbeeld met monitoring?", "sources": []},
                {"text": "Je hebt vast monitoring gedaan.", "sources": []},
            ],
            "outline": [{"text": "Situatie: 40 miljoen metingen", "sources": ["cv:role1:b1", ref]}],
        }

    def practice(messages: Sequence[Message], _: type[BaseModel]) -> dict[str, Any]:
        turn = re.search(r"(turn:[0-9a-f]+)", all_text(messages))
        return {
            "actions": [
                {
                    "action": "Oefen STAR met resultaat",
                    "why": "R ontbreekt vaak",
                    "links": [
                        "tip:star",
                        "stat:quantified_rate",
                        turn.group(1) if turn else "x",
                        "turn:bogus",
                    ],
                },
            ]
        }

    return {
        "PlanOut": plan,
        "BriefingOut": briefing,
        "_Escalation": escalation,
        "FeedbackOut": feedback,
        "PracticePlanOut": practice,
    }
