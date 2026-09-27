"""Claude provider, using the official ``anthropic`` SDK.

Retries are done by the gateway (so every provider retries the same way), so the SDK's own
retries are switched off. Structured output uses ``messages.parse(output_format=Model)``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import anthropic
import httpx2
from pydantic import BaseModel

from app.llm.base import unsupported
from app.llm.config import RoleConfig
from app.llm.errors import ProviderError, TransientProviderError, UnsafeTextError
from app.llm.text import SafeText
from app.llm.types import EmbedResult, GenerateResult, JudgeQuestion, JudgeResult, Message, Usage

_TRANSIENT = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)


def _safe(value: SafeText | str) -> str:
    if not isinstance(value, SafeText):
        raise UnsafeTextError("anthropic provider received plain text; pseudonymise it first")
    return value.text


class AnthropicProvider:
    name = "anthropic"
    external = True

    def __init__(self, api_key: str, http_client: httpx2.AsyncClient | None = None) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, max_retries=0, http_client=http_client
        )

    async def generate(
        self, role: RoleConfig, messages: Sequence[Message], schema: type[BaseModel] | None
    ) -> GenerateResult:
        system = "\n\n".join(_safe(m.content) for m in messages if m.role == "system")
        convo: list[Any] = [
            {"role": m.role, "content": _safe(m.content)} for m in messages if m.role != "system"
        ]
        kwargs: dict[str, Any] = {
            "model": role.model,
            "max_tokens": role.max_tokens,
            "messages": convo,
            "timeout": role.timeout_s,
        }
        if system:
            kwargs["system"] = system
        effort = role.options.get("effort")
        if effort:
            kwargs["output_config"] = {"effort": effort}

        try:
            if schema is not None:
                response: Any = await self._client.messages.parse(output_format=schema, **kwargs)
            else:
                response = await self._client.messages.create(**kwargs)
        except _TRANSIENT as e:
            raise TransientProviderError(f"Claude {type(e).__name__}") from e
        except anthropic.APIError as e:
            raise ProviderError(f"Claude {type(e).__name__}: {e}") from e

        if response.stop_reason == "refusal":
            raise ProviderError("Claude declined the request (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            raise ProviderError(f"Claude hit max_tokens={role.max_tokens} for model {role.model}")

        text = "".join(b.text for b in response.content if b.type == "text")
        parsed = getattr(response, "parsed_output", None) if schema is not None else None
        if schema is not None and parsed is None:
            raise ProviderError(f"Claude output did not match {schema.__name__}")
        usage = Usage(
            tokens_in=response.usage.input_tokens, tokens_out=response.usage.output_tokens
        )
        return GenerateResult(text=text, parsed=parsed, model=response.model, usage=usage)

    async def judge(
        self, role: RoleConfig, state: SafeText, questions: dict[str, JudgeQuestion]
    ) -> JudgeResult:
        raise unsupported(self.name, "judge")  # escalations use generate() with a schema

    async def embed(self, role: RoleConfig, texts: Sequence[SafeText | str]) -> EmbedResult:
        raise unsupported(self.name, "embed")

    async def ping(self) -> bool:
        return True  # reachability is checked by /healthz with a real call, not here

    async def reachable(self) -> bool:
        """Lists models: authenticated, no tokens used."""
        try:
            await self._client.models.list(limit=1)
        except anthropic.APIError:
            return False
        return True

    async def aclose(self) -> None:
        await self._client.close()
