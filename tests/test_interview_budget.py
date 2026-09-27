"""Time budget: follow-ups may only use time that is left after every remaining topic."""

from __future__ import annotations

from app.interview.engine import follow_up_fits

MIN = 60.0


def test_first_real_run_no_follow_up_after_slow_answer() -> None:
    # 15-minute interview, 4 topics, first answer took 3.5 minutes (the 2026-09-27 run).
    # Three topics are still to come: 3 x 3.5 = 10.5 min of the 11.5 left, no room for a follow-up.
    assert not follow_up_fits(
        elapsed_s=3.5 * MIN,
        exchanges_done=1,
        topics_left=3,
        budget_s=15 * MIN,
        min_exchange_s=2 * MIN,
    )


def test_follow_up_allowed_when_answers_are_quick() -> None:
    # 1-minute answers: the configured 2 minutes per exchange is the estimate; 14 - 3 x 2 = 8 min left.
    assert follow_up_fits(
        elapsed_s=1 * MIN,
        exchanges_done=1,
        topics_left=3,
        budget_s=15 * MIN,
        min_exchange_s=2 * MIN,
    )


def test_last_topic_may_use_the_remaining_time() -> None:
    assert follow_up_fits(
        elapsed_s=10 * MIN,
        exchanges_done=4,
        topics_left=0,
        budget_s=15 * MIN,
        min_exchange_s=2 * MIN,
    )


def test_out_of_time_never_allows_a_follow_up() -> None:
    assert not follow_up_fits(
        elapsed_s=16 * MIN,
        exchanges_done=5,
        topics_left=0,
        budget_s=15 * MIN,
        min_exchange_s=2 * MIN,
    )


def test_no_exchanges_yet_uses_the_configured_minimum() -> None:
    assert follow_up_fits(
        elapsed_s=0.0, exchanges_done=0, topics_left=3, budget_s=15 * MIN, min_exchange_s=2 * MIN
    )
