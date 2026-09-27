from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.conftest import Stack

spec = importlib.util.spec_from_file_location(
    "run_eval", Path(__file__).resolve().parents[1] / "scripts" / "run_eval.py"
)
assert spec and spec.loader
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)


async def test_eval_runner_scores_and_recommends(stack: Stack) -> None:
    items = run_eval.load_items(None)
    assert len(items) >= 6 and {i["kind"] for i in items} == {"answer", "question", "document"}
    report = await run_eval.run(stack.gateway, items, 0.9)
    assert {"a_quality", "q_appropriate", "doc_injection", "doc_type"} <= set(report)
    for r in report.values():
        assert 0 <= r["accuracy"] <= 1 and r["n"] >= 1
    # the fake Jev says 0.8 ("yes") to every noul, so the "no"-labelled q_appropriate fails
    assert report["q_appropriate"]["accuracy"] == 0.5


def test_recommend_picks_lowest_cutoff() -> None:
    rows = [(True, 0.9), (True, 0.8), (False, 0.3), (True, 0.2)]
    assert run_eval.recommend(rows, 0.9)["cutoff"] == 0.35
