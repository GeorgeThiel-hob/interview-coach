"""SQLite engine and session helpers (SQLModel; Postgres-ready via DATABASE_URL)."""

from __future__ import annotations

from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine

from app.db import models  # noqa: F401  (registers the tables on SQLModel.metadata)


def make_engine(url: str) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    SQLModel.metadata.create_all(engine)
    return engine
