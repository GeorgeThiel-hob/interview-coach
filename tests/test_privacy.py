"""M0 acceptance: non-pseudonymised text cannot be sent to an external provider."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
import yaml
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import ModelCall
from app.llm.config import ModelsConfig, RoleConfig
from app.llm.gateway import Gateway
from app.llm.text import SafeText, TrustedText, _mint_pseudonymised
from app.llm.types import (
    EmbedResult,
    GenerateResult,
    JudgeAnswer,
    JudgeQuestion,
    JudgeResult,
    Message,
    Usage,
)


class RecordingProvider:
    """Stands in for a provider and records everything it would have sent."""

    def __init__(self, name: str, external: bool) -> None:
        self.name = name
        self.external = external
        self.calls: list[Any] = []

    async def generate(
        self, role: RoleConfig, messages: Sequence[Message], schema: type[BaseModel] | None
    ) -> GenerateResult:
        self.calls.append(messages)
        return GenerateResult("ok", None, role.model, Usage(10, 5))

    async def judge(
        self, role: RoleConfig, state: SafeText, questions: dict[str, JudgeQuestion]
    ) -> JudgeResult:
        self.calls.append(state)
        answers = {q: JudgeAnswer("noul", 0.9, None) for q in questions}
        return JudgeResult(answers, role.model, Usage(10, 1))

    async def embed(self, role: RoleConfig, texts: Sequence[SafeText | str]) -> EmbedResult:
        self.calls.append(texts)
        return EmbedResult([[0.0] for _ in texts], role.model, Usage(3, 0))

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


@pytest.fixture
def providers() -> dict[str, RecordingProvider]:
    return {
        "ollama": RecordingProvider("ollama", external=False),
        "anthropic": RecordingProvider("anthropic", external=True),
        "typesafe": RecordingProvider("typesafe", external=True),
    }


@pytest.fixture
def gateway(config: ModelsConfig, providers: dict[str, Any], engine: Engine) -> Gateway:
    return Gateway(config, providers, engine)


RAW_CV = "Jan de Vries, jan@example.nl, 06-12345678, worked at ACME as data engineer."
Q = {"q": JudgeQuestion("noul", TrustedText("The text mentions a role."))}


async def test_raw_text_to_claude_is_refused(gateway: Gateway, providers: Any) -> None:
    with pytest.raises(Exception) as err:
        await gateway.generate("plan", [Message("user", RAW_CV)])
    assert type(err.value).__name__ == "UnsafeTextError"
    assert providers["anthropic"].calls == []


async def test_raw_text_in_any_message_is_refused(gateway: Gateway, providers: Any) -> None:
    messages = [Message("system", TrustedText("Plan an interview.")), Message("user", RAW_CV)]
    with pytest.raises(Exception, match="only pseudonymised or trusted text"):
        await gateway.generate("feedback", messages)
    assert providers["anthropic"].calls == []


async def test_raw_state_to_jev_is_refused(gateway: Gateway, providers: Any) -> None:
    with pytest.raises(Exception, match="only pseudonymised or trusted text"):
        await gateway.judge(RAW_CV, Q)  # type: ignore[arg-type]
    assert providers["typesafe"].calls == []


async def test_raw_criteria_to_jev_is_refused(gateway: Gateway, providers: Any) -> None:
    raw_requirement = "Must have 5 years Python (Jan de Vries has this)"
    questions = {
        "q": JudgeQuestion("choice", TrustedText("Which?"), {"a": raw_requirement})  # type: ignore[dict-item]
    }
    with pytest.raises(Exception, match="only pseudonymised or trusted text"):
        await gateway.judge(_mint_pseudonymised("[PERSON_1] ..."), questions)
    assert providers["typesafe"].calls == []


async def test_refused_calls_are_not_logged_as_sent(gateway: Gateway, engine: Engine) -> None:
    with pytest.raises(Exception, match="only pseudonymised"):
        await gateway.generate("plan", [Message("user", RAW_CV)])
    with Session(engine) as s:
        assert s.exec(select(ModelCall)).all() == []


async def test_pseudonymised_text_reaches_claude(gateway: Gateway, providers: Any) -> None:
    await gateway.generate("plan", [Message("user", _mint_pseudonymised("[PERSON_1] at ACME"))])
    assert len(providers["anthropic"].calls) == 1


async def test_raw_text_is_allowed_to_the_local_model(gateway: Gateway, providers: Any) -> None:
    await gateway.generate("pseudonymise", [Message("user", RAW_CV)])
    assert providers["ollama"].calls[0][0].content == RAW_CV


def test_plain_str_cannot_pretend_to_be_safe() -> None:
    with pytest.raises(TypeError, match="pseudonymised first"):
        SafeText(RAW_CV, _key=object())
    with pytest.raises(TypeError):
        TrustedText("Hi {name}").render(name=RAW_CV)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        _ = TrustedText("a") + RAW_CV  # type: ignore[operator]


def test_config_rejects_pseudonymiser_on_external_provider() -> None:
    from app.llm.config import DEFAULT_PATH

    data = yaml.safe_load(DEFAULT_PATH.read_text())
    data["roles"]["pseudonymise"]["provider"] = "anthropic"
    data["roles"]["pseudonymise"]["model"] = "claude-haiku-4-5"
    with pytest.raises(ValidationError, match="must run locally"):
        ModelsConfig.model_validate(data)
