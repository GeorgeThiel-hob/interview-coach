"""Evidence map: which CV fragments support each requirement (spec 5.2).

1. Embed CV chunks and requirements locally (role ``embed``).
2. Take the top-k CV chunks per requirement by cosine similarity.
3. Ask Jev one ``evidence_for_req`` noul per (requirement, chunk), all chunks of one
   requirement in a single call.
4. Strength = strong / partial / none from the best chunk (thresholds in config).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import Chunk, Requirement
from app.ingest.pseudonymise import stored
from app.ingest.service import chunks
from app.judgments.cascade import Asked, ask, thresholds
from app.judgments.catalog import get
from app.llm.gateway import Gateway
from app.llm.text import SafeText, fence, join, label


@dataclass(frozen=True)
class EvidenceEntry:
    requirement_id: str
    strength: str
    refs: list[str]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def strength_of(best: float) -> str:
    cfg = thresholds()["evidence"]
    if best >= float(cfg["strong"]):
        return "strong"
    if best >= float(cfg["partial"]):
        return "partial"
    return "none"


async def embed_chunks(gateway: Gateway, engine: Engine, run_id: str) -> None:
    todo = [c for c in chunks(engine, run_id) if not c.embedding]
    if not todo:
        return
    result = await gateway.embed([c.text_pseudonymised for c in todo], run_id=run_id)
    with Session(engine) as s:
        for c, vec in zip(todo, result.vectors, strict=True):
            row = s.get(Chunk, c.id)
            if row:
                row.embedding = vec
                s.add(row)
        s.commit()


async def build_evidence_map(gateway: Gateway, engine: Engine, run_id: str) -> list[EvidenceEntry]:
    await embed_chunks(gateway, engine, run_id)
    cv = [c for c in chunks(engine, run_id, "cv:") if c.embedding]
    by_ref = {c.chunk_ref: c for c in chunks(engine, run_id, "vac:")}
    with Session(engine) as s:
        reqs = list(
            s.exec(
                select(Requirement).where(
                    Requirement.run_id == run_id,
                    Requirement.kind.in_(["eis", "wens"]),  # type: ignore[attr-defined]
                )
            ).all()
        )
    top_k = int(thresholds()["evidence"]["top_k"])
    results: list[EvidenceEntry] = []
    for req in reqs:
        req_chunk = by_ref.get(f"vac:{req.id.replace('_', '')}")
        if req_chunk is None or not req_chunk.embedding or not cv:
            results.append(EvidenceEntry(req.id, "none", []))
            continue
        ranked = sorted(cv, key=lambda c: cosine(req_chunk.embedding, c.embedding), reverse=True)
        top = ranked[:top_k]
        parts: list[SafeText] = [fence("requirement", stored(req.text))]
        asked: list[Asked] = []
        entry = get("evidence_for_req")
        for i, c in enumerate(top, 1):
            tag = f"F{i}"
            parts.append(fence(f"fragment-{tag}", stored(c.text_pseudonymised)))
            asked.append(
                Asked(
                    f"evidence_{tag}",
                    entry,
                    entry.build(label=label(f"fragment-{tag}")),
                    subject=f"{req.id}|{c.chunk_ref}",
                )
            )
        out = await ask(gateway, engine, join(parts), asked, run_id=run_id)
        scored = sorted(
            ((float(out[a.key].value), c.chunk_ref) for a, c in zip(asked, top, strict=True)),
            reverse=True,
        )
        partial = float(thresholds()["evidence"]["partial"])
        refs = [ref for value, ref in scored if value >= partial]
        entry_out = EvidenceEntry(req.id, strength_of(scored[0][0] if scored else 0.0), refs)
        results.append(entry_out)
        with Session(engine) as s:
            row = s.get(Requirement, (req.id, run_id))
            if row:
                row.evidence_strength = entry_out.strength
                row.evidence_refs = refs
                s.add(row)
                s.commit()
    return results
