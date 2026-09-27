"""Extract eisen, wensen, responsibilities and context from the vacancy (spec 5.2).

Local Qwen first (role ``extract``, JSON validated with pydantic); on invalid output retry
once, then escalate to Claude (role ``extract_escalation``). The vacancy is pseudonymised
before any of this, so escalation is allowed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import Chunk, Requirement, Run
from app.ingest.pseudonymise import stored
from app.ingest.service import chunks
from app.llm.errors import ProviderError
from app.llm.gateway import Gateway
from app.llm.prompts import prompt
from app.llm.text import fence
from app.llm.types import Message


class VacancyContext(BaseModel):
    title: str = ""
    organisation: str = ""
    team: str = ""
    domain: str = ""
    summary: str = ""


class ExtractedItem(BaseModel):
    kind: Literal["eis", "wens", "responsibility"]
    text: str = Field(min_length=3)
    source_ref: str | None = None


class Extraction(BaseModel):
    context: VacancyContext
    items: list[ExtractedItem]


def _valid(result: object) -> Extraction | None:
    if isinstance(result, Extraction) and any(i.kind == "eis" for i in result.items):
        return result
    return None


async def extract_requirements(gateway: Gateway, engine: Engine, run_id: str) -> Extraction:
    vac_chunks = chunks(engine, run_id, "vac:")
    if not vac_chunks:
        raise ValueError("run has no vacancy")
    listing = stored("\n".join(f"[{c.chunk_ref}] {c.text_pseudonymised}" for c in vac_chunks))
    messages = [Message("system", prompt("extract")), Message("user", fence("vacancy", listing))]

    extraction: Extraction | None = None
    for role in ("extract", "extract", "extract_escalation"):
        try:
            out = await gateway.generate(role, messages, Extraction, run_id=run_id)
        except ProviderError:
            continue
        extraction = _valid(out.parsed)
        if extraction:
            break
    if extraction is None:
        raise ProviderError("could not extract requirements from the vacancy")

    known = {c.chunk_ref for c in vac_chunks}
    counters: dict[str, int] = {}
    prefix = {"eis": "eis", "wens": "wens", "responsibility": "resp"}
    with Session(engine) as s:
        for old in s.exec(select(Requirement).where(Requirement.run_id == run_id)).all():
            s.delete(old)
        for old_chunk in s.exec(select(Chunk).where(Chunk.run_id == run_id)).all():
            if old_chunk.chunk_ref.startswith(("vac:eis", "vac:wens")):
                s.delete(old_chunk)
        vac_doc = vac_chunks[0].document_id
        for item in extraction.items:
            p = prefix[item.kind]
            counters[p] = counters.get(p, 0) + 1
            rid = f"{p}_{counters[p]}"
            s.add(
                Requirement(
                    id=rid,
                    run_id=run_id,
                    kind=item.kind,
                    text=item.text.strip(),
                    source_chunk_ref=item.source_ref if item.source_ref in known else None,
                )
            )
            if item.kind in ("eis", "wens"):
                s.add(
                    Chunk(
                        document_id=vac_doc,
                        run_id=run_id,
                        chunk_ref=f"vac:{p}{counters[p]}",
                        text_pseudonymised=item.text,
                    )
                )
        run = s.get(Run, run_id)
        if run:
            run.context = extraction.context.model_dump()
            s.add(run)
        s.commit()
    return extraction
