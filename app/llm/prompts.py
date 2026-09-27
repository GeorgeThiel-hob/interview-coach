"""Load prompt files from prompts/ as TrustedText (developer-written, versioned in git)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.llm.text import TrustedText

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@lru_cache
def prompt(name: str) -> TrustedText:
    """``prompt("plan")`` reads prompts/plan.md; ``prompt("personas/technical_lead")`` too."""
    path = (PROMPTS_DIR / f"{name}.md").resolve()
    if PROMPTS_DIR not in path.parents:
        raise ValueError(f"prompt {name!r} is outside prompts/")
    return TrustedText(path.read_text(encoding="utf-8").strip())
