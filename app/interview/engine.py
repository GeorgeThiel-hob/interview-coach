"""The interview run loop (spec 5.3, 5.4).

Per candidate answer:
1. pseudonymise the answer (same per-run mapping as the documents) and store the turn;
2. a fast Jev ``next_move`` call decides the interviewer's move; code enforces the limits
   (max follow-ups per topic, time budget, closing topic);
3. the full answer evaluation (section 7.4, with escalation) runs in the background;
4. the local model writes the next question, which must pass the Jev guardrails before it is
   shown: regenerate once with the failure reason, then escalate to Claude, then fall back to
   a safe question. Every guardrail event is logged.

State lives in ``runs.interview_state`` and every turn is stored immediately, so a crash or
refresh loses nothing and the run can resume.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import Event, PlanTopic, Requirement, Run, Turn
from app.ingest.pseudonymise import pseudonymise, stored
from app.ingest.service import chunks, load_mapping, save_mapping
from app.interview.evaluation import evaluate_answer
from app.judgments.cascade import Asked, Outcome, ask, thresholds
from app.judgments.catalog import GUARDRAIL_IDS, get
from app.llm.errors import BudgetExceeded, ProviderError
from app.llm.gateway import Gateway
from app.llm.prompts import prompt
from app.llm.text import SafeText, TrustedText, fence, join, label
from app.llm.types import Message
from app.prep.plan import interview_config

MOVES = ("open", "probe_deeper", "challenge", "clarify", "next_topic")
_MOVE_INSTRUCTIONS = {
    "open": TrustedText("Open this topic with a first question."),
    "probe_deeper": TrustedText(
        "Probe deeper into the last answer: ask for missing detail, e.g. the concrete "
        "situation, their own actions or the result."
    ),
    "challenge": TrustedText(
        "Politely challenge the last answer: it may overclaim or conflict with the CV."
    ),
    "clarify": TrustedText(
        "Ask a short clarifying question about the ambiguous part of the last answer."
    ),
}
_FALLBACK = {
    "nl": "Kun je daar een concreet voorbeeld van geven?",
    "en": "Could you give a concrete example of that?",
}
_CLOSING_FALLBACK = {
    "nl": "Welke vragen heb jij nog voor ons?",
    "en": "What questions do you have for us?",
}


@dataclass(frozen=True)
class AnswerResult:
    next_question: Turn | None
    finished: bool
    move: str


def two_sentences(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip().strip('"').strip())
    text = re.sub(r"^(interviewer|vraag|question)\s*:\s*", "", text, flags=re.I)
    parts = re.split(r"(?<=[.?!])\s+", text)
    return " ".join(parts[:2]).strip()


def follow_up_fits(
    *,
    elapsed_s: float,
    exchanges_done: int,
    topics_left: int,
    budget_s: float,
    min_exchange_s: float,
) -> bool:
    """True if one more follow-up still leaves an exchange for every remaining topic.

    The time per exchange is the candidate's own pace so far, never less than the configured
    minimum: slow, thorough answers must not use up the time of the topics still to come.
    """
    per = max(min_exchange_s, elapsed_s / exchanges_done if exchanges_done else 0.0)
    return budget_s - elapsed_s - topics_left * per >= per


class InterviewEngine:
    def __init__(self, gateway: Gateway, engine: Engine, run_id: str, pii_key: str) -> None:
        self.gateway = gateway
        self.db = engine
        self.run_id = run_id
        self.pii_key = pii_key
        self._background: set[asyncio.Task[Any]] = set()
        self.cfg = interview_config()

    # ------------------------------------------------------------------ state helpers

    def _run(self) -> Run:
        with Session(self.db) as s:
            run = s.get(Run, self.run_id)
        if run is None:
            raise ValueError(f"unknown run {self.run_id}")
        return run

    def _save_state(self, **changes: Any) -> dict[str, Any]:
        with Session(self.db) as s:
            run = s.get(Run, self.run_id)
            assert run is not None
            state = {**run.interview_state, **changes}
            run.interview_state = state
            s.add(run)
            s.commit()
        return state

    def topics(self) -> list[PlanTopic]:
        with Session(self.db) as s:
            rows = s.exec(select(PlanTopic).where(PlanTopic.run_id == self.run_id)).all()
        return sorted(rows, key=lambda t: t.order)

    def turns(self) -> list[Turn]:
        with Session(self.db) as s:
            rows = s.exec(select(Turn).where(Turn.run_id == self.run_id)).all()
        return sorted(rows, key=lambda t: t.seq)

    def _add_turn(self, **fields: Any) -> Turn:
        with Session(self.db) as s:
            turn = Turn(run_id=self.run_id, seq=len(self.turns()) + 1, **fields)
            s.add(turn)
            s.commit()
            s.refresh(turn)
        return turn

    def _event(self, kind: str, detail: str | None = None) -> None:
        with Session(self.db) as s:
            s.add(Event(run_id=self.run_id, kind=kind, detail=detail))
            s.commit()

    def _set_status(self, status: str) -> None:
        with Session(self.db) as s:
            run = s.get(Run, self.run_id)
            assert run is not None
            run.status = status
            s.add(run)
            s.commit()

    @property
    def language(self) -> str:
        return str(self._run().settings.get("language", "nl"))

    def pending_question(self) -> Turn | None:
        turns = self.turns()
        return turns[-1] if turns and turns[-1].role == "interviewer" else None

    # ------------------------------------------------------------------ public API

    async def start(self) -> Turn:
        """First question, or the unanswered question when resuming."""
        pending = self.pending_question()
        if pending:
            self._save_state(resumed_at=time.time())
            self._set_status("interviewing")
            return pending
        topics = self.topics()
        if not topics:
            raise ValueError("the run has no interview plan")
        self._save_state(
            topic_index=0,
            follow_ups=0,
            elapsed_s=0.0,
            exchanges=0,
            resumed_at=time.time(),
            finished=False,
        )
        self._set_status("interviewing")
        return await self._ask(topics[0], "open")

    def pause(self) -> None:
        state = self._run().interview_state
        elapsed = (
            float(state.get("elapsed_s", 0.0))
            + time.time()
            - float(state.get("resumed_at", time.time()))
        )
        self._save_state(elapsed_s=elapsed, resumed_at=None)
        self._set_status("paused")

    async def answer(self, text: str, *, audio_duration_s: float | None = None) -> AnswerResult:
        question = self.pending_question()
        if question is None:
            raise ValueError("there is no open question to answer")
        state = self._run().interview_state
        topics = self.topics()
        topic = topics[int(state.get("topic_index", 0))]

        mapping = load_mapping(self.db, self.run_id, self.pii_key)
        safe_answer = await pseudonymise(self.gateway, text, mapping, run_id=self.run_id)
        save_mapping(self.db, self.run_id, mapping, self.pii_key)
        answer_turn = self._add_turn(
            topic_id=topic.id,
            role="candidate",
            text_pseudonymised=safe_answer.text,
            audio_duration_s=audio_duration_s,
        )

        context = self._evaluation_state(topic, question, safe_answer)
        self._spawn(
            evaluate_answer(
                self.gateway,
                self.db,
                self.run_id,
                answer_turn.id,
                topic,
                context,
                self._linked_requirements(topic),
            )
        )
        exchanges = int(state.get("exchanges", 0)) + 1
        elapsed = (
            float(state.get("elapsed_s", 0.0))
            + time.time()
            - float(state.get("resumed_at") or time.time())
        )
        move = await self._decide_move(context, answer_turn, topic, state, elapsed, exchanges)
        self._save_state(exchanges=exchanges, elapsed_s=elapsed, resumed_at=time.time())

        index = int(state.get("topic_index", 0))
        if topic.question_type == "closing" and move == "next_topic":
            return self._finish(move)
        if move == "next_topic":
            index = self._next_topic_index(index, topics, elapsed, exchanges)
            self._save_state(topic_index=index, follow_ups=0)
            return AnswerResult(await self._ask(topics[index], "open"), False, move)
        self._save_state(follow_ups=int(state.get("follow_ups", 0)) + 1)
        return AnswerResult(await self._ask(topic, move), False, move)

    async def drain(self) -> None:
        """Wait for background evaluations (call before building the review/report)."""
        if self._background:
            await asyncio.gather(*self._background, return_exceptions=True)

    # ------------------------------------------------------------------ internals

    def _finish(self, move: str) -> AnswerResult:
        self._save_state(finished=True, resumed_at=None)
        self._set_status("reviewing")
        return AnswerResult(None, True, move)

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _budget(self) -> tuple[float, int]:
        minutes = float(self._run().settings.get("length", 30))
        per = float(self.cfg["minutes_per_exchange"])
        return minutes * 60, max(2, int(minutes / per))

    def _next_topic_index(
        self, index: int, topics: list[PlanTopic], elapsed: float, exchanges: int
    ) -> int:
        seconds, max_exchanges = self._budget()
        closing = len(topics) - 1
        if elapsed >= seconds or exchanges >= max_exchanges - 1:
            return closing  # out of time: go to the closing topic
        return min(index + 1, closing)

    async def _decide_move(
        self,
        context: SafeText,
        answer_turn: Turn,
        topic: PlanTopic,
        state: dict[str, Any],
        elapsed: float,
        done: int,
    ) -> str:
        entry = get("next_move")
        try:
            out = await ask(
                self.gateway,
                self.db,
                context,
                [Asked("next_move", entry, entry.build())],
                run_id=self.run_id,
                turn_id=answer_turn.id,
                allow_escalation=False,
            )
            outcome: Outcome | None = out["next_move"]
        except (ProviderError, BudgetExceeded):
            outcome = None
        follow_ups = int(state.get("follow_ups", 0))
        if outcome is None or outcome.uncertain:
            move = "probe_deeper" if follow_ups == 0 else "next_topic"
        else:
            move = str(outcome.value)
        if topic.question_type == "closing":
            # one follow-up at most in the closing topic, then finish
            return (
                "next_topic" if follow_ups >= 1 else ("clarify" if move != "next_topic" else move)
            )
        if move != "next_topic" and follow_ups >= int(self.cfg["max_follow_ups_per_topic"]):
            return "next_topic"
        seconds, max_exchanges = self._budget()
        if move != "next_topic" and (elapsed >= seconds or done >= max_exchanges):
            return "next_topic"
        # follow-ups only while every remaining planned topic still fits in the time budget,
        # counted in exchanges and in time at the candidate's own pace
        topics_left = len(self.topics()) - 1 - int(state.get("topic_index", 0))
        if move != "next_topic" and max_exchanges - done <= topics_left:
            return "next_topic"
        if move != "next_topic" and not follow_up_fits(
            elapsed_s=elapsed,
            exchanges_done=done,
            topics_left=topics_left,
            budget_s=seconds,
            min_exchange_s=float(self.cfg["minutes_per_exchange"]) * 60,
        ):
            return "next_topic"
        return move

    def _linked_requirements(self, topic: PlanTopic) -> list[Requirement]:
        if not topic.requirement_ids:
            return []
        with Session(self.db) as s:
            rows = s.exec(select(Requirement).where(Requirement.run_id == self.run_id)).all()
        return [r for r in rows if r.id in topic.requirement_ids]

    def _evidence_text(self, topic: PlanTopic) -> str:
        reqs = self._linked_requirements(topic)
        refs = {ref for r in reqs for ref in r.evidence_refs}
        cv = chunks(self.db, self.run_id, "cv:")
        picked = [c for c in cv if c.chunk_ref in refs] or cv[:6]
        return "\n".join(f"[{c.chunk_ref}] {c.text_pseudonymised}" for c in picked)

    def _evaluation_state(self, topic: PlanTopic, question: Turn, answer: SafeText) -> SafeText:
        reqs = self._linked_requirements(topic)
        return join(
            [
                fence("interview_question", stored(question.text_pseudonymised)),
                fence("candidate_answer", answer),
                fence("planned_topic", stored(topic.goal)),
                fence(
                    "linked_requirements",
                    stored("\n".join(f"{r.id}: {r.text}" for r in reqs) or "none"),
                ),
                fence("cv_evidence", stored(self._evidence_text(topic))),
            ]
        )

    def _conversation(self) -> str:
        turns = self.turns()
        n = int(self.cfg["history_turns"])
        older, recent = turns[:-n], turns[-n:]
        lines = []
        if older:
            lines.append(f"(earlier: {len(older)} turns about previous topics)")
        for t in recent:
            who = "Interviewer" if t.role == "interviewer" else "Candidate"
            lines.append(f"{who}: {t.text_pseudonymised}")
        return "\n".join(lines) or "(no conversation yet)"

    def _question_context(self, topic: PlanTopic) -> SafeText:
        run = self._run()
        ctx = run.context or {}
        reqs = self._linked_requirements(topic)
        return join(
            [
                fence(
                    "vacancy",
                    stored(
                        f"{ctx.get('title', '')} - {ctx.get('organisation', '')}\n"
                        f"{ctx.get('summary', '')}"
                    ),
                ),
                fence(
                    "topic",
                    stored(
                        f"goal: {topic.goal}\ntype: {topic.question_type}\n"
                        f"requirements: {'; '.join(r.text for r in reqs) or 'none'}\n"
                        f"possible angles: {'; '.join(topic.follow_up_angles) or 'none'}"
                    ),
                ),
                fence("cv_fragments", stored(self._evidence_text(topic))),
                fence("conversation", stored(self._conversation())),
            ]
        )

    def _system(self, topic: PlanTopic) -> SafeText:
        s = self._run().settings
        return join(
            [
                prompt("interviewer"),
                prompt(f"personas/{topic.persona}"),
                TrustedText("Interview language: {lang}. Difficulty: {d}.").render(
                    lang=label({"nl": "Dutch", "en": "English"}.get(self.language, "Dutch")),
                    d=label(s.get("difficulty", "realistic")),
                ),
            ]
        )

    async def _generate(
        self, topic: PlanTopic, move: str, feedback: str | None, role: str = "interviewer"
    ) -> str:
        instruction = TrustedText("Next move: {m}.").render(m=label(move))
        parts = [
            self._question_context(topic),
            instruction,
            _MOVE_INSTRUCTIONS.get(move, _MOVE_INSTRUCTIONS["open"]),
        ]
        if feedback:
            parts.append(
                TrustedText(
                    "Your previous attempt was rejected because it failed "
                    "these checks; write a new question that passes them:"
                )
            )
            parts.append(TrustedText("{f}").render(f=label(feedback)))
        out = await self.gateway.generate(
            role,
            [Message("system", self._system(topic)), Message("user", join(parts))],
            run_id=self.run_id,
        )
        return two_sentences(out.text)

    async def _guardrails(self, topic: PlanTopic, question: str) -> list[str]:
        state = join([self._question_context(topic), fence("question_to_check", stored(question))])
        asked = [Asked(q, get(q), get(q).build()) for q in GUARDRAIL_IDS]
        out = await ask(
            self.gateway, self.db, state, asked, run_id=self.run_id, allow_escalation=False
        )
        need = thresholds()["guardrail_pass"]
        return [q for q in GUARDRAIL_IDS if float(out[q].value) < float(need[q])]

    async def _ask(self, topic: PlanTopic, move: str) -> Turn:
        question = ""
        if move == "open" and topic.opening_question:
            question = two_sentences(topic.opening_question)
        failed: list[str] = []
        attempts = [
            ("interviewer", None),
            ("interviewer", "retry"),
            ("interviewer_escalation", "retry"),
        ]
        for i, (role, retry) in enumerate(attempts):
            if not question or retry:
                try:
                    question = await self._generate(
                        topic, move, ",".join(failed) if retry else None, role
                    )
                except ProviderError:
                    question = ""
            if question:
                failed = await self._guardrails(topic, question)
                if not failed:
                    if i == 1:
                        self._event("question_regenerated")
                    elif i == 2:
                        self._event("question_escalated")
                    break
            question = ""
            if i == 0:
                self._event("question_failed_guardrails", ",".join(failed))
        if not question:
            self._event("question_blocked", ",".join(failed))
            fallback = _CLOSING_FALLBACK if topic.question_type == "closing" else _FALLBACK
            question = fallback.get(self.language, fallback["en"])
        return self._add_turn(
            topic_id=topic.id,
            role="interviewer",
            persona=topic.persona,
            text_pseudonymised=question,
            next_move=move,
        )
