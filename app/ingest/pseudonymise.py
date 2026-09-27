"""Pseudonymisation: the only place raw user text becomes ``PseudonymisedText`` (spec 5.1).

Two passes, both on the server:
1. Regex for structured identifiers: e-mail, phone, IBAN, BSN, Dutch postcode, dates of
   birth, profile URLs.
2. The local Qwen model (role ``pseudonymise``, local-only) for names, home addresses and
   other direct identifiers.

Each distinct value gets a stable token per run (``[PERSON_1]``), shared across all
documents and answers of that run. The mapping is stored encrypted (Fernet) so the review and
the downloaded report can show real names to their owner.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import BaseModel

from app.llm.errors import ProviderError
from app.llm.gateway import Gateway
from app.llm.prompts import prompt
from app.llm.text import PseudonymisedText, _mint_pseudonymised
from app.llm.types import Message

EntityType = Literal["person", "address", "city", "other"]

_TOKEN_RE = re.compile(r"\[[A-Z]+_\d+\]")
_TUSSENVOEGSELS = {"van", "de", "der", "den", "het", "ten", "ter", "te", "la", "le", "von", "da"}

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_URL_PROFILE = re.compile(
    r"\b(?:https?://)?(?:www\.)?(?:linkedin\.com/in|github\.com|x\.com|twitter\.com)/[\w\-./]*[\w/]",
    re.I,
)
_PHONE = re.compile(
    r"(?<![\w+])(?:\+|00)\d{2}[\s\-.]?(?:\(0\))?[\d\s\-.]{8,13}\d|\b0\d[\d\s\-.]{7,11}\d\b"
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}\s?(?:[A-Z0-9]{4}\s?){2,7}[A-Z0-9]{1,4}\b")
_POSTCODE = re.compile(r"\b[1-9]\d{3}\s?(?!SA|SD|SS)[A-Z]{2}\b")
_NINE_DIGITS = re.compile(r"\b\d{9}\b")
_DOB = re.compile(
    r"(?i)(?:geboren|geboortedatum|geb\.|date of birth|born|d\.?o\.?b\.?)\s*(?:op|on)?\s*:?\s*"
    r"(\d{1,2}[\-/. ](?:\d{1,2}|[a-z]{3,9})[\-/. ]\d{2,4})"
)


def _iban_ok(value: str) -> bool:
    s = value.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    digits = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(digits) % 97 == 1


def _bsn_ok(value: str) -> bool:
    weights = [9, 8, 7, 6, 5, 4, 3, 2, -1]
    return sum(int(d) * w for d, w in zip(value, weights, strict=True)) % 11 == 0


@dataclass
class PiiMapping:
    """value -> token, per run. Serialisable and encryptable."""

    tokens: dict[str, str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def token_for(self, value: str, kind: str) -> str:
        value = value.strip()
        existing = self.tokens.get(value)
        if existing:
            return existing
        label = kind.upper()
        self.counters[label] = self.counters.get(label, 0) + 1
        token = f"[{label}_{self.counters[label]}]"
        self.tokens[value] = token
        return token

    def alias(self, value: str, token: str) -> None:
        self.tokens.setdefault(value.strip(), token)

    def apply(self, text: str) -> str:
        for value in sorted(self.tokens, key=len, reverse=True):
            if len(value) < 2:
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(value)}(?!\w)", re.I)
            text = pattern.sub(self.tokens[value], text)
        return text

    def restore(self, text: str) -> str:
        """Replace tokens with the original values (for the owner's own view only)."""
        reverse: dict[str, str] = {}
        for value, token in self.tokens.items():
            # the first (longest) value registered for a token is the display form
            if token not in reverse or len(value) > len(reverse[token]):
                reverse[token] = value
        return _TOKEN_RE.sub(lambda m: reverse.get(m.group(0), m.group(0)), text)

    def to_json(self) -> str:
        return json.dumps({"tokens": self.tokens, "counters": self.counters})

    @classmethod
    def from_json(cls, data: str) -> PiiMapping:
        obj = json.loads(data)
        return cls(tokens=dict(obj["tokens"]), counters=dict(obj["counters"]))

    def encrypt(self, key: str) -> bytes:
        return Fernet(key.encode()).encrypt(self.to_json().encode())

    @classmethod
    def decrypt(cls, blob: bytes, key: str) -> PiiMapping:
        return cls.from_json(Fernet(key.encode()).decrypt(blob).decode())


def regex_pass(text: str, mapping: PiiMapping) -> str:
    def sub(pattern: re.Pattern[str], kind: str, check: object = None, group: int = 0) -> None:
        nonlocal text

        def repl(m: re.Match[str]) -> str:
            value = m.group(group)
            if callable(check) and not check(value):
                return m.group(0)
            token = mapping.token_for(value, kind)
            return m.group(0).replace(value, token)

        text = pattern.sub(repl, text)

    sub(_EMAIL, "email")
    sub(_URL_PROFILE, "url")
    sub(_IBAN, "iban", _iban_ok)
    sub(_DOB, "dob", group=1)
    sub(_PHONE, "phone", lambda v: sum(c.isdigit() for c in v) >= 9)
    sub(_NINE_DIGITS, "bsn", _bsn_ok)
    sub(_POSTCODE, "postcode")
    return text


class _Entity(BaseModel):
    text: str
    type: EntityType


class _Entities(BaseModel):
    entities: list[_Entity]


_KIND = {"person": "person", "address": "address", "city": "city", "other": "id"}


def _register_entity(mapping: PiiMapping, entity: _Entity) -> None:
    value = entity.text.strip().strip(".,;:")
    if len(value) < 2 or _TOKEN_RE.fullmatch(value):
        return
    token = mapping.token_for(value, _KIND[entity.type])
    if entity.type == "person":
        # "Jan de Vries" -> also map "Vries"-style surnames and first names to the same token
        parts = [p for p in re.split(r"\s+", value) if p]
        for part in parts:
            if part.lower() not in _TUSSENVOEGSELS and len(part) >= 3 and part[0].isupper():
                mapping.alias(part, token)
        if len(parts) >= 2:
            surname = " ".join(parts[1:])
            if len(surname) >= 3:
                mapping.alias(surname, token)


def _segments(text: str, size: int = 6000) -> list[str]:
    out, current = [], ""
    for para in text.split("\n\n"):
        if current and len(current) + len(para) > size:
            out.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        out.append(current)
    return out


async def pseudonymise(
    gateway: Gateway, text: str, mapping: PiiMapping, *, run_id: str | None = None
) -> PseudonymisedText:
    """Replace personal data in ``text``; updates ``mapping`` in place."""
    text = mapping.apply(regex_pass(text, mapping))
    system = Message("system", prompt("pseudonymise"))
    for segment in _segments(text):
        found: _Entities | None = None
        for _attempt in range(2):  # one retry on invalid JSON; no external fallback (local only)
            try:
                result = await gateway.generate(
                    "pseudonymise", [system, Message("user", segment)], _Entities, run_id=run_id
                )
            except ProviderError:
                continue
            if isinstance(result.parsed, _Entities):
                found = result.parsed
                break
        if found is None:
            raise ProviderError("pseudonymisation failed twice; the run is stopped for safety")
        for entity in found.entities:
            if entity.text.strip() and entity.text.strip() in segment:
                _register_entity(mapping, entity)
    return _mint_pseudonymised(mapping.apply(text))


def pseudonymise_known(text: str, mapping: PiiMapping) -> PseudonymisedText:
    """Regex + already-known values only (no model call). Used for short texts like report
    labels that were built from already-pseudonymised material."""
    return _mint_pseudonymised(mapping.apply(regex_pass(text, mapping)))


def stored(text: str) -> PseudonymisedText:
    """Re-wrap text read back from the database.

    Every user-derived text column is written pseudonymised (see app/ingest/service.py), so
    reading it back is safe; the regex pass runs again as a cheap second line of defence.
    Never call this on text that did not come from the database.
    """
    return _mint_pseudonymised(regex_pass(text, PiiMapping()))
