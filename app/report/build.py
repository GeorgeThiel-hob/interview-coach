"""Build ``report/v1`` from the database (spec 5.8).

The stored copy stays pseudonymised; ``restore_names=True`` (the owner's download) puts the
real names back using the run's encrypted PII mapping.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, select

from app.db.models import Feedback, Judgment, PlanTopic, Report, Requirement, Run, Turn
from app.followup.focus import derive_weak_points, merge_history
from app.ingest.pseudonymise import PiiMapping
from app.judgments.cascade import thresholds
from app.llm.config import load_models_config
from app.report.schema import (
    AnswerView,
    FeedbackView,
    JudgmentView,
    ModelsView,
    PracticeAction,
    RequirementCoverage,
    SpeakingView,
    Vacancy,
)
from app.report.schema import (
    Report as ReportModel,
)
from app.review.metrics import answer_stats, evidence_level, speaking_stats


def judgment_key(j: Judgment) -> str:
    return f"a_req_{j.subject}" if j.question_id == "a_req" else j.question_id


def load(engine: Engine, run_id: str) -> dict[str, Any]:
    with Session(engine) as s:
        run = s.get(Run, run_id)
        if run is None:
            raise ValueError(f"unknown run {run_id}")
        return {
            "run": run,
            "reqs": list(s.exec(select(Requirement).where(Requirement.run_id == run_id)).all()),
            "topics": {
                t.id: t for t in s.exec(select(PlanTopic).where(PlanTopic.run_id == run_id)).all()
            },
            "turns": sorted(
                s.exec(select(Turn).where(Turn.run_id == run_id)).all(), key=lambda t: t.seq
            ),
            "judgments": list(s.exec(select(Judgment).where(Judgment.run_id == run_id)).all()),
            "feedback": {
                f.turn_id: f
                for f in s.exec(select(Feedback).where(Feedback.run_id == run_id)).all()
            },
        }


def qa_pairs(turns: list[Turn]) -> list[tuple[Turn, Turn]]:
    pairs = []
    for prev, cur in pairwise(turns):
        if prev.role == "interviewer" and cur.role == "candidate" and not cur.practice_of:
            pairs.append((prev, cur))
    return pairs


def build_report(
    engine: Engine, run_id: str, *, mapping: PiiMapping | None = None, store: bool = True
) -> ReportModel:
    d = load(engine, run_id)
    run: Run = d["run"]
    lang = str(run.settings.get("language", "nl"))
    by_turn: dict[str, dict[str, Judgment]] = defaultdict(dict)
    for j in d["judgments"]:
        if j.turn_id:
            by_turn[j.turn_id][judgment_key(j)] = j

    ev = thresholds()["evidence"]
    answers: list[AnswerView] = []
    raw_answers: list[dict[str, Any]] = []
    for question, answer in qa_pairs(d["turns"]):
        topic: PlanTopic | None = d["topics"].get(answer.topic_id or "")
        js = by_turn.get(answer.id, {})
        speaking = speaking_stats(answer.text_pseudonymised, answer.audio_duration_s, lang)
        fb = d["feedback"].get(answer.id)
        answers.append(
            AnswerView(
                turn_id=answer.id,
                topic=topic.goal if topic else "",
                persona=question.persona,
                question=question.text_pseudonymised,
                answer=answer.text_pseudonymised,
                judgments={
                    k: JudgmentView(
                        value=j.answer.get("value", ""),
                        confidence=j.confidence,
                        provider=j.provider,
                        uncertain=j.uncertain,
                        escalated=j.escalated,
                        rationale=j.answer.get("rationale"),
                    )
                    for k, j in js.items()
                },
                feedback=FeedbackView(
                    strengths=fb.strengths, add=fb.add, explore=fb.explore, outline=fb.outline
                )
                if fb
                else None,
                speaking=SpeakingView(
                    duration_s=speaking.duration_s,
                    wpm=speaking.wpm,
                    fillers_per_min=speaking.fillers_per_min,
                )
                if speaking
                else None,
                focus_item_id=topic.focus_item_id if topic else None,
            )
        )
        quality = js.get("a_quality")
        raw_answers.append(
            {
                "turn_id": answer.id,
                "question": question.text_pseudonymised,
                "answer": answer.text_pseudonymised,
                "requirement_ids": topic.requirement_ids if topic else [],
                "quality": float(quality.answer["value"]) if quality else None,
            }
        )

    coverage = []
    for r in sorted(d["reqs"], key=lambda r: (r.kind, r.id)):
        values = [
            float(js[f"a_req_{r.id}"].answer["value"])
            for js in by_turn.values()
            if f"a_req_{r.id}" in js
        ]
        coverage.append(
            RequirementCoverage(
                id=r.id,
                kind=r.kind,
                text=r.text,
                evidence_in_documents=r.evidence_strength,
                evidence_in_interview=evidence_level(
                    max(values) if values else None,
                    float(ev["strong"]),
                    float(ev["partial"]),
                ),
            )
        )

    judged = [
        {k: {"value": j.answer.get("value")} for k, j in by_turn.get(a.turn_id, {}).items()}
        for a in answers
    ]
    stats = answer_stats(judged, float(thresholds()["noul_yes"]))
    spoken = [a.speaking for a in answers if a.speaking]
    if spoken:
        stats["speaking"] = {
            "answers": len(spoken),
            "avg_wpm": round(sum(s.wpm for s in spoken) / len(spoken), 1),
            "avg_fillers_per_min": round(sum(s.fillers_per_min for s in spoken) / len(spoken), 2),
            "avg_duration_s": round(sum(s.duration_s for s in spoken) / len(spoken), 1),
        }

    mastery = {
        j.subject or "": str(j.answer.get("value"))
        for j in d["judgments"]
        if j.question_id == "f_mastery"
    }
    focus = merge_history(
        run.focus_items, mastery, derive_weak_points(stats, coverage, raw_answers, lang)
    )

    cfg = load_models_config()
    jev_versions = {
        str(j.answer.get("model"))
        for j in d["judgments"]
        if j.provider == "jev" and j.answer.get("model")
    }
    report = ReportModel(
        run_id=run.id,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        language=lang,
        vacancy=Vacancy(
            title=run.context.get("title", ""),
            organisation=run.context.get("organisation", ""),
            summary=run.context.get("summary", ""),
        ),
        requirements=coverage,
        answers=answers,
        stats=stats,
        focus_items=focus,
        practice_plan=[
            PracticeAction.model_validate(p) for p in run.briefing.get("practice_plan", [])
        ],
        models=ModelsView(
            jev_version=",".join(sorted(jev_versions)),
            claude=cfg.role("feedback").model,
            local=cfg.role("interviewer").model,
        ),
    )
    if store:
        with Session(engine) as s:
            s.add(Report(run_id=run.id, report_json=report.model_dump(by_alias=True)))
            s.commit()
    if mapping is not None:
        report = ReportModel.model_validate_json(mapping.restore(report.to_json()))
    return report
