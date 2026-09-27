"""Local provider for OpenAI-compatible servers (oMLX; also LM Studio, mlx_lm.server).

Endpoints used, as implemented by oMLX (github.com/jundot/omlx, ``omlx/api/``):
``POST /v1/chat/completions`` with ``response_format={"type": "json_schema", ...}`` for
structured output and ``enable_thinking`` to switch Qwen's thinking off, ``POST
/v1/embeddings`` and ``GET /v1/models`` as a reachability check. oMLX requires a Bearer API
key whenever it listens on a network address.
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


def _text(value: SafeText | str) -> str:
    return value.text if isinstance(value, SafeText) else value


class OpenAICompatProvider:
    external = False

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(base_url=base_url, headers=headers, transport=transport)

    async def _post(self, path: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=body, timeout=timeout)
        except httpx.ConnectError as e:
            raise LocalModelOffline(f"{self.name} unreachable at {self._client.base_url}") from e
        except httpx.TimeoutException as e:
            raise TransientProviderError(f"{self.name} timed out on {path}") from e
        except httpx.TransportError as e:
            raise TransientProviderError(f"{self.name} transport error on {path}: {e}") from e
        if response.status_code >= 500 or response.status_code == 429:
            raise TransientProviderError(f"{self.name} {path} returned {response.status_code}")
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name} {path} returned {response.status_code}: {response.text}"
            )
        data: dict[str, Any] = response.json()
        return data

    async def generate(
        self, role: RoleConfig, messages: Sequence[Message], schema: type[BaseModel] | None
    ) -> GenerateResult:
        body: dict[str, Any] = {
            "model": role.model,
            "messages": [{"role": m.role, "content": _text(m.content)} for m in messages],
            "max_tokens": role.max_tokens,
            "stream": False,
        }
        options = dict(role.options)
        if "think" in options:
            body["enable_thinking"] = bool(options.pop("think"))
        body.update(options)  # temperature, top_p, ... are top-level in the OpenAI format
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": True,
                },
            }

        data = await self._post("/v1/chat/completions", body, role.timeout_s)
        choices = data.get("choices") or [{}]
        text = str((choices[0].get("message") or {}).get("content") or "")
        parsed: BaseModel | None = None
        if schema is not None:
            try:
                parsed = schema.model_validate_json(text)
            except ValidationError as e:
                raise ProviderError(
                    f"{self.name} output did not match {schema.__name__}: {e}"
                ) from e
        usage = data.get("usage") or {}
        return GenerateResult(
            text=text,
            parsed=parsed,
            model=str(data.get("model", role.model)),
            usage=Usage(
                tokens_in=int(usage.get("prompt_tokens", 0)),
                tokens_out=int(usage.get("completion_tokens", 0)),
            ),
        )

    async def judge(
        self, role: RoleConfig, state: SafeText, questions: dict[str, JudgeQuestion]
    ) -> JudgeResult:
        raise unsupported(self.name, "judge")

    async def embed(self, role: RoleConfig, texts: Sequence[SafeText | str]) -> EmbedResult:
        body = {"model": role.model, "input": [_text(t) for t in texts]}
        data = await self._post("/v1/embeddings", body, role.timeout_s)
        items = sorted(data.get("data", []), key=lambda d: int(d.get("index", 0)))
        vectors = [[float(x) for x in item["embedding"]] for item in items]
        if len(vectors) != len(texts):
            raise ProviderError(f"{self.name} returned {len(vectors)} embeddings for {len(texts)}")
        usage = data.get("usage") or {}
        return EmbedResult(
            vectors=vectors,
            model=str(data.get("model", role.model)),
            usage=Usage(tokens_in=int(usage.get("prompt_tokens", 0))),
        )

    async def ping(self) -> bool:
        try:
            response = await self._client.get("/v1/models", timeout=3.0)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    async def aclose(self) -> None:
        await self._client.aclose()
