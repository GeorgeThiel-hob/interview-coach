"""Run the Jev question catalog against the labelled eval set (spec 10.2).

Reports accuracy and calibration per question id and recommends thresholds:
* Choice/Score: the lowest min-confidence at which answers kept automatically reach the
  target accuracy (the rest would escalate).
* Noul: the narrowest uncertainty band around 0.5 outside of which the target is reached.

    uv run python scripts/run_eval.py [--subset N] [--target 0.9]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import models  # noqa: E402,F401
from app.ingest.pseudonymise import stored  # noqa: E402
from app.judgments.catalog import CATALOG, GUARDRAIL_IDS  # noqa: E402
from app.llm.gateway import Gateway, build_gateway  # noqa: E402
from app.llm.text import SafeText, fence, join  # noqa: E402

EVAL_DIR = ROOT / "eval"


def load_items(subset: int | None, seed: int = 7) -> list[dict[str, Any]]:
    items = []
    for path in sorted((EVAL_DIR / "set").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(json.loads(line))
    if subset and subset < len(items):
        items = random.Random(seed).sample(items, subset)
    return items


def state_for(item: dict[str, Any]) -> SafeText:
    """Build the same state shape as production code (the eval set is synthetic, no PII)."""
    kind = item["kind"]
    if kind == "answer":
        return join(
            [
                fence("interview_question", stored(item["question"])),
                fence("candidate_answer", stored(item["answer"])),
                fence("planned_topic", stored(item.get("topic", ""))),
                fence(
                    "linked_requirements", stored("\n".join(item.get("requirements", [])) or "none")
                ),
                fence("cv_evidence", stored(item.get("cv", ""))),
            ]
        )
    if kind == "question":
        return join(
            [
                fence("vacancy", stored(item.get("vacancy", ""))),
                fence("topic", stored(item.get("topic", ""))),
                fence("cv_fragments", stored(item.get("cv", ""))),
                fence("conversation", stored(item.get("conversation", ""))),
                fence("question_to_check", stored(item["question"])),
            ]
        )
    return fence("document", stored(item["text"]))


def correct(qid: str, label: Any, value: Any) -> bool:
    kind = CATALOG[qid].kind
    if kind == "noul":
        return (float(value) >= 0.5) == bool(label)
    if kind == "choice":
        return str(value) == str(label)
    return round(float(value)) == int(label)


def certainty(kind: str, value: Any, confidence: float | None) -> float:
    if kind == "noul":
        return abs(float(value) - 0.5) * 2  # 0 at 0.5, 1 at 0 or 1
    return float(confidence or 0.0)


def recommend(rows: list[tuple[bool, float]], target: float) -> dict[str, Any]:
    """Lowest certainty cut-off at which kept answers reach the target accuracy."""
    for cut in [i / 20 for i in range(0, 20)]:
        kept = [ok for ok, c in rows if c >= cut]
        if kept and sum(kept) / len(kept) >= target:
            return {
                "cutoff": cut,
                "kept_share": round(len(kept) / len(rows), 3),
                "kept_accuracy": round(sum(kept) / len(kept), 3),
            }
    return {"cutoff": None, "kept_share": 0.0, "kept_accuracy": None}


async def run(gw: Gateway, items: list[dict[str, Any]], target: float) -> dict[str, Any]:
    per_q: dict[str, list[tuple[bool, float]]] = defaultdict(list)
    for item in items:
        qids = [q for q in item["labels"] if q in CATALOG]
        if not qids:
            continue
        questions = {q: CATALOG[q].build() for q in qids}
        result = await gw.judge(state_for(item), questions)
        for q in qids:
            ans = result.answers[q]
            per_q[q].append(
                (
                    correct(q, item["labels"][q], ans.value),
                    certainty(ans.kind, ans.value, ans.confidence),
                )
            )
    report: dict[str, Any] = {}
    for q, rows in sorted(per_q.items()):
        bins: dict[str, list[bool]] = defaultdict(list)
        for ok, c in rows:
            bins[f"{min(int(c * 5), 4) / 5:.1f}"].append(ok)
        rec = recommend(rows, target)
        kind = CATALOG[q].kind
        suggestion: dict[str, Any] = {}
        if rec["cutoff"] is not None:
            if kind == "noul":
                half = rec["cutoff"] / 2
                suggestion = {"noul_uncertain_band": [round(0.5 - half, 3), round(0.5 + half, 3)]}
            else:
                suggestion = {f"{kind}_min_confidence": rec["cutoff"]}
        report[q] = {
            "n": len(rows),
            "accuracy": round(sum(ok for ok, _ in rows) / len(rows), 3),
            "calibration": {
                b: {"n": len(v), "accuracy": round(sum(v) / len(v), 3)}
                for b, v in sorted(bins.items())
            },
            "recommendation": rec,
            "suggested_config": suggestion,
            "guardrail": q in GUARDRAIL_IDS,
        }
    return report


def write(report: dict[str, Any], target: float, n_items: int) -> Path:
    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (out_dir / f"eval-{stamp}.json").write_text(json.dumps(report, indent=2))
    lines = [
        f"# Eval {stamp}",
        "",
        f"{n_items} items, target accuracy {target:.0%}.",
        "",
        "```",
        f"{'question':<18} {'n':>4} {'acc':>6} {'cutoff':>7} {'kept':>6}  suggestion",
        "-" * 72,
    ]
    for q, r in report.items():
        rec = r["recommendation"]
        lines.append(
            f"{q:<18} {r['n']:>4} {r['accuracy']:>6.2f} {rec['cutoff']!s:>7} "
            f"{rec['kept_share']:>6.2f}  {json.dumps(r['suggested_config'])}"
        )
    lines.append("```")
    path = out_dir / f"eval-{stamp}.md"
    path.write_text("\n".join(lines) + "\n")
    return path


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", type=int, default=None)
    parser.add_argument("--target", type=float, default=0.9)
    args = parser.parse_args()
    items = load_items(args.subset)
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    gw = build_gateway(engine)
    try:
        report = await run(gw, items, args.target)
    finally:
        await gw.aclose()
    path = write(report, args.target, len(items))
    print(path.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
