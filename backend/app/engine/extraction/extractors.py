"""Text extraction layer.

PDF -> PyMuPDF, DOCX -> python-docx, TXT -> native reader.
Every extractor returns the same :class:`ExtractedDocument` so the knowledge
extraction stage never needs to know the source format.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".text"}
MAX_CHARACTERS = 400_000


class ExtractionError(RuntimeError):
    """Raised when a document cannot be read at all."""


@dataclass(slots=True)
class ExtractedPage:
    number: int
    text: str


@dataclass(slots=True)
class ExtractedDocument:
    text: str
    pages: list[ExtractedPage] = field(default_factory=list)
    page_count: int = 0
    extractor: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\S+", self.text))


_WS_RE = re.compile(r"[ \t\x0b\f\r]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")
# Ligatures and typographic characters that break keyword matching in PDFs.
_CHAR_FIXES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\u00a0": " ",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2022": "* ",
    "\u25cf": "* ",
    "\u2192": "->",
    "\u00d7": "x",
    "\u2264": "<=",
    "\u2265": ">=",
}
_CHAR_RE = re.compile("|".join(map(re.escape, _CHAR_FIXES)))


def normalize_text(raw: str) -> str:
    text = _CHAR_RE.sub(lambda m: _CHAR_FIXES[m.group(0)], raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _MULTI_NL_RE.sub("\n\n", text).strip()


def _truncate(text: str) -> tuple[str, list[str]]:
    if len(text) <= MAX_CHARACTERS:
        return text, []
    return (
        text[:MAX_CHARACTERS],
        [f"Document truncated to {MAX_CHARACTERS} characters for analysis."],
    )


# ------------------------------------------------------------------------------ pdf
def extract_pdf(data: bytes) -> ExtractedDocument:
    pymupdf: Any
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - older wheels expose fitz only
        try:
            import fitz

            pymupdf = fitz
        except ImportError as exc:  # pragma: no cover
            raise ExtractionError("PyMuPDF is required for PDF extraction") from exc

    warnings: list[str] = []
    pages: list[ExtractedPage] = []
    metadata: dict[str, str] = {}
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.is_encrypted and not doc.authenticate(""):
                raise ExtractionError("PDF is password protected")
            raw_meta = doc.metadata or {}
            metadata = {k: str(v) for k, v in raw_meta.items() if v}
            if getattr(doc, "needs_pass", False):
                raise ExtractionError("PDF is password protected")
            for index in range(doc.page_count):
                page_text = doc.load_page(index).get_text("text") or ""
                if not page_text.strip():
                    warnings.append(f"Page {index + 1} has no extractable text (scanned image?).")
                pages.append(ExtractedPage(number=index + 1, text=page_text))
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Could not read PDF: {exc}") from exc

    if not any(p.text.strip() for p in pages):
        raise ExtractionError(
            "No text layer found in the PDF. Scanned/image PDFs need OCR, which this "
            "build does not run yet."
        )

    body = "\n\n".join(p.text for p in pages)
    body, trunc_warnings = _truncate(body)
    warnings.extend(trunc_warnings)
    return ExtractedDocument(
        text=normalize_text(body),
        pages=[ExtractedPage(p.number, normalize_text(p.text)) for p in pages],
        page_count=len(pages),
        extractor="pymupdf",
        warnings=warnings,
        metadata=metadata,
    )


# ----------------------------------------------------------------------------- docx
def extract_docx(data: bytes) -> ExtractedDocument:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("python-docx is required for DOCX extraction") from exc

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise ExtractionError(f"Could not read DOCX: {exc}") from exc

    blocks: list[tuple[str, str]] = []

    def walk_table(table) -> None:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                blocks.append(("table", " | ".join(cells)))

    body = document.element.body
    # Preserve document order (paragraphs and tables interleaved).
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            text = "".join(node.text or "" for node in child.iter() if node.tag.endswith("}t"))
            style = child.find(
                ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pStyle"
            )
            style_name = (
                style.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
                if style is not None
                else None
            )
            if text.strip():
                blocks.append((style_name or "", text))
        elif tag == "tbl":
            for table in document.tables:
                if table._element is child:
                    walk_table(table)
                    break

    headings: list[str] = []
    for style, text in blocks:
        if style and style.lower().startswith(("heading", "title")):
            headings.append(text.strip())

    body_text = "\n".join(text for _, text in blocks)
    body_text, trunc_warnings = _truncate(body_text)
    warnings = list(trunc_warnings)
    if not body_text.strip():
        raise ExtractionError("DOCX contains no readable text")

    props = document.core_properties
    metadata = {"title": props.title or "", "author": props.author or ""}
    return ExtractedDocument(
        text=normalize_text(body_text),
        pages=[ExtractedPage(1, normalize_text(body_text))],
        page_count=1,
        extractor="python-docx",
        warnings=warnings,
        metadata={k: v for k, v in metadata.items() if v}
        | ({"headings": " | ".join(headings[:20])} if headings else {}),
    )


# ------------------------------------------------------------------------------ txt
def extract_txt(data: bytes) -> ExtractedDocument:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            raw = data.decode(encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    else:  # pragma: no cover - latin-1 never fails
        raw = data.decode("utf-8", errors="replace")

    if "\x00" in raw[:2048]:
        raise ExtractionError("File looks binary, not a text document")

    text, warnings = _truncate(raw)
    # A plain text file has no pages. Reporting the line count here would show
    # "127 pages" in the UI, so it is counted as a single logical document and
    # word_count carries the real size.
    return ExtractedDocument(
        text=normalize_text(text),
        pages=[ExtractedPage(1, normalize_text(text))],
        page_count=1,
        extractor="native",
        warnings=warnings,
        metadata={"lines": str(len(raw.splitlines()))},
    )


# ------------------------------------------------------------------------- dispatch
_EXTRACTORS = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".txt": extract_txt,
    ".md": extract_txt,
    ".text": extract_txt,
}


def detect_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def extract(filename: str, data: bytes) -> ExtractedDocument:
    """Extract text from an uploaded file by extension."""
    ext = detect_extension(filename)
    if ext == ".doc":
        raise ExtractionError(
            "Legacy .doc is not supported. Save as .docx, PDF or TXT and re-upload."
        )
    if ext not in _EXTRACTORS:
        raise ExtractionError(
            f"Unsupported file type '{ext or filename}'. Upload a PDF, DOCX or TXT file."
        )
    if not data:
        raise ExtractionError("Uploaded file is empty")
    if ext == ".docx" and _looks_like_zip_but_not_docx(data):
        raise ExtractionError("File has a .docx name but is not a valid Word document")
    doc = _EXTRACTORS[ext](data)
    if not doc.text.strip():
        raise ExtractionError("No readable text was found in the document")
    return doc


def _looks_like_zip_but_not_docx(data: bytes) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" not in archive.namelist()
    except zipfile.BadZipFile:
        return True


def store_upload(data: bytes, filename: str, subject_id: int) -> str:
    """Persist the raw upload under ``STORAGE_DIR`` and return its path."""
    safe_name = Path(filename).name.replace("..", "_")
    target_dir = settings.storage_dir / f"subject_{subject_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / safe_name
    counter = 1
    while path.exists():
        path = target_dir / f"{Path(safe_name).stem}_{counter}{detect_extension(safe_name)}"
        counter += 1
    path.write_bytes(data)
    return str(path)
