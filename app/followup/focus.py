"""Focus list for the next run (spec 5.8, 5.9): weak points found in code from the judgments.

Weak points are patterns, not single bad answers: a STAR element that is usually missing, few
quantified results, requirements the candidate has evidence for but did not bring up, and
low-quality answers per requirement. Severity is a number 0-1 computed in code.
"""

from __future__ import annotations

from typing import Any

from app.report.schema import FocusItem, RequirementCoverage

_LABELS = {
    "R": {"en": "Results are rarely stated", "nl": "Resultaten worden zelden benoemd"},
    "S": {
        "en": "The situation/context is often missing",
        "nl": "De situatie/context ontbreekt vaak",
    },
    "T": {
        "en": "Own task or responsibility is often unclear",
        "nl": "Eigen taak of verantwoordelijkheid is vaak onduidelijk",
    },
    "A": {
        "en": "Own actions are described too little",
        "nl": "Eigen acties worden te weinig beschreven",
    },
    "quantified": {
        "en": "Results are rarely quantified",
        "nl": "Resultaten worden zelden gekwantificeerd",
    },
    "specific": {
        "en": "Answers stay general instead of concrete",
        "nl": "Antwoorden blijven algemeen in plaats van concreet",
    },
    "unused": {
        "en": "Experience for '{req}' was not brought up",
        "nl": "Ervaring voor '{req}' niet benoemd",
    },
    "weak_req": {"en": "Weak answers on '{req}'", "nl": "Zwakke antwoorden over '{req}'"},
}
STAR_THRESHOLD = 0.5
RATE_THRESHOLD = 0.4


def short(text: str, limit: int = 60) -> str:
    """Shorten at a word boundary with an ellipsis, never mid-word."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return (cut or text[:limit]) + "…"


def _label(key: str, lang: str, **fmt: str) -> str:
    return _LABELS[key].get(lang, _LABELS[key]["en"]).format(**fmt)


def derive_weak_points(
    stats: dict[str, Any],
    requirements: list[RequirementCoverage],
    answers: list[dict[str, Any]],
    language: str,
) -> list[FocusItem]:
    """``answers``: [{"turn_id", "question", "answer", "requirement_ids", "quality"}]."""
    items: list[FocusItem] = []
    for element, rate in stats.get("star_rates", {}).items():
        if stats.get("answers", 0) >= 2 and rate < STAR_THRESHOLD:
            items.append(
                FocusItem(
                    id=f"star_{element.lower()}",
                    label=_label(element, language),
                    severity=round(1 - rate, 2),
                    history=["weak"],
                )
            )
    for key, stat in (("quantified", "quantified_rate"), ("specific", "specific_rate")):
        rate = float(stats.get(stat, 1.0))
        if stats.get("answers", 0) >= 2 and rate < RATE_THRESHOLD:
            items.append(
                FocusItem(
                    id=key,
                    label=_label(key, language),
                    severity=round(1 - rate, 2),
                    history=["weak"],
                )
            )
    for r in requirements:
        if r.kind != "eis":
            continue
        related = [a for a in answers if r.id in a.get("requirement_ids", [])]
        if r.evidence_in_documents in ("strong", "partial") and r.evidence_in_interview == "none":
            items.append(
                FocusItem(
                    id=f"unused_{r.id}",
                    label=_label("unused", language, req=short(r.text)),
                    linked_requirements=[r.id],
                    severity=0.7,
                    history=["weak"],
                    previous_questions=[a["question"] for a in related][:3],
                    previous_answer=related[-1]["answer"][:400] if related else "",
                )
            )
        qualities = [float(a["quality"]) for a in related if a.get("quality") is not None]
        if qualities and sum(qualities) / len(qualities) < 1.5:
            items.append(
                FocusItem(
                    id=f"weak_{r.id}",
                    label=_label("weak_req", language, req=short(r.text)),
                    linked_requirements=[r.id],
                    severity=round(1 - (sum(qualities) / len(qualities)) / 3, 2),
                    history=["weak"],
                    previous_questions=[a["question"] for a in related][:3],
                    previous_answer=related[-1]["answer"][:400] if related else "",
                )
            )
    return items


def merge_history(
    carried: list[dict[str, Any]], mastery: dict[str, str], new: list[FocusItem]
) -> list[FocusItem]:
    """Carry focus items from the previous report, append this run's mastery result, and drop
    items mastered twice in a row (spec 5.9 step 5). New weak points are added once."""
    out: list[FocusItem] = []
    seen: set[str] = set()
    for raw in carried:
        item = FocusItem.model_validate(raw)
        result = mastery.get(item.id)
        history = [*item.history, result] if result else list(item.history)
        seen.add(item.id)
        if history[-2:] == ["mastered", "mastered"]:
            continue
        out.append(item.model_copy(update={"history": history}))
    for item in new:
        if item.id not in seen:
            out.append(item)
            seen.add(item.id)
    return out
