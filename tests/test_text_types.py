"""Keeps the escape hatches of app/llm/text.py confined to the modules allowed to use them."""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# Who may create PseudonymisedText: the pseudonymiser only (tests are outside app/).
MINT_ALLOWED = {"llm/text.py", "ingest/pseudonymise.py"}
# Who may create TrustedText: prompt/catalog code that holds developer-written text.
TRUSTED_ALLOWED = {
    "llm/text.py",
    "llm/prompts.py",
    "judgments/catalog.py",
    "prompts.py",
}


def _users(pattern: str) -> set[str]:
    rx = re.compile(pattern)
    return {str(p.relative_to(APP)) for p in APP.rglob("*.py") if rx.search(p.read_text("utf-8"))}


def test_only_the_pseudonymiser_mints_pseudonymised_text() -> None:
    offenders = _users(r"\b_mint_pseudonymised\b|\b_MINT\b") - MINT_ALLOWED
    assert not offenders, f"only the pseudonymiser may mint PseudonymisedText: {offenders}"


def test_trusted_text_is_only_built_from_developer_text() -> None:
    offenders = _users(r"\bTrustedText\(") - TRUSTED_ALLOWED
    assert not offenders, f"TrustedText(...) may only wrap prompt/catalog text: {offenders}"
