"""Everything countable is computed here, in code (spec 5.4, 5.6). No model does arithmetic.

Inputs are stored turns and judgments; outputs feed the stats dashboard and the report.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

FILLERS_PATH = Path(__file__).resolve().parents[2] / "config" / "fillers.yaml"
STAR = ("a_star_s", "a_star_t", "a_star_a", "a_star_r")
# Target bands (spec 5.6). [DECISION: tune] - kept here until the owner tunes them.
WPM_BAND = (120.0, 160.0)
BEHAVIOURAL_DURATION_BAND = (60.0, 120.0)


@lru_cache
def fillers() -> dict[str, list[str]]:
    with FILLERS_PATH.open(encoding="utf-8") as f:
        data: dict[str, list[str]] = yaml.safe_load(f)
    return data


def words(text: str) -> list[str]:
    return re.findall(r"[\w'’-]+", text, flags=re.UNICODE)


def filler_count(text: str, language: str) -> int:
    lowered = " " + re.sub(r"\s+", " ", text.lower()) + " "
    total = 0
    for filler in sorted(fillers().get(language, []), key=len, reverse=True):
        pattern = re.compile(rf"(?<![\w]){re.escape(filler)}(?![\w])")
        total += len(pattern.findall(lowered))
        lowered = pattern.sub(" ", lowered)  # don't count "zeg maar" and "maar" twice
    return total


@dataclass(frozen=True)
class Speaking:
    duration_s: float
    words: int
    wpm: float
    fillers: int
    fillers_per_min: float
    in_wpm_band: bool


def speaking_stats(text: str, duration_s: float | None, language: str) -> Speaking | None:
    if not duration_s or duration_s <= 0:
        return None
    n = len(words(text))
    minutes = duration_s / 60
    f = filler_count(text, language)
    wpm = n / minutes
    return Speaking(
        duration_s=round(duration_s, 1),
        words=n,
        wpm=round(wpm, 1),
        fillers=f,
        fillers_per_min=round(f / minutes, 2),
        in_wpm_band=WPM_BAND[0] <= wpm <= WPM_BAND[1],
    )


def evidence_level(value: float | None, strong: float, partial: float) -> str:
    if value is None:
        return "none"
    return "strong" if value >= strong else "partial" if value >= partial else "none"


def rate(flags: list[bool]) -> float:
    return round(sum(flags) / len(flags), 3) if flags else 0.0


def answer_stats(judged: list[dict[str, Any]], noul_yes: float) -> dict[str, Any]:
    """``judged``: one dict per answer: {question_id: {"value": ..., ...}}."""

    def yes(j: dict[str, Any], qid: str) -> bool | None:
        v = j.get(qid, {}).get("value")
        return None if v is None else float(v) >= noul_yes

    star_rates = {}
    for qid in STAR:
        flags = [f for j in judged if (f := yes(j, qid)) is not None]
        star_rates[qid.removeprefix("a_star_").upper()] = rate(flags)
    quality = Counter(round(float(j["a_quality"]["value"])) for j in judged if "a_quality" in j)
    consistency = Counter(
        str(j["a_cv_consistency"]["value"]) for j in judged if "a_cv_consistency" in j
    )
    return {
        "star_rates": star_rates,
        "specific_rate": rate([f for j in judged if (f := yes(j, "a_specific")) is not None]),
        "quantified_rate": rate([f for j in judged if (f := yes(j, "a_quantified")) is not None]),
        "overclaim_rate": rate([f for j in judged if (f := yes(j, "a_overclaim")) is not None]),
        "quality_distribution": {str(k): quality.get(k, 0) for k in range(4)},
        "cv_consistency": dict(consistency),
        "answers": len(judged),
    }
