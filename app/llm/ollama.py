"""Ollama provider (the local Qwen + embedding model on the laptop).

Uses the Ollama HTTP API directly: ``POST /api/chat`` (``format`` takes a JSON schema for
structured output), ``POST /api/embed`` and ``GET /api/tags`` as a reachability check.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.llm.base import unsupported
from app.llm.config import RoleConfig
from app.llm.errors import LocalModelOffline, ProviderError, TransientProviderError
from app.llm.text import SafeText
from app.llm.types import (
    EmbedResult,
    GenerateResult,
    JudgeQuestion,
    JudgeResult,
    Message,
    Usage,
)

# Ollama-specific request fields; everything else in role.options goes into "options"
_TOP_LEVEL_OPTIONS = frozenset({"think", "keep_alive"})


def _text(value: SafeText | str) -> str:
    return value.text if isinstance(value, SafeText) else value


class OllamaProvider:
    name = "ollama"
    external = False

    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, transport=transport)

    async def _post(self, path: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=body, timeout=timeout)
        except httpx.ConnectError as e:
            raise LocalModelOffline(f"Ollama unreachable at {self._client.base_url}") from e
        except httpx.TimeoutException as e:
            raise TransientProviderError(f"Ollama timed out on {path}") from e
        except httpx.TransportError as e:
            raise TransientProviderError(f"Ollama transport error on {path}: {e}") from e
        if response.status_code >= 500 or response.status_code == 429:
            raise TransientProviderError(f"Ollama {path} returned {response.status_code}")
        if response.status_code >= 400:
            raise ProviderError(f"Ollama {path} returned {response.status_code}: {response.text}")
        data: dict[str, Any] = response.json()
        return data

    async def generate(
        self, role: RoleConfig, messages: Sequence[Message], schema: type[BaseModel] | None
    ) -> GenerateResult:
        body: dict[str, Any] = {
            "model": role.model,
            "messages": [{"role": m.role, "content": _text(m.content)} for m in messages],
            "stream": False,
        }
        options = dict(role.options)
        for key in _TOP_LEVEL_OPTIONS & options.keys():
            body[key] = options.pop(key)
        if options:
            body["options"] = options
        if schema is not None:
            body["format"] = schema.model_json_schema()

        data = await self._post("/api/chat", body, role.timeout_s)
        text = str(data.get("message", {}).get("content", ""))
        parsed: BaseModel | None = None
        if schema is not None:
            try:
                parsed = schema.model_validate_json(text)
            except ValidationError as e:
                raise ProviderError(f"Ollama output did not match {schema.__name__}: {e}") from e
        usage = Usage(
            tokens_in=int(data.get("prompt_eval_count", 0)),
            tokens_out=int(data.get("eval_count", 0)),
        )
        return GenerateResult(
            text=text, parsed=parsed, model=str(data.get("model", role.model)), usage=usage
        )

    async def judge(
        self, role: RoleConfig, state: SafeText, questions: dict[str, JudgeQuestion]
    ) -> JudgeResult:
        raise unsupported(self.name, "judge")

    async def embed(self, role: RoleConfig, texts: Sequence[SafeText | str]) -> EmbedResult:
        body = {"model": role.model, "input": [_text(t) for t in texts]}
        data = await self._post("/api/embed", body, role.timeout_s)
        vectors = [[float(x) for x in vec] for vec in data.get("embeddings", [])]
        if len(vectors) != len(texts):
            raise ProviderError(f"Ollama returned {len(vectors)} embeddings for {len(texts)} texts")
        usage = Usage(tokens_in=int(data.get("prompt_eval_count", 0)))
        return EmbedResult(vectors=vectors, model=str(data.get("model", role.model)), usage=usage)

    async def ping(self) -> bool:
        try:
            response = await self._client.get("/api/tags", timeout=3.0)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def aclose(self) -> None:
        await self._client.aclose()
