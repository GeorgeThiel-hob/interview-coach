"""The interface every provider implements. Only the gateway talks to providers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel

from app.llm.config import RoleConfig
from app.llm.errors import ProviderError
from app.llm.text import SafeText
from app.llm.types import EmbedResult, GenerateResult, JudgeQuestion, JudgeResult, Message


class Provider(Protocol):
    name: str
    external: bool  # True -> data leaves the server; only SafeText is allowed

    async def generate(
        self, role: RoleConfig, messages: Sequence[Message], schema: type[BaseModel] | None
    ) -> GenerateResult: ...

    async def judge(
        self, role: RoleConfig, state: SafeText, questions: dict[str, JudgeQuestion]
    ) -> JudgeResult: ...

    async def embed(self, role: RoleConfig, texts: Sequence[SafeText | str]) -> EmbedResult: ...

    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


def unsupported(provider: str, operation: str) -> ProviderError:
    return ProviderError(f"provider {provider!r} does not support {operation}")
