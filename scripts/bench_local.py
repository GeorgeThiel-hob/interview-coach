"""Speed benchmark for local runtimes and models (M1; spec D1 and risk "local model too slow").

Runs the same interviewer turns and JSON extractions through the gateway for each target and
prints a table. A target is ``provider:model``; the model may itself contain colons.

    uv run python scripts/bench_local.py \
        --target ollama:qwen3.6:35b-a3b --target ollama:qwen3.8:27b \
        --target ollama:qwen3.6:35b-mlx --target omlx:<model-name-in-omlx>

Only one ~20 GB model fits in memory at a time, so the script unloads nothing itself: the
first call per target (loading the model) is timed separately as "load". Run Ollama and oMLX
targets in separate invocations with the other runtime stopped, or both will fight for memory.
Results are also written to eval/bench/results-<timestamp>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import models  # noqa: E402,F401
from app.llm.config import ModelsConfig, load_models_config  # noqa: E402
from app.llm.gateway import build_gateway  # noqa: E402
from app.llm.types import Message  # noqa: E402
from eval.bench.fixtures import (  # noqa: E402
    CV_SNIPPET,
    INTERVIEWER_CASES,
    PERSONA,
    VACANCY_NL,
)


class Requirement(BaseModel):
    kind: str  # eis | wens
    text: str


class Extraction(BaseModel):
    requirements: list[Requirement]


EXTRACT_PROMPT = (
    "Extract every hard requirement (kind 'eis') and nice-to-have (kind 'wens') from the "
    "vacancy below, each as one short sentence in the vacancy's language.\n\n" + VACANCY_NL
)
EXPECTED_EISEN, EXPECTED_WENSEN = 4, 2


def target_config(base: ModelsConfig, provider: str, model: str) -> ModelsConfig:
    roles = {
        name: base.roles[name].model_copy(update={"provider": provider, "model": model})
        for name in ("interviewer", "extract")
    }
    return base.model_copy(update={"roles": roles})


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s])


async def bench(provider: str, model: str, rounds: int) -> dict[str, object]:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    gw = build_gateway(engine, target_config(load_models_config(), provider, model))
    try:
        if not await gw.local_available():
            return {"target": f"{provider}:{model}", "error": f"{provider} not reachable"}

        def turn(case: tuple) -> list[Message]:  # type: ignore[type-arg]
            persona, language, convo, move = case
            system = PERSONA.format(persona=persona, language=language)
            system += f"\n\nVacancy:\n{VACANCY_NL}\nCV:\n{CV_SNIPPET}"
            msgs = [Message("system", system)]
            msgs += [Message(r, t) for r, t in convo]  # type: ignore[arg-type]
            msgs.append(Message("user", f"[Interviewer instruction: {move}]"))
            return msgs

        t0 = time.monotonic()
        await gw.generate("interviewer", turn(INTERVIEWER_CASES[0]))
        load_s = time.monotonic() - t0

        turn_s, tok_s, too_long = [], [], 0
        for _ in range(rounds):
            for case in INTERVIEWER_CASES:
                t0 = time.monotonic()
                out = await gw.generate("interviewer", turn(case))
                dt = time.monotonic() - t0
                turn_s.append(dt)
                if out.usage.tokens_out:
                    tok_s.append(out.usage.tokens_out / dt)
                too_long += sentences(out.text) > 2

        extract_s, valid, exact = [], 0, 0
        for _ in range(rounds):
            t0 = time.monotonic()
            try:
                out = await gw.generate("extract", [Message("user", EXTRACT_PROMPT)], Extraction)
            except Exception:
                extract_s.append(time.monotonic() - t0)
                continue
            extract_s.append(time.monotonic() - t0)
            valid += 1
            reqs = out.parsed.requirements if isinstance(out.parsed, Extraction) else []
            kinds = [r.kind for r in reqs]
            exact += kinds.count("eis") == EXPECTED_EISEN and kinds.count("wens") == EXPECTED_WENSEN

        return {
            "target": f"{provider}:{model}",
            "load_s": round(load_s, 1),
            "turn_p50_s": round(statistics.median(turn_s), 2),
            "turn_max_s": round(max(turn_s), 2),
            "tokens_per_s": round(statistics.median(tok_s), 1) if tok_s else None,
            "turns_over_2_sentences": f"{too_long}/{len(turn_s)}",
            "extract_p50_s": round(statistics.median(extract_s), 2),
            "extract_valid_json": f"{valid}/{rounds}",
            "extract_correct_counts": f"{exact}/{rounds}",
        }
    finally:
        await gw.aclose()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", action="append", required=True, help="provider:model")
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()

    results = []
    for target in args.target:
        provider, _, model = target.partition(":")
        print(f"benchmarking {target} ...", flush=True)
        results.append(await bench(provider, model, args.rounds))

    cols = [
        "target",
        "load_s",
        "turn_p50_s",
        "turn_max_s",
        "tokens_per_s",
        "turns_over_2_sentences",
        "extract_p50_s",
        "extract_valid_json",
        "extract_correct_counts",
    ]
    widths = [max(len(c), *(len(str(r.get(c, ""))) for r in results)) for c in cols]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths, strict=True)))
    print("  ".join("-" * w for w in widths))
    for r in results:
        if "error" in r:
            print(f"{r['target']}  ERROR: {r['error']}")
            continue
        print("  ".join(str(r.get(c, "")).ljust(w) for c, w in zip(cols, widths, strict=True)))

    out = ROOT / "eval" / "bench" / f"results-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nsaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
