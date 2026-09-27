"""FastAPI app. M0 only exposes /healthz; the interview UI arrives in M2."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from sqlalchemy import text
from sqlmodel import Session

from app.db.session import make_engine
from app.llm.gateway import build_gateway


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = make_engine(os.environ.get("DATABASE_URL", "sqlite:///data/app.db"))
    app.state.engine = engine
    app.state.gateway = build_gateway(engine)
    yield
    await app.state.gateway.aclose()


app = FastAPI(title="Interview Simulator", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    with Session(app.state.engine) as s:
        db_ok = s.exec(text("SELECT 1")).one()[0] == 1  # type: ignore[call-overload]
    local_ok = await app.state.gateway.local_available()
    # "local" false means the laptop is off: finished runs still work, new runs are blocked
    return {"db": db_ok, "local_model": local_ok, "new_runs_allowed": db_ok and local_ok}
