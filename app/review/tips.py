"""Curated tips library (spec 5.7): static markdown in knowledge/tips, reviewed by humans.

Models may only select tips by id; they never rewrite them.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

TIPS_DIR = Path(__file__).resolve().parents[2] / "knowledge" / "tips"


@dataclass(frozen=True)
class Tip:
    id: str
    title: str
    body: str


@lru_cache
def all_tips() -> dict[str, Tip]:
    tips = {}
    for path in sorted(TIPS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        _, header, body = text.split("---", 2)
        meta = dict(line.split(":", 1) for line in header.strip().splitlines())
        tip = Tip(meta["id"].strip(), meta["title"].strip(), body.strip())
        tips[tip.id] = tip
    return tips
