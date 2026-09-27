"""End to end with fake providers: prepare -> interview -> review -> report -> follow-up run.

Covers the M1 flow, the M3 report/feedback rules and the M4 acceptance criterion (a second
run with the first report re-tests at least 3 previous weak points with new questions).
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.db.models import Feedback, Judgment, PlanTopic, Run, Turn
from app.ingest.parse import parse_pasted
from app.interview.engine import InterviewEngine
from app.llm.types import JudgeAnswer
from app.pipeline import add_document, create_run, finish, prepare
from app.report.export import load_report, to_pdf
from app.report.schema import Report
from tests.conftest import CV, VACANCY, Stack

WEAK = {"a_star_r": 0.1, "a_quantified": 0.1, "a_specific": 0.2}


def weak_answers(key, q, state):  # type: ignore[no-untyped-def]
    if key in WEAK:
        return JudgeAnswer("noul", WEAK[key], None)
    return None


async def run_once(st: Stack, previous: Report | None = None) -> tuple[str, Report]:
    run_id = create_run(st.engine, {"language": "nl", "length": 15, "interview_type": "mixed"})
    for kind, text in (("vacancy", VACANCY), ("cv", CV)):
        await add_document(
            st.gateway, st.engine, run_id, kind, f"{kind}.txt", parse_pasted(text), st.key
        )
    await prepare(st.gateway, st.engine, run_id, st.key, previous=previous)

    ie = InterviewEngine(st.gateway, st.engine, run_id, st.key)
    question = await ie.start()
    assert question.role == "interviewer"
    # pause and resume with a fresh engine: the open question comes back
    ie.pause()
    ie = InterviewEngine(st.gateway, st.engine, run_id, st.key)
    assert (await ie.start()).id == question.id

    for n in range(40):
        result = await ie.answer(
            f"Bij ACME bouwde ik met Petra Jansen een pipeline ({n}). Dat ging goed."
        )
        if result.finished:
            break
    else:
        raise AssertionError("interview never finished")
    await ie.drain()
    return run_id, await finish(st.gateway, st.engine, run_id, st.key)


async def test_full_run_and_follow_up(stack: Stack) -> None:
    stack.jev.handlers["judge"] = weak_answers
    run_id, report = await run_once(stack)

    with Session(stack.engine) as s:
        run = s.get(Run, run_id)
        turns = s.exec(select(Turn).where(Turn.run_id == run_id)).all()
        feedback = s.exec(select(Feedback).where(Feedback.run_id == run_id)).all()
        judgments = s.exec(select(Judgment).where(Judgment.run_id == run_id)).all()
    assert run is not None and run.status == "done"

    # interview shape: follow-ups are capped, the interview ends in the closing topic
    assert len(report.answers) >= 4
    assert all("Petra Jansen" not in t.text_pseudonymised for t in turns)  # stored pseudonymised
    assert any("Petra Jansen" in a.answer for a in report.answers)  # restored in the download

    # every answer was evaluated, with STAR + next_move, and the engine logged provider data
    evaluated = {j.turn_id for j in judgments if j.question_id == "a_quality"}
    assert {a.turn_id for a in report.answers} <= evaluated
    assert {"a_star_s", "a_star_r", "next_move", "a_req"} <= {j.question_id for j in judgments}

    # M3: every feedback item has a source; invented sources and non-questions are removed
    assert feedback
    for fb in feedback:
        for section in (fb.strengths, fb.add, fb.explore, fb.outline):
            assert all(item["sources"] for item in section)
        assert all(item["text"].endswith("?") for item in fb.explore)
        assert not any("cv:nope" in item["sources"] for item in fb.add)
        assert fb.dropped >= 2
    assert report.practice_plan and "turn:bogus" not in report.practice_plan[0].links
    assert "tip:star" in report.practice_plan[0].links

    # stats and weak points computed in code
    assert report.stats["star_rates"]["R"] == 0.0
    focus_ids = {f.id for f in report.focus_items}
    assert {"star_r", "quantified", "specific"} <= focus_ids

    # M3: the PDF opens and carries the JSON; import accepts it
    pdf = to_pdf(report)
    assert pdf.startswith(b"%PDF-")
    imported = load_report(pdf, "report.pdf")
    assert imported.run_id == run_id and len(imported.answers) == len(report.answers)

    # M4: a second run with the first report re-tests >= 3 weak points with new questions
    run2, report2 = await run_once(stack, previous=imported)
    with Session(stack.engine) as s:
        run2_row = s.get(Run, run2)
        topics = s.exec(select(PlanTopic).where(PlanTopic.run_id == run2)).all()
        turns2 = s.exec(select(Turn).where(Turn.run_id == run2)).all()
        mastery = s.exec(
            select(Judgment).where(Judgment.run_id == run2, Judgment.question_id == "f_mastery")
        ).all()
    assert run2_row is not None and len(run2_row.focus_items) >= 3
    retested = [t for t in topics if t.focus_item_id]
    assert len(retested) >= 3
    old_questions = {a.question for a in report.answers}
    asked_on_focus = [
        t.text_pseudonymised
        for t in turns2
        if t.role == "interviewer" and t.topic_id in {x.id for x in retested}
    ]
    assert len(asked_on_focus) >= 3 and not set(asked_on_focus) & old_questions
    assert len({m.subject for m in mastery}) >= 3
    # the trend is recorded: history grows by this run's mastery result
    item = next(f for f in report2.focus_items if f.id == "star_r")
    assert len(item.history) >= 2
