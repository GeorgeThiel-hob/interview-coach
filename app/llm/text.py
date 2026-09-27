"""Text types that decide what may leave the server.

External providers (Claude, Jev) only accept ``SafeText``. There are two ways to get one:

* ``PseudonymisedText``: produced by the pseudonymiser after personal data has been replaced
  with tokens. Creating one requires the private ``_MINT`` key, which only the pseudonymiser
  (and tests) may use. ``tests/test_text_types.py`` fails if another module references it.
* ``TrustedText``: text written by us (prompt files, the Jev question catalog). It never
  contains user data. ``tests/test_text_types.py`` limits which modules may construct it.

``SafeText`` deliberately does not subclass ``str``: a plain string can never pass an
``isinstance(x, SafeText)`` check, and ``safe + "raw"`` raises instead of silently mixing.
"""

from __future__ import annotations

import re
from typing import Final, Self, final

_MINT: Final = object()


class SafeText:
    """Text that is allowed to reach an external provider."""

    __slots__ = ("_text",)

    def __init__(self, text: str, *, _key: object) -> None:
        if _key is not _MINT:
            raise TypeError(
                f"{type(self).__name__} can only be created by the pseudonymiser or from "
                "trusted prompt text; raw user text must be pseudonymised first."
            )
        if not isinstance(text, str):
            raise TypeError("text must be a str")
        self._text = text

    @property
    def text(self) -> str:
        return self._text

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return f"{type(self).__name__}({len(self._text)} chars)"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, SafeText) and type(other) is type(self) and other._text == self._text
        )

    def __hash__(self) -> int:
        return hash((type(self).__name__, self._text))

    def __len__(self) -> int:
        return len(self._text)

    def truncated(self, max_chars: int) -> Self:
        """The first ``max_chars`` characters, keeping the same safety type."""
        clone = object.__new__(type(self))
        clone._text = self._text[:max_chars]
        return clone

    def __add__(self, other: SafeText) -> SafeText:
        if not isinstance(other, SafeText):
            return NotImplemented
        return SafeText(self._text + other._text, _key=_MINT)


@final
class PseudonymisedText(SafeText):
    """User-derived text whose personal data has been replaced with tokens."""

    __slots__ = ()


@final
class TrustedText(SafeText):
    """Developer-written text (prompt templates, question catalog). Never user data."""

    __slots__ = ()

    def __init__(self, text: str) -> None:
        super().__init__(text, _key=_MINT)

    def render(self, **values: SafeText) -> SafeText:
        """Fill ``{name}`` placeholders; every value must itself be safe text."""
        for name, value in values.items():
            if not isinstance(value, SafeText):
                raise TypeError(f"value for {{{name}}} is {type(value).__name__}, not SafeText")
        return SafeText(self.text.format(**{k: v.text for k, v in values.items()}), _key=_MINT)


def _mint_pseudonymised(text: str) -> PseudonymisedText:
    """Only for the pseudonymiser (app/ingest/pseudonymise.py) and tests."""
    return PseudonymisedText(text, _key=_MINT)


def fence(label: str, body: SafeText) -> SafeText:
    """Wrap untrusted document text so prompts treat it as data (spec 9.3).

    The closing tag is neutralised inside the body, so a document cannot end the fence early
    and smuggle instructions after it.
    """
    if not isinstance(body, SafeText):
        raise TypeError("fence() needs SafeText; pseudonymise user text first")
    if not label.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"invalid fence label {label!r}")
    inner = body.text.replace("</document", "<\\/document")
    return SafeText(f'<document name="{label}">\n{inner}\n</document>', _key=_MINT)


def join(parts: list[SafeText], sep: str = "\n\n") -> SafeText:
    """Concatenate safe texts with a fixed separator."""
    if not all(isinstance(p, SafeText) for p in parts):
        raise TypeError("join() only accepts SafeText parts")
    return SafeText(sep.join(p.text for p in parts), _key=_MINT)


_LABEL_RE = re.compile(r"[A-Za-z0-9_:.,\-]{0,96}")


def label(value: str | int | float | None) -> TrustedText:
    """Trusted text for short developer identifiers (question keys, option names, numbers).

    Rejects spaces and punctuation, so sentences of user text can never pass through here.
    """
    text = str(value)
    if not _LABEL_RE.fullmatch(text):
        raise ValueError(f"label() only accepts short identifiers, got {text[:40]!r}")
    return TrustedText(text)
