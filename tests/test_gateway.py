"""Gateway behaviour: logging, cost, retries, budget caps and the laptop-offline path."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import ModelCall
from app.llm.config import ModelsConfig
from app.llm.errors import BudgetExceeded, LocalModelOffline, TransientProviderError
from app.llm.gateway import Gateway
from app.llm.text import TrustedText, _mint_pseudonymised
from app.llm.types import JudgeQuestion, Message
from tests.conftest import no_sleep
from tests.test_privacy import RecordingProvider

SAFE = [Message("user", _mint_pseudonymised("[PERSON_1] at ACME"))]


def make(config: ModelsConfig, engine: Engine, **overrides: Any) -> tuple[Gateway, dict[str, Any]]:
    providers: dict[str, Any] = {
        "ollama": RecordingProvider("ollama", external=False),
        "anthropic": RecordingProvider("anthropic", external=True),
        "typesafe": RecordingProvider("typesafe", external=True),
        **overrides,
    }
    return Gateway(config, providers, engine, sleep=no_sleep), providers


def rows(engine: Engine) -> list[ModelCall]:
    with Session(engine) as s:
        return list(s.exec(select(ModelCall)).all())


async def test_every_call_is_logged_with_cost_and_no_content(
    config: ModelsConfig, engine: Engine
) -> None:
    gw, _ = make(config, engine)
    await gw.generate("plan", SAFE, run_id="run-1")
    q = {"q": JudgeQuestion("noul", TrustedText("Mentions ACME?"))}
    await gw.judge(_mint_pseudonymised("[PERSON_1] at ACME"), q, run_id="run-1")

    logged = rows(engine)
    assert [(r.role, r.provider, r.status) for r in logged] == [
        ("plan", "anthropic", "ok"),
        ("judge", "typesafe", "ok"),
    ]
    # plan: 10 in / 5 out on claude-sonnet-5 at $2 / $10 per MTok, converted to EUR
    expected = (10 * 2.0 + 5 * 10.0) / 1_000_000 * config.usd_to_eur
    assert logged[0].cost_eur == pytest.approx(expected)
    columns = set(ModelCall.model_fields)
    assert not columns & {"prompt", "response", "content", "text", "messages"}


class FlakyProvider(RecordingProvider):
    def __init__(self, failures: int) -> None:
        super().__init__("anthropic", external=True)
        self.failures = failures

    async def generate(self, role: Any, messages: Any, schema: Any) -> Any:
        if self.failures:
            self.failures -= 1
            raise TransientProviderError("429")
        return await super().generate(role, messages, schema)


async def test_transient_errors_are_retried_and_each_attempt_logged(
    config: ModelsConfig, engine: Engine
) -> None:
    gw, _ = make(config, engine, anthropic=FlakyProvider(failures=2))
    await gw.generate("plan", SAFE)
    assert [(r.attempt, r.status) for r in rows(engine)] == [
        (1, "transient_error"),
        (2, "transient_error"),
        (3, "ok"),
    ]


async def test_retries_give_up_after_max_attempts(config: ModelsConfig, engine: Engine) -> None:
    gw, _ = make(config, engine, anthropic=FlakyProvider(failures=10))
    with pytest.raises(TransientProviderError):
        await gw.generate("plan", SAFE)
    assert len(rows(engine)) == config.retries.max_attempts


async def test_run_budget_blocks_further_calls(config: ModelsConfig, engine: Engine) -> None:
    config.budgets.per_run_eur = 0.00001  # one plan call costs more than this
    gw, providers = make(config, engine)
    await gw.generate("plan", SAFE, run_id="run-1")
    with pytest.raises(BudgetExceeded, match="run budget"):
        await gw.generate("plan", SAFE, run_id="run-1")
    assert len(providers["anthropic"].calls) == 1
    await gw.generate("plan", SAFE, run_id="run-2")  # other runs are unaffected


async def test_daily_budget_blocks_all_runs(config: ModelsConfig, engine: Engine) -> None:
    config.budgets.daily_eur = 0.00001
    gw, _ = make(config, engine)
    await gw.generate("plan", SAFE, run_id="run-1")
    with pytest.raises(BudgetExceeded, match="daily budget"):
        await gw.generate("plan", SAFE, run_id="run-2")


class OfflineProvider(RecordingProvider):
    def __init__(self) -> None:
        super().__init__("ollama", external=False)

    async def generate(self, role: Any, messages: Any, schema: Any) -> Any:
        raise LocalModelOffline("laptop is off")

    async def ping(self) -> bool:
        return False


async def test_laptop_offline_is_reported_not_retried(config: ModelsConfig, engine: Engine) -> None:
    gw, _ = make(config, engine, ollama=OfflineProvider())
    assert await gw.local_available() is False
    with pytest.raises(LocalModelOffline):
        await gw.generate("pseudonymise", [Message("user", "raw CV")])
    assert [r.status for r in rows(engine)] == ["offline"]
