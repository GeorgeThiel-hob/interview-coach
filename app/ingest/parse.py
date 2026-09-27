"""Turn an uploaded file into plain text (spec 5.1, 9.3).

* Only PDF, DOCX, TXT/MD are accepted; the type is sniffed from the bytes, not the filename.
* Parsing runs in a separate process with a timeout, so a malicious or broken file cannot
  hang or crash the app.
* Scanned PDFs (almost no extractable text) are rejected with a clear error: OCR is out of
  scope for v1.
"""

from __future__ import annotations

import hashlib
import io
import multiprocessing as mp
import zipfile
from dataclasses import dataclass
from typing import Literal

FileKind = Literal["pdf", "docx", "text"]

MAX_BYTES_DEFAULT = 10 * 1024 * 1024
PARSE_TIMEOUT_S = 30
MIN_CHARS_PER_PDF_PAGE = 40


class UploadError(ValueError):
    """The upload cannot be used; the message is safe to show to the user."""


@dataclass(frozen=True)
class ParsedFile:
    kind: FileKind
    text: str
    sha256: str
    pages: int | None = None


def sniff(data: bytes, filename: str) -> FileKind:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
        raise UploadError("This zip-based file is not a Word document (.docx).")
    if filename.lower().endswith((".txt", ".md", ".markdown")) or not filename:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise UploadError("Text files must be UTF-8.") from e
        if b"\x00" in data:
            raise UploadError("This does not look like a text file.")
        return "text"
    raise UploadError("Unsupported file type. Upload a PDF, a Word file (.docx) or a text file.")


def _extract(kind: FileKind, data: bytes) -> tuple[str, int | None]:
    if kind == "text":
        return data.decode("utf-8"), None
    if kind == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(p.strip() for p in pages), len(pages)
    from docx import Document

    doc = Document(io.BytesIO(data))
    lines = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(lines), None


def _worker(kind: FileKind, data: bytes, conn: mp.connection.Connection) -> None:
    try:
        conn.send(("ok", _extract(kind, data)))
    except Exception as e:
        conn.send(("error", f"{type(e).__name__}: {e}"))
    finally:
        conn.close()


def _extract_isolated(kind: FileKind, data: bytes, timeout: float) -> tuple[str, int | None]:
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_worker, args=(kind, data, child), daemon=True)
    proc.start()
    child.close()
    try:
        if not parent.poll(timeout):
            raise UploadError("The file took too long to read. Try saving it again as PDF.")
        status, payload = parent.recv()
    finally:
        proc.kill()
        proc.join(1)
        parent.close()
    if status != "ok":
        raise UploadError("The file could not be read. Is it damaged or password-protected?")
    text, pages = payload
    return str(text), pages


def parse_upload(
    data: bytes,
    filename: str,
    *,
    max_bytes: int = MAX_BYTES_DEFAULT,
    timeout: float = PARSE_TIMEOUT_S,
) -> ParsedFile:
    if not data:
        raise UploadError("The file is empty.")
    if len(data) > max_bytes:
        raise UploadError(f"Files may be at most {max_bytes // (1024 * 1024)} MB.")
    kind = sniff(data, filename)
    text, pages = _extract_isolated(kind, data, timeout)
    text = normalise(text)
    if kind == "pdf" and pages and len(text) < MIN_CHARS_PER_PDF_PAGE * pages:
        raise UploadError(
            "This PDF seems to be a scan (no readable text). Scanned PDFs are not supported "
            "yet; export the document as a text-based PDF or Word file."
        )
    if len(text.strip()) < 20:
        raise UploadError("The file contains almost no text.")
    return ParsedFile(kind=kind, text=text, sha256=hashlib.sha256(data).hexdigest(), pages=pages)


def parse_pasted(text: str) -> ParsedFile:
    text = normalise(text)
    if len(text.strip()) < 20:
        raise UploadError("The pasted text is too short.")
    return ParsedFile("text", text, hashlib.sha256(text.encode()).hexdigest())


def normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    lines = [line.rstrip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line == "" and out and out[-1] == "":
            continue
        out.append(line)
    return "\n".join(out).strip()
