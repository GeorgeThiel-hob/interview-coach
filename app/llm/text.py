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

from typing import Final, final

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
