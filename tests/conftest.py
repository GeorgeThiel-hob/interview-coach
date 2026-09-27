from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app.db import models  # noqa: F401
from app.llm.config import ModelsConfig, load_models_config


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def config() -> ModelsConfig:
    return load_models_config()


async def no_sleep(_: float) -> None:
    return None


# ---------------------------------------------------------------- pipeline stack with fakes

from dataclasses import dataclass  # noqa: E402

from cryptography.fernet import Fernet  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db.models import Run  # noqa: E402
from app.llm.gateway import Gateway  # noqa: E402
from tests.fakes import FakeProvider, claude_handlers, local_handlers  # noqa: E402

PEOPLE = {"Jan de Vries": "person", "Petra Jansen": "person", "Dorpsstraat 12": "address"}

VACANCY = """Functie: AI Developer bij een Nederlandse overheidsorganisatie.
Wat ga je doen: AI-toepassingen bouwen voor analisten.
- Eis: Minimaal 2 jaar ervaring met Python in productie.
- Eis: Ervaring met toepassingen op basis van taalmodellen.
- Eis: Kennis van CI/CD en containers.
- Wens: Ervaring met lokale open-source modellen.
- Taak: Je beheert AI-toepassingen van prototype tot productie.
"""

CV = """Jan de Vries
Dorpsstraat 12, 1234 AB Utrecht, jan@example.nl, 06-12345678

Data Engineer bij ACME Logistics (2022-2026)
- Bouwde een Python pipeline die dagelijks 40 miljoen metingen verwerkt in productie.
- Zette CI/CD op met GitHub Actions en Docker containers voor 6 services.
- Maakte een prototype chatbot op basis van een open-source taalmodel.
Referentie: Petra Jansen, teamleider.

Opleiding: MSc Civil Engineering, TU Delft (2021).
"""


@dataclass
class Stack:
    gateway: Gateway
    engine: Engine
    local: FakeProvider
    claude: FakeProvider
    jev: FakeProvider
    run_id: str
    key: str


@pytest.fixture
def stack(config: ModelsConfig, engine: Engine) -> Stack:
    local = FakeProvider("ollama", False, local_handlers(PEOPLE))
    claude = FakeProvider("anthropic", True, claude_handlers())
    jev = FakeProvider("typesafe", True)
    gw = Gateway(
        config, {"ollama": local, "anthropic": claude, "typesafe": jev}, engine, sleep=no_sleep
    )
    settings = {
        "interview_type": "mixed",
        "language": "nl",
        "length": 15,
        "difficulty": "realistic",
        "answer_mode": "typed",
    }
    with Session(engine) as s:
        run = Run(settings=settings)
        s.add(run)
        s.commit()
        run_id = run.id
    return Stack(gw, engine, local, claude, jev, run_id, Fernet.generate_key().decode())
