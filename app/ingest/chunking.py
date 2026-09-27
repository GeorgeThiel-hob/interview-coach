"""Split documents into chunks with stable IDs for retrieval and citations (spec 5.1).

CV:      per role (``cv:role2:h`` header, ``cv:role2:b3`` bullets) and other paragraphs
         (``cv:p4``, e.g. summary, education, skills).
Vacancy: per paragraph and bullet (``vac:p3``, ``vac:b7``). Extracted requirements get their
         own IDs later (``vac:eis4``, ``vac:wens1``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BULLET = re.compile(r"^\s*(?:[-*•–·▪◦]|\d{1,2}[.)])\s+")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_ROLE_HINT = re.compile(r"\b(bij|at|@|te)\b|[-–|]", re.I)
_SECTION = re.compile(
    r"^(opleiding(en)?|education|skills|vaardigheden|talen|languages|certificat\w*|"
    r"cursussen|courses|hobby\w*|interesses|interests|profiel|profile|samenvatting|summary|"
    r"werkervaring|work experience|experience|nevenactiviteiten|publicaties|projects|projecten)\b",
    re.I,
)


@dataclass(frozen=True)
class TextChunk:
    ref: str
    text: str


def _paragraphs(text: str) -> list[list[str]]:
    blocks: list[list[str]] = [[]]
    for line in text.split("\n"):
        if line.strip():
            blocks[-1].append(line.strip())
        elif blocks[-1]:
            blocks.append([])
    return [b for b in blocks if b]


def _is_role_header(line: str) -> bool:
    return (
        not _BULLET.match(line)
        and len(line) < 160
        and bool(_YEAR.search(line))
        and bool(_ROLE_HINT.search(line))
    )


def split_cv(text: str) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    role = 0
    bullet = 0
    para = 0
    in_role = False
    for block in _paragraphs(text):
        loose: list[str] = []
        for line in block:
            if _SECTION.match(line):
                in_role = False
            if _is_role_header(line):
                if loose:
                    para += 1
                    chunks.append(TextChunk(f"cv:p{para}", " ".join(loose)))
                    loose = []
                role += 1
                bullet = 0
                in_role = True
                chunks.append(TextChunk(f"cv:role{role}:h", line))
            elif _BULLET.match(line) and in_role:
                bullet += 1
                chunks.append(TextChunk(f"cv:role{role}:b{bullet}", _BULLET.sub("", line)))
            elif in_role and not loose and chunks and chunks[-1].ref == f"cv:role{role}:h":
                # a description line directly under a role header belongs to that role
                bullet += 1
                chunks.append(TextChunk(f"cv:role{role}:b{bullet}", line))
            else:
                loose.append(_BULLET.sub("", line))
        if loose:
            para += 1
            in_role = False
            chunks.append(TextChunk(f"cv:p{para}", " ".join(loose)))
    return chunks


def split_vacancy(text: str) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    para = 0
    bullet = 0
    for block in _paragraphs(text):
        loose: list[str] = []
        for line in block:
            if _BULLET.match(line):
                if loose:
                    para += 1
                    chunks.append(TextChunk(f"vac:p{para}", " ".join(loose)))
                    loose = []
                bullet += 1
                chunks.append(TextChunk(f"vac:b{bullet}", _BULLET.sub("", line)))
            else:
                loose.append(line)
        if loose:
            para += 1
            chunks.append(TextChunk(f"vac:p{para}", " ".join(loose)))
    return chunks


def split_other(text: str, prefix: str) -> list[TextChunk]:
    return [TextChunk(f"{prefix}:p{i}", " ".join(b)) for i, b in enumerate(_paragraphs(text), 1)]
