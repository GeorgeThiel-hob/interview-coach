"""Jev provider, using the official ``typesafe-sdk`` (see docs/vendor/typesafe/).

``AsyncTypeSafeClient.system_one(state, questions, model=...)`` returns answers grouped by
type: ``.nouls[name].noul`` (probability 0-1, no confidence), ``.choices[name].choice`` /
``.confidence`` / ``.probabilities`` and ``.scores[name].score`` (expected level) /
``.confidence`` / ``.probabilities``. ``response.model`` is the versioned model that answered.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx2
import typesafe_sdk as ts
from pydantic import BaseModel

from app.llm.base import unsupported
from app.llm.config import RoleConfig
from app.llm.errors import ProviderError, TransientProviderError, UnsafeTextError
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

_TRANSIENT = (
    ts.TypeSafeRateLimitError,
    ts.TypeSafeAPITimeoutError,
    ts.TypeSafeAPIConnectionError,
    ts.TypeSafeInternalServerError,
)


def _safe(value: SafeText | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, SafeText):
        raise UnsafeTextError("typesafe provider received plain text; pseudonymise it first")
    return value.text


def _to_sdk(question: JudgeQuestion) -> ts.Noul | ts.Choice | ts.Score:
    instructions = _safe(question.instructions)
    if question.kind == "noul":
        return ts.Noul(instructions=instructions)
    if question.kind == "choice":
        if not isinstance(question.criteria, dict) or not question.criteria:
            raise ProviderError("choice question needs a non-empty {option: description} dict")
        return ts.Choice(
            instructions=instructions,
            criteria={k: _safe(v) for k, v in question.criteria.items()},
        )
    if not isinstance(question.criteria, list) or not question.criteria:
        raise ProviderError("score question needs a non-empty list of level descriptions")
    return ts.Score(instructions=instructions, criteria=[_safe(c) for c in question.criteria])


class TypeSafeProvider:
    name = "typesafe"
    external = True

    def __init__(self, api_key: str, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._client = ts.AsyncTypeSafeClient(
            api_key=api_key, retry=ts.RetryPolicy(max_retries=0), transport=transport
        )

    async def judge(
        self, role: RoleConfig, state: SafeText, questions: dict[str, JudgeQuestion]
    ) -> JudgeResult:
        state_text = _safe(state)
        sdk_questions: dict[str, Any] = {qid: _to_sdk(q) for qid, q in questions.items()}
        try:
            response = await self._client.system_one(
                state_text or "", sdk_questions, model=role.model, timeout=role.timeout_s
            )
        except _TRANSIENT as e:
            raise TransientProviderError(f"Jev {type(e).__name__}") from e
        except ts.TypeSafeError as e:
            raise ProviderError(f"Jev {type(e).__name__}: {e}") from e

        answers: dict[str, JudgeAnswer] = {}
        for qid, q in questions.items():
            if q.kind == "noul" and qid in response.nouls:
                n = response.nouls[qid]
                answers[qid] = JudgeAnswer(kind="noul", value=float(n.noul), confidence=None)
            elif q.kind == "choice" and qid in response.choices:
                c = response.choices[qid]
                answers[qid] = JudgeAnswer(
                    kind="choice",
                    value=str(c.choice),
                    confidence=float(c.confidence),
                    probabilities={str(k): float(v) for k, v in c.probabilities.items()},
                )
            elif q.kind == "score" and qid in response.scores:
                s = response.scores[qid]
                answers[qid] = JudgeAnswer(
                    kind="score",
                    value=float(s.score),
                    confidence=float(s.confidence),
                    probabilities={str(k): float(v) for k, v in s.probabilities.items()},
                )
            else:
                raise ProviderError(f"Jev returned no {q.kind} answer for question {qid!r}")
        usage = Usage(
            tokens_in=response.usage.input_tokens or 0,
            tokens_out=response.usage.output_tokens or 0,
        )
        return JudgeResult(answers=answers, model=response.model, usage=usage)

    async def generate(
        self, role: RoleConfig, messages: Sequence[Message], schema: type[BaseModel] | None
    ) -> GenerateResult:
        raise unsupported(self.name, "generate")

    async def embed(self, role: RoleConfig, texts: Sequence[SafeText | str]) -> EmbedResult:
        raise unsupported(self.name, "embed")

    async def ping(self) -> bool:
        return True

    async def reachable(self) -> bool:
        """Lists models: authenticated, no tokens used."""
        try:
            await self._client.models.list()
        except ts.TypeSafeError:
            return False
        return True

    async def aclose(self) -> None:
        await self._client.aclose()
