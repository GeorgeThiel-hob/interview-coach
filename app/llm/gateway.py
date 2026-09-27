"""The single entry point for every model call (spec section 6.3).

The gateway resolves a role to a provider and model from config/models.yaml, and for every
call it:

* refuses to send anything but ``SafeText`` to an external provider (``UnsafeTextError``);
* checks the per-run and daily budget caps before calling (``BudgetExceeded``);
* applies the role's timeout and retries transient failures with exponential backoff;
* writes one ``model_calls`` row per attempt: provider, model, tokens, EUR cost, latency and
  status. Prompt and response content are never logged.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import Engine, func
from sqlmodel import Session, select

from app.db.models import ModelCall
from app.llm.base import Provider
from app.llm.config import ModelsConfig, RoleConfig, load_models_config
from app.llm.errors import (
    BudgetExceeded,
    GatewayError,
    LocalModelOffline,
    ProviderError,
    TransientProviderError,
    UnsafeTextError,
)
from app.llm.text import SafeText
from app.llm.types import EmbedResult, GenerateResult, JudgeQuestion, JudgeResult, Message, Usage

T = TypeVar("T", GenerateResult, JudgeResult, EmbedResult)


class Gateway:
    def __init__(
        self,
        config: ModelsConfig,
        providers: dict[str, Provider],
        engine: Engine,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self._providers = providers
        self._engine = engine
        self._sleep = sleep
        for name, role in config.roles.items():
            if role.provider not in providers:
                raise GatewayError(f"role {name!r} needs provider {role.provider!r}")

    # ------------------------------------------------------------------ public interface

    async def generate(
        self,
        role: str,
        messages: Sequence[Message],
        schema: type[BaseModel] | None = None,
        *,
        run_id: str | None = None,
    ) -> GenerateResult:
        cfg, provider = self._resolve(role)
        if provider.external:
            for m in messages:
                _require_safe(m.content, provider.name, role)
        return await self._call(
            role, cfg, provider, run_id, lambda: provider.generate(cfg, messages, schema)
        )

    async def judge(
        self,
        state: SafeText,
        questions: dict[str, JudgeQuestion],
        *,
        role: str = "judge",
        run_id: str | None = None,
    ) -> JudgeResult:
        if not questions:
            raise GatewayError("judge() needs at least one question")
        cfg, provider = self._resolve(role)
        if provider.external:
            _require_safe(state, provider.name, role)
            for q in questions.values():
                _require_safe(q.instructions, provider.name, role)
                crit = q.criteria
                values = crit.values() if isinstance(crit, dict) else (crit or [])
                for c in values:
                    if c is not None:
                        _require_safe(c, provider.name, role)
        return await self._call(
            role, cfg, provider, run_id, lambda: provider.judge(cfg, state, questions)
        )

    async def embed(
        self, texts: Sequence[SafeText | str], *, role: str = "embed", run_id: str | None = None
    ) -> EmbedResult:
        cfg, provider = self._resolve(role)
        if provider.external:
            for t in texts:
                _require_safe(t, provider.name, role)
        if not texts:
            return EmbedResult(vectors=[], model=cfg.model, usage=Usage())
        return await self._call(role, cfg, provider, run_id, lambda: provider.embed(cfg, texts))

    async def local_available(self) -> bool:
        """True when every local provider (the laptop's Ollama) answers. New runs need this."""
        local = {r.provider for r in self.config.roles.values()}
        checks = [self._providers[p].ping() for p in local if not self._providers[p].external]
        return all(await asyncio.gather(*checks))

    async def health(self) -> dict[str, bool]:
        """Reachability of every configured provider (no tokens spent)."""
        names = sorted(self._providers)
        results = await asyncio.gather(
            *(self._providers[n].reachable() for n in names), return_exceptions=True
        )
        return {n: r is True for n, r in zip(names, results, strict=True)}

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()

    # ------------------------------------------------------------------ internals

    def _resolve(self, role: str) -> tuple[RoleConfig, Provider]:
        cfg = self.config.role(role)
        return cfg, self._providers[cfg.provider]

    def _check_budget(self, run_id: str | None, role: str) -> None:
        budgets = self.config.budgets
        since = datetime.now(UTC) - timedelta(days=1)
        with Session(self._engine) as s:
            daily = s.exec(
                select(func.coalesce(func.sum(ModelCall.cost_eur), 0.0)).where(
                    ModelCall.created_at >= since
                )
            ).one()
            if daily >= budgets.daily_eur:
                raise BudgetExceeded(f"daily budget of EUR {budgets.daily_eur:.2f} reached")
            if run_id is None:
                return
            run_cost, run_tokens = s.exec(
                select(
                    func.coalesce(func.sum(ModelCall.cost_eur), 0.0),
                    func.coalesce(func.sum(ModelCall.tokens_in + ModelCall.tokens_out), 0),
                ).where(ModelCall.run_id == run_id)
            ).one()
        if run_cost >= budgets.per_run_eur:
            raise BudgetExceeded(f"run budget of EUR {budgets.per_run_eur:.2f} reached ({role})")
        if run_tokens >= budgets.per_run_tokens:
            raise BudgetExceeded(f"run token budget of {budgets.per_run_tokens} reached ({role})")

    async def _call(
        self,
        role: str,
        cfg: RoleConfig,
        provider: Provider,
        run_id: str | None,
        call: Callable[[], Awaitable[T]],
    ) -> T:
        retry = self.config.retries
        for attempt in range(1, retry.max_attempts + 1):
            self._check_budget(run_id, role)
            started = time.monotonic()
            try:
                # the provider applies the role timeout; this is a hard backstop
                result = await asyncio.wait_for(call(), timeout=cfg.timeout_s + 5)
            except (TimeoutError, TransientProviderError) as e:
                self._log(role, cfg, run_id, attempt, started, "transient_error", error=e)
                if attempt == retry.max_attempts:
                    if isinstance(e, TimeoutError):
                        raise TransientProviderError(f"{role} timed out") from e
                    raise
                backoff = min(retry.backoff_max_s, retry.backoff_base_s * 2 ** (attempt - 1))
                await self._sleep(backoff * (0.5 + random.random() / 2))
                continue
            except LocalModelOffline as e:
                self._log(role, cfg, run_id, attempt, started, "offline", error=e)
                raise
            except ProviderError as e:
                self._log(role, cfg, run_id, attempt, started, "error", error=e)
                raise
            self._log(role, cfg, run_id, attempt, started, "ok", result=result)
            return result
        raise AssertionError("unreachable")  # pragma: no cover

    def _log(
        self,
        role: str,
        cfg: RoleConfig,
        run_id: str | None,
        attempt: int,
        started: float,
        status: str,
        *,
        result: GenerateResult | JudgeResult | EmbedResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        usage = result.usage if result is not None else Usage()
        served = result.model if result is not None else None
        billed_model = served if served in self.config.pricing_usd_per_mtok else cfg.model
        row = ModelCall(
            run_id=run_id,
            role=role,
            provider=cfg.provider,
            model=cfg.model,
            served_model=served,
            attempt=attempt,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            cost_eur=self.config.cost_eur(billed_model, usage.tokens_in, usage.tokens_out),
            latency_ms=int((time.monotonic() - started) * 1000),
            status=status,
            error_type=type(error).__name__ if error is not None else None,
        )
        with Session(self._engine) as s:
            s.add(row)
            s.commit()


def _require_safe(value: object, provider: str, role: str) -> None:
    if not isinstance(value, SafeText):
        raise UnsafeTextError(
            f"role {role!r} sends to external provider {provider!r}, but got "
            f"{type(value).__name__}; only pseudonymised or trusted text may leave the server"
        )


def build_gateway(engine: Engine, config: ModelsConfig | None = None) -> Gateway:
    """Create the gateway with real providers, reading keys and URLs from the environment."""
    from app.llm.anthropic import AnthropicProvider
    from app.llm.ollama import OllamaProvider
    from app.llm.openai_compat import OpenAICompatProvider
    from app.llm.typesafe import TypeSafeProvider

    config = config or load_models_config()
    used = {r.provider for r in config.roles.values()}
    env = config.providers
    providers: dict[str, Provider] = {}
    if "ollama" in used:
        url = os.environ.get(env["ollama"]["base_url_env"], "http://localhost:11434")
        providers["ollama"] = OllamaProvider(url)
    if "omlx" in used:
        url = os.environ.get(env["omlx"]["base_url_env"], "http://localhost:8000")
        key = os.environ.get(env["omlx"]["api_key_env"]) or None
        providers["omlx"] = OpenAICompatProvider("omlx", url.rstrip("/"), key)
    if "anthropic" in used:
        providers["anthropic"] = AnthropicProvider(os.environ[env["anthropic"]["api_key_env"]])
    if "typesafe" in used:
        providers["typesafe"] = TypeSafeProvider(os.environ[env["typesafe"]["api_key_env"]])
    return Gateway(config, providers, engine)
