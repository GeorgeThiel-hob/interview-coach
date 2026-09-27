"""One smoke test per provider (M0 acceptance criterion).

Each test runs the real SDK / HTTP code path against a mocked HTTP transport, so request
building and response parsing are exercised without network access or API keys. The
response bodies follow the providers' documented formats (Jev: docs/vendor/typesafe).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import httpx2
from pydantic import BaseModel

from app.llm.anthropic import AnthropicProvider
from app.llm.ollama import OllamaProvider
from app.llm.text import TrustedText, _mint_pseudonymised
from app.llm.types import JudgeQuestion, Message
from app.llm.typesafe import TypeSafeProvider


class Topic(BaseModel):
    title: str
    weight: int


async def test_ollama_generate_with_schema_and_embed(config: Any) -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"path": request.url.path, **body})
        if request.url.path == "/api/chat":
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "message": {"role": "assistant", "content": '{"title": "STAR", "weight": 2}'},
                    "prompt_eval_count": 12,
                    "eval_count": 9,
                },
            )
        return httpx.Response(200, json={"model": body["model"], "embeddings": [[0.1, 0.2]]})

    provider = OllamaProvider("http://laptop:11434", transport=httpx.MockTransport(handler))
    role = config.role("extract")
    result = await provider.generate(role, [Message("user", "raw text is fine locally")], Topic)
    assert result.parsed == Topic(title="STAR", weight=2)
    assert (result.usage.tokens_in, result.usage.tokens_out) == (12, 9)
    assert seen[0]["format"] == Topic.model_json_schema()
    assert seen[0]["think"] is False  # top-level Ollama field, not inside options
    assert seen[0]["options"] == {"temperature": 0}

    emb = await provider.embed(config.role("embed"), ["chunk"])
    assert emb.vectors == [[0.1, 0.2]]
    await provider.aclose()


async def test_anthropic_generate_parses_structured_output(config: Any) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.update(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": '{"title": "Gap", "weight": 3}'}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    provider = AnthropicProvider("sk-test", http_client=client)
    messages = [
        Message("system", TrustedText("You plan interviews.")),
        Message("user", _mint_pseudonymised("[PERSON_1] worked at ACME.")),
    ]
    result = await provider.generate(config.role("plan"), messages, Topic)
    assert result.parsed == Topic(title="Gap", weight=3)
    assert result.model == "claude-sonnet-5"
    assert captured["system"] == "You plan interviews."
    assert captured["messages"] == [{"role": "user", "content": "[PERSON_1] worked at ACME."}]
    assert captured["output_config"]["effort"] == "medium"
    await provider.aclose()


async def test_typesafe_judge_maps_all_three_answer_types(config: Any) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.update(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "a_star_r": {"type": "noul", "noul": 0.2},
                    "a_cv_consistency": {
                        "type": "choice",
                        "choice": "consistent",
                        "probabilities": {"consistent": 0.9, "contradicts": 0.1},
                        "confidence": 0.81,
                    },
                    "a_quality": {
                        "type": "score",
                        "score": 1.05,
                        "legend": {"0": "No", "1": "Partly", "2": "Yes"},
                        "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
                        "confidence": 0.92,
                    },
                },
                "usage": {"input_tokens": 318, "output_tokens": 34},
            },
        )

    provider = TypeSafeProvider("ts-test-key", transport=httpx2.MockTransport(handler))
    t = TrustedText
    questions = {
        "a_star_r": JudgeQuestion("noul", t("The answer states an outcome or result.")),
        "a_cv_consistency": JudgeQuestion(
            "choice",
            t("How does the answer relate to the CV?"),
            {"consistent": t("supported by the CV"), "contradicts": None},
        ),
        "a_quality": JudgeQuestion("score", t("How good?"), [t("No"), t("Partly"), t("Yes")]),
    }
    result = await provider.judge(
        config.role("judge"), _mint_pseudonymised("Q: ... A: ..."), questions
    )
    assert captured["model"] == "jev-1.13.0"
    assert captured["questions"]["a_star_r"]["type"] == "noul"
    assert result.model == "jev-1.13.0"
    assert result.answers["a_star_r"].value == 0.2
    assert result.answers["a_star_r"].confidence is None
    assert result.answers["a_cv_consistency"].value == "consistent"
    assert result.answers["a_cv_consistency"].confidence == 0.81
    assert result.answers["a_quality"].value == 1.05
    assert result.answers["a_quality"].probabilities["1"] == 0.95
    assert (result.usage.tokens_in, result.usage.tokens_out) == (318, 34)
    await provider.aclose()
