"""Keeps the escape hatches of app/llm/text.py confined to where they belong."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.llm.text import label

APP = Path(__file__).resolve().parents[1] / "app"

# Who may create PseudonymisedText: the pseudonymiser only (tests are outside app/).
MINT_ALLOWED = {"llm/text.py", "ingest/pseudonymise.py"}
# Where TrustedText may wrap a non-literal: the prompt loader and the question catalog.
TRUSTED_DYNAMIC_ALLOWED = {"llm/text.py", "llm/prompts.py", "judgments/catalog.py"}


def _files() -> list[Path]:
    return list(APP.rglob("*.py"))


def test_only_the_pseudonymiser_mints_pseudonymised_text() -> None:
    rx = re.compile(r"\b_mint_pseudonymised\b|\b_MINT\b")
    offenders = {
        str(p.relative_to(APP)) for p in _files() if rx.search(p.read_text("utf-8"))
    } - MINT_ALLOWED
    assert not offenders, f"only the pseudonymiser may mint PseudonymisedText: {offenders}"


def test_trusted_text_only_wraps_string_literals() -> None:
    offenders: list[str] = []
    for path in _files():
        rel = str(path.relative_to(APP))
        if rel in TRUSTED_DYNAMIC_ALLOWED:
            continue
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "TrustedText"
                and not (
                    len(node.args) == 1
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                )
            ):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, f"TrustedText(...) must wrap a string literal here: {offenders}"


def test_label_rejects_sentences() -> None:
    assert label("a_req_eis_2").text == "a_req_eis_2"
    assert label(0.81).text == "0.81"
    with pytest.raises(ValueError):
        label("Jan de Vries worked at ACME")
