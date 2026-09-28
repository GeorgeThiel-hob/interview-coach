"""Plan rules enforced in code: topic count per length, requirement coverage, closing topic."""

from __future__ import annotations

from app.db.models import Requirement
from app.prep.plan import PlanOut, TopicOut, enforce_plan

SETTINGS = {"length": 15, "interview_type": "mixed"}  # config: 15 min -> 4 topics incl. closing


def topic(goal: str, reqs: list[str], qtype: str = "behavioural") -> TopicOut:
    return TopicOut(
        goal=goal,
        requirement_ids=reqs,
        question_type=qtype,  # type: ignore[arg-type]
        persona="hiring_manager",
        opening_question="?",
    )


def req(rid: str, kind: str = "eis") -> Requirement:
    return Requirement(id=rid, run_id="r", kind=kind, text=rid, evidence_strength="partial")


def test_topic_count_is_capped_and_coverage_moves_to_kept_topics() -> None:
    # the first real demo run: 7 planned topics for a 15-minute interview
    plan = PlanOut(
        topics=[topic(f"t{i}", [f"eis_{i}"]) for i in range(1, 8)] + [topic("close", [], "closing")]
    )
    reqs = [req(f"eis_{i}") for i in range(1, 8)]
    out = enforce_plan(plan, reqs, SETTINGS, set())
    assert len(out) == 4 and out[-1].question_type == "closing"
    assert [t.goal for t in out[:3]] == ["t1", "t2", "t3"]  # order (opening first) is kept
    covered = {r for t in out for r in t.requirement_ids}
    assert covered == {f"eis_{i}" for i in range(1, 8)}  # nothing is lost


def test_uncovered_requirement_joins_a_topic_when_the_plan_is_full() -> None:
    plan = PlanOut(topics=[topic("a", ["eis_1"]), topic("b", ["eis_2"]), topic("c", ["eis_3"])])
    out = enforce_plan(plan, [req(f"eis_{i}") for i in range(1, 5)], SETTINGS, set())
    assert len(out) == 4  # 3 topics + generated closing, no extra topic for eis_4
    assert any("eis_4" in t.requirement_ids for t in out[:3])


def test_uncovered_requirement_gets_its_own_topic_when_there_is_room() -> None:
    plan = PlanOut(topics=[topic("a", ["eis_1"]), topic("close", [], "closing")])
    out = enforce_plan(plan, [req("eis_1"), req("eis_2")], SETTINGS, set())
    assert [t.requirement_ids for t in out] == [["eis_1"], ["eis_2"], []]
