"""Real calls to each provider. Skipped by default; run with ``uv run pytest -m live``.

Needs ANTHROPIC_API_KEY, TYPESAFE_API_KEY and a reachable Ollama (OLLAMA_BASE_URL, default
http://localhost:11434) with the models from config/models.yaml pulled. Costs a fraction
of a cent.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel
from sqlalchemy import Engine

from app.llm.config import ModelsConfig
from app.llm.gateway import build_gateway
from app.llm.text import TrustedText
from app.llm.types import JudgeQuestion, Message

pytestmark = pytest.mark.live


class Answer(BaseModel):
    answer: str


def need(var: str) -> None:
    if not os.environ.get(var):
        pytest.skip(f"{var} not set")


async def test_live_ollama(engine: Engine, config: ModelsConfig) -> None:
    gw = build_gateway(engine, config)
    if not await gw.local_available():
        pytest.skip("Ollama not reachable")
    out = await gw.generate("interviewer", [Message("user", "Say hello in Dutch, one word.")])
    assert out.text.strip()
    emb = await gw.embed(["Ervaring met Python en SQL"])
    assert len(emb.vectors[0]) > 10
    await gw.aclose()


async def test_live_claude(engine: Engine, config: ModelsConfig) -> None:
    need("ANTHROPIC_API_KEY")
    need("TYPESAFE_API_KEY")
    gw = build_gateway(engine, config)
    msg = [Message("user", TrustedText('Reply with JSON {"answer": "ok"}.'))]
    out = await gw.generate("fallback_fast", msg, Answer)
    assert isinstance(out.parsed, Answer)
    await gw.aclose()


async def test_live_jev(engine: Engine, config: ModelsConfig) -> None:
    need("ANTHROPIC_API_KEY")
    need("TYPESAFE_API_KEY")
    gw = build_gateway(engine, config)
    q = {"urgent": JudgeQuestion("noul", TrustedText("The message conveys urgency."))}
    out = await gw.judge(TrustedText("Help, the server is down and clients are waiting!"), q)
    assert out.model.startswith("jev-")
    assert float(out.answers["urgent"].value) > 0.5
    await gw.aclose()
