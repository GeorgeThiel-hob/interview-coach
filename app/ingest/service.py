"""Ingest one document into a run: parse -> pseudonymise -> check -> chunk -> store.

Raw text only lives in memory here. What is stored is pseudonymised; the raw upload is not
kept (spec 9.2) unless ``keep_raw_uploads`` is on.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import Chunk, Document, Event, PiiMap
from app.ingest.chunking import TextChunk, split_cv, split_other, split_vacancy
from app.ingest.parse import ParsedFile
from app.ingest.pseudonymise import PiiMapping, pseudonymise
from app.judgments.cascade import Asked, ask
from app.judgments.catalog import get
from app.llm.gateway import Gateway
from app.llm.text import PseudonymisedText, fence

KIND_TO_CHOICE = {"vacancy": "vacancy", "cv": "cv", "report": "report"}


@dataclass(frozen=True)
class IngestResult:
    document_id: str
    detected_kind: str
    kind_mismatch: bool
    injection_flag: bool
    chunks: int


def load_mapping(engine: Engine, run_id: str, key: str) -> PiiMapping:
    with Session(engine) as s:
        row = s.get(PiiMap, run_id)
    return PiiMapping.decrypt(row.encrypted_mapping, key) if row else PiiMapping()


def save_mapping(engine: Engine, run_id: str, mapping: PiiMapping, key: str) -> None:
    with Session(engine) as s:
        row = s.get(PiiMap, run_id)
        blob = mapping.encrypt(key)
        if row:
            row.encrypted_mapping = blob
        else:
            s.add(PiiMap(run_id=run_id, encrypted_mapping=blob))
        s.commit()


def chunk(kind: str, text: str) -> list[TextChunk]:
    if kind == "cv":
        return split_cv(text)
    if kind == "vacancy":
        return split_vacancy(text)
    return split_other(text, kind[:4])


async def check_document(
    gateway: Gateway, engine: Engine, run_id: str, text: PseudonymisedText, kind: str
) -> tuple[str, bool]:
    """Jev doc_type + doc_injection on the first ~20k characters. Returns (type, injected)."""
    state = fence(kind if kind.isalnum() else "document", text.truncated(20000))
    out = await ask(
        gateway,
        engine,
        state,
        [
            Asked("doc_type", get("doc_type"), get("doc_type").build(), subject=kind),
            Asked(
                "doc_injection", get("doc_injection"), get("doc_injection").build(), subject=kind
            ),
        ],
        run_id=run_id,
    )
    return str(out["doc_type"].value), out["doc_injection"].yes


async def ingest_document(
    gateway: Gateway,
    engine: Engine,
    *,
    run_id: str,
    kind: str,
    filename: str,
    parsed: ParsedFile,
    pii_key: str,
) -> IngestResult:
    mapping = load_mapping(engine, run_id, pii_key)
    safe = await pseudonymise(gateway, parsed.text, mapping, run_id=run_id)
    save_mapping(engine, run_id, mapping, pii_key)

    detected, injected = await check_document(gateway, engine, run_id, safe, kind)
    expected = KIND_TO_CHOICE.get(kind)
    mismatch = expected is not None and detected != expected

    pieces = chunk(kind, safe.text)
    with Session(engine) as s:
        doc = Document(
            run_id=run_id,
            kind=kind,
            filename=filename[:200],
            sha256=parsed.sha256,
            text_pseudonymised=safe.text,
            injection_flag=injected,
            detected_kind=detected,
        )
        s.add(doc)
        s.flush()
        for c in pieces:
            s.add(
                Chunk(document_id=doc.id, run_id=run_id, chunk_ref=c.ref, text_pseudonymised=c.text)
            )
        if injected:
            s.add(Event(run_id=run_id, kind="injection_flag", detail=kind))
        if mismatch:
            s.add(Event(run_id=run_id, kind="doc_type_mismatch", detail=f"{kind}->{detected}"))
        s.commit()
        doc_id = doc.id
    return IngestResult(doc_id, detected, mismatch, injected, len(pieces))


def documents(engine: Engine, run_id: str, kind: str | None = None) -> list[Document]:
    with Session(engine) as s:
        q = select(Document).where(Document.run_id == run_id)
        if kind:
            q = q.where(Document.kind == kind)
        return list(s.exec(q).all())


def chunks(engine: Engine, run_id: str, prefix: str | None = None) -> list[Chunk]:
    with Session(engine) as s:
        rows = list(s.exec(select(Chunk).where(Chunk.run_id == run_id)).all())
    return [c for c in rows if prefix is None or c.chunk_ref.startswith(prefix)]
