"""Provider-neutral request and result types used by the gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from app.llm.text import SafeText

Role = Literal["system", "user", "assistant"]
MessageContent = SafeText | str  # plain str is only accepted by local providers


@dataclass(frozen=True)
class Message:
    role: Role
    content: MessageContent


@dataclass(frozen=True)
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass(frozen=True)
class GenerateResult:
    text: str
    parsed: BaseModel | None
    model: str
    usage: Usage


QuestionKind = Literal["noul", "choice", "score"]


@dataclass(frozen=True)
class JudgeQuestion:
    """One typed question. ``criteria`` is a {name: description} dict for Choice and an
    ordered list of level descriptions for Score; Noul takes none."""

    kind: QuestionKind
    instructions: SafeText
    criteria: dict[str, SafeText | None] | list[SafeText] | None = None


@dataclass(frozen=True)
class JudgeAnswer:
    kind: QuestionKind
    # noul: probability of "yes" (0-1); choice: the winning option; score: expected level
    value: float | str
    # None for noul (Jev reports none; use the uncertainty band in config/thresholds.yaml)
    confidence: float | None
    probabilities: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class JudgeResult:
    answers: dict[str, JudgeAnswer]
    model: str  # the versioned model that answered, as reported by the provider
    usage: Usage
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EmbedResult:
    vectors: list[list[float]]
    model: str
    usage: Usage
