"""Report export and import (spec 5.8).

``report.pdf`` is rendered with WeasyPrint and carries ``report.json`` as an embedded file
attachment, so the user only needs to keep one file. Import accepts the JSON or that PDF.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import ValidationError

from app.report.schema import SCHEMA_VERSION, Report
from app.review.tips import all_tips
from app.web.i18n import translate

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
ATTACHMENT_NAME = "report.json"


class ReportImportError(ValueError):
    """Shown to the user as-is."""


def _env() -> Environment:
    return Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


def render_html(report: Report) -> str:
    lang = report.language
    return (
        _env()
        .get_template("report_pdf.html")
        .render(r=report, tips=all_tips(), t=lambda key: translate(key, lang))
    )


def to_pdf(report: Report) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from weasyprint import HTML  # type: ignore[import-untyped]

    pdf = HTML(string=render_html(report)).write_pdf()
    assert pdf is not None
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    writer.add_attachment(ATTACHMENT_NAME, report.to_json().encode("utf-8"))
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def load_report(data: bytes, filename: str = "") -> Report:
    if data.startswith(b"%PDF-"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        attached = reader.attachments.get(ATTACHMENT_NAME)
        if not attached:
            raise ReportImportError(
                "This PDF has no embedded report data. Upload the report PDF downloaded from "
                "Interview Coach, or its report.json."
            )
        data = attached[0]
    try:
        raw = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ReportImportError("This is not a valid report file.") from e
    version = raw.get("schema") if isinstance(raw, dict) else None
    if version != SCHEMA_VERSION:
        raise ReportImportError(
            f"Unsupported report version {version!r}; this app reads {SCHEMA_VERSION}."
        )
    try:
        return Report.model_validate(raw)
    except ValidationError as e:
        raise ReportImportError("The report file is incomplete or damaged.") from e
