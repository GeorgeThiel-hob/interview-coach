"""Load and validate config/models.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

ProviderName = Literal["ollama", "omlx", "anthropic", "typesafe"]
LOCAL_PROVIDERS: frozenset[str] = frozenset({"ollama", "omlx"})

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"


class RoleConfig(BaseModel):
    provider: ProviderName
    model: str
    local_only: bool = False
    timeout_s: float = 60.0
    max_tokens: int = 4000
    options: dict[str, Any] = Field(default_factory=dict)


class Price(BaseModel):
    input: float
    output: float


class RetryConfig(BaseModel):
    max_attempts: int = 3
    backoff_base_s: float = 0.5
    backoff_max_s: float = 8.0


class BudgetConfig(BaseModel):
    per_run_eur: float
    per_run_tokens: int
    daily_eur: float


class ModelsConfig(BaseModel):
    providers: dict[str, dict[str, str]]
    roles: dict[str, RoleConfig]
    pricing_usd_per_mtok: dict[str, Price]
    usd_to_eur: float
    retries: RetryConfig = Field(default_factory=RetryConfig)
    budgets: BudgetConfig

    @model_validator(mode="after")
    def _local_only_roles_stay_local(self) -> ModelsConfig:
        for name, role in self.roles.items():
            if role.local_only and role.provider not in LOCAL_PROVIDERS:
                raise ValueError(
                    f"role {name!r} handles raw personal data and must run locally, "
                    f"but is configured for {role.provider!r}"
                )
        return self

    @model_validator(mode="after")
    def _external_models_have_prices(self) -> ModelsConfig:
        for name, role in self.roles.items():
            if role.provider not in LOCAL_PROVIDERS and role.model not in self.pricing_usd_per_mtok:
                raise ValueError(f"role {name!r} uses {role.model!r}, which has no price entry")
        return self

    def role(self, name: str) -> RoleConfig:
        try:
            return self.roles[name]
        except KeyError:
            raise KeyError(f"unknown role {name!r}; add it to config/models.yaml") from None

    def cost_eur(self, model: str, tokens_in: int, tokens_out: int) -> float:
        price = self.pricing_usd_per_mtok.get(model)
        if price is None:
            return 0.0
        usd = (tokens_in * price.input + tokens_out * price.output) / 1_000_000
        return usd * self.usd_to_eur


def load_models_config(path: Path = DEFAULT_PATH) -> ModelsConfig:
    with path.open(encoding="utf-8") as f:
        return ModelsConfig.model_validate(yaml.safe_load(f))
