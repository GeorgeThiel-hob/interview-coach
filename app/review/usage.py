"""Usage metrics from model_calls, judgments and events (spec 10.1). Metadata only."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import Event, Judgment, ModelCall


def _pct(values: list[int], q: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def usage(engine: Engine, run_id: str | None = None) -> dict[str, Any]:
    with Session(engine) as s:
        calls_q = select(ModelCall)
        judg_q = select(Judgment)
        ev_q = select(Event)
        if run_id:
            calls_q = calls_q.where(ModelCall.run_id == run_id)
            judg_q = judg_q.where(Judgment.run_id == run_id)
            ev_q = ev_q.where(Event.run_id == run_id)
        calls = list(s.exec(calls_q).all())
        judgments = list(s.exec(judg_q).all())
        events = list(s.exec(ev_q).all())

    per_provider: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_eur": 0.0}
    )
    latency: dict[str, list[int]] = defaultdict(list)
    for c in calls:
        p = per_provider[c.provider]
        p["calls"] += 1
        p["tokens_in"] += c.tokens_in
        p["tokens_out"] += c.tokens_out
        p["cost_eur"] = round(p["cost_eur"] + c.cost_eur, 5)
        if c.status == "ok":
            latency[c.role].append(c.latency_ms)
    total = len(calls) or 1
    local = sum(1 for c in calls if c.provider in ("ollama", "omlx"))

    by_q: dict[str, Counter[str]] = defaultdict(Counter)
    for j in judgments:
        by_q[j.question_id]["total"] += 1
        by_q[j.question_id]["escalated"] += int(j.escalated)
        by_q[j.question_id]["uncertain"] += int(j.uncertain)
    return {
        "calls": len(calls),
        "cost_eur": round(sum(c.cost_eur for c in calls), 4),
        "local_share": round(local / total, 3),
        "per_provider": dict(per_provider),
        "latency_ms": {
            r: {"p50": _pct(v, 0.5), "p95": _pct(v, 0.95), "n": len(v)} for r, v in latency.items()
        },
        "errors": dict(Counter(c.status for c in calls if c.status != "ok")),
        "escalation": {
            q: {
                "total": c["total"],
                "escalated": c["escalated"],
                "uncertain": c["uncertain"],
                "rate": round(c["escalated"] / c["total"], 3) if c["total"] else 0.0,
            }
            for q, c in sorted(by_q.items())
        },
        "events": dict(Counter(e.kind for e in events)),
    }
