"""Turning an uploaded file into text segments.

Typed documents are read directly. Scanned PDF pages and photos go through OCR (Tesseract),
which is slower and less exact, so it only runs where there is no text to read.
"""

import io
import logging
import re
from dataclasses import dataclass, field

from mindnest_core.filetypes import IMAGE_EXTENSIONS

from mindnest_worker.chunking import Segment

logger = logging.getLogger("mindnest.parsing")

# A PDF page with fewer characters than this is treated as a scan and sent to OCR.
MIN_PAGE_TEXT_CHARS = 20


class IngestError(Exception):
    """A failure with a short code that the web app shows in the user's language."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Parsed:
    segments: list[Segment] = field(default_factory=list)
    # 0-based indexes of PDF pages with no text layer.
    ocr_pages: list[int] = field(default_factory=list)
    # True when the whole file is a picture.
    ocr_image: bool = False

    @property
    def needs_ocr(self) -> bool:
        return bool(self.ocr_pages) or self.ocr_image


def parse_document(extension: str, data: bytes) -> Parsed:
    try:
        if extension == "pdf":
            return _parse_pdf(data)
        if extension == "pptx":
            return _parse_pptx(data)
        if extension == "docx":
            return _parse_docx(data)
        if extension in {"txt", "md"}:
            return _parse_text(data, markdown=extension == "md")
        if extension in IMAGE_EXTENSIONS:
            return Parsed(ocr_image=True)
    except IngestError:
        raise
    except Exception as exc:
        logger.warning("Could not parse a %s file", extension, exc_info=True)
        raise IngestError("unreadable_file") from exc
    raise IngestError("unsupported_type")


def _parse_pdf(data: bytes) -> Parsed:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        # Many "protected" PDFs open with an empty password; anything else cannot be read.
        if not reader.decrypt(""):
            raise IngestError("encrypted_file")
    parsed = Parsed()
    for index, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if len(text) < MIN_PAGE_TEXT_CHARS:
            parsed.ocr_pages.append(index)
        else:
            parsed.segments.append(Segment(text, page=index + 1))
    return parsed


def _shape_text(shape, parts: list[str]) -> None:  # type: ignore[no-untyped-def]
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        text = "\n".join(p.text for p in shape.text_frame.paragraphs).strip()
        if text:
            parts.append(text)
    if getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    children = getattr(shape, "shapes", None)  # grouped shapes
    if children is not None:
        for child in children:
            _shape_text(child, parts)


def _parse_pptx(data: bytes) -> Parsed:
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(data))
    parsed = Parsed()
    for number, slide in enumerate(presentation.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            _shape_text(shape, parts)
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes is not None and notes.text.strip():
                parts.append(notes.text.strip())
        title = None
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title = slide.shapes.title.text_frame.text.strip() or None
        if parts:
            parsed.segments.append(Segment("\n\n".join(parts), page=number, section=title))
    return parsed


def _parse_docx(data: bytes) -> Parsed:
    from docx import Document

    document = Document(io.BytesIO(data))
    parsed = Parsed()
    section: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        text = "\n\n".join(buffer).strip()
        if text:
            parsed.segments.append(Segment(text, section=section))
        buffer.clear()

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = paragraph.style.name if paragraph.style is not None else ""
        if style and style.lower().startswith(("heading", "title")):
            flush()
            section = text[:200]
        buffer.append(text)
    flush()

    for table in document.tables:
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            parsed.segments.append(Segment("\n".join(rows), section="table"))
    return parsed


def _decode(data: bytes) -> str:
    # UTF-16 is only trusted when it announces itself with a byte-order mark: without one,
    # almost any even-length byte string "decodes" as UTF-16 into nonsense.
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeError:
            pass
    try:
        return data.decode("utf-8-sig")
    except UnicodeError:
        return data.decode("cp1252", errors="replace")


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def _parse_text(data: bytes, markdown: bool) -> Parsed:
    text = _decode(data)
    parsed = Parsed()
    if not markdown:
        if text.strip():
            parsed.segments.append(Segment(text))
        return parsed
    # Split Markdown at headings so each passage knows which section it belongs to.
    matches = list(_MD_HEADING.finditer(text))
    if not matches:
        if text.strip():
            parsed.segments.append(Segment(text))
        return parsed
    intro = text[: matches[0].start()].strip()
    if intro:
        parsed.segments.append(Segment(intro))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if body:
            parsed.segments.append(Segment(body, section=match.group(2).strip()[:200]))
    return parsed


# --- OCR -------------------------------------------------------------------------------------


def _ocr_image(image, languages: str) -> str:  # type: ignore[no-untyped-def]
    import pytesseract

    try:
        return str(pytesseract.image_to_string(image, lang=languages))
    except pytesseract.TesseractError:
        # A missing language pack should degrade to English, not fail the whole upload.
        logger.warning("Tesseract failed with languages %s; retrying with English", languages)
        return str(pytesseract.image_to_string(image, lang="eng"))


def run_ocr(
    extension: str, data: bytes, parsed: Parsed, languages: str, max_pages: int
) -> list[Segment]:
    """OCR the scanned pages (or the image) and return the extra segments."""
    import pytesseract
    from PIL import Image

    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError as exc:
        raise IngestError("ocr_unavailable") from exc

    segments: list[Segment] = []
    if parsed.ocr_image:
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
        except Exception as exc:  # corrupt files and decompression bombs
            raise IngestError("unreadable_file") from exc
        image.thumbnail((4000, 4000))
        text = _ocr_image(image.convert("RGB"), languages).strip()
        if text:
            segments.append(Segment(text, page=1))
        return segments

    if len(parsed.ocr_pages) > max_pages:
        raise IngestError("too_many_scanned_pages")
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        for index in parsed.ocr_pages:
            bitmap = document[index].render(scale=200 / 72)
            text = _ocr_image(bitmap.to_pil().convert("RGB"), languages).strip()
            if text:
                segments.append(Segment(text, page=index + 1))
    finally:
        document.close()
    return segments
