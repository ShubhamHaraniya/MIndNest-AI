"""Unit tests for reading and splitting documents. No database or services needed."""

import io

import pytest
from mindnest_worker.chunking import Segment, chunk_segments, split_text
from mindnest_worker.language import detect_language
from mindnest_worker.parsing import IngestError, parse_document


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of text per page (no parentheses in the text)."""
    count = len(pages)
    font_id = 3 + 2 * count
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
    ]
    for i, text in enumerate(pages):
        page_id = 3 + 2 * i
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {page_id + 1} 0 R "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
            ).encode()
        )
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


# --- language ---------------------------------------------------------------------------


def test_language_detection():
    assert detect_language("A process is a program in execution.") == "en"
    assert detect_language("प्रक्रिया वह प्रोग्राम है जो चल रहा हो।") == "hi"
    assert detect_language("પ્રક્રિયા એ ચાલી રહેલો પ્રોગ્રામ છે.") == "gu"
    assert detect_language("") == "en"
    assert detect_language("1234 -- ***") == "en"
    # One Hindi word inside English text does not flip the language.
    assert detect_language("The word प्रक्रिया means process in this long English sentence") == "en"


# --- chunking ---------------------------------------------------------------------------


def test_short_text_is_one_chunk():
    assert split_text("A short note.", 800, 120) == ["A short note."]


def test_long_text_respects_the_size_limit_and_keeps_all_words():
    sentence = "Threads share the memory of their process and run independently. "
    text = sentence * 60
    chunks = split_text(text, max_chars=300, overlap=60)
    assert len(chunks) > 3
    assert all(len(chunk) <= 300 for chunk in chunks)
    joined = " ".join(chunks)
    assert joined.count("Threads share") >= 60  # nothing lost (overlap may repeat some)


def test_neighbouring_chunks_overlap():
    words = " ".join(f"word{i}" for i in range(400))
    chunks = split_text(words, max_chars=300, overlap=80)
    assert len(chunks) >= 3
    for before, after in zip(chunks, chunks[1:], strict=False):
        last_word = before.split()[-1]
        assert last_word in after


def test_paragraphs_are_packed_and_pdf_line_breaks_are_folded():
    text = "First line of a sentence\nthat continues here.\n\nSecond paragraph."
    assert split_text(text, 800, 120) == ["First line of a sentence that continues here.\nSecond paragraph."]


def test_devanagari_danda_is_a_sentence_boundary():
    sentence = "यह एक वाक्य है जो काफ़ी लंबा है। "
    chunks = split_text(sentence * 30, max_chars=200, overlap=0)
    assert all(len(chunk) <= 200 for chunk in chunks)
    assert all(chunk.rstrip().endswith("।") for chunk in chunks)


def test_text_without_spaces_is_still_split():
    chunks = split_text("x" * 2000, max_chars=500, overlap=0)
    assert len(chunks) == 4 and all(len(c) <= 500 for c in chunks)


def test_chunk_segments_keeps_location_and_skips_noise():
    segments = [
        Segment("Real content about operating systems.", page=3, section="Intro"),
        Segment("— 12 —", page=4),
    ]
    chunks = chunk_segments(segments, 800, 120)
    assert len(chunks) == 1
    assert chunks[0].page == 3 and chunks[0].section == "Intro" and chunks[0].language == "en"


# --- parsing ----------------------------------------------------------------------------


def test_pdf_pages_become_segments_with_page_numbers():
    parsed = parse_document(
        "pdf", make_pdf(["Processes have their own address space.", "Threads share memory with peers."])
    )
    assert [s.page for s in parsed.segments] == [1, 2]
    assert "address space" in parsed.segments[0].text
    assert not parsed.needs_ocr


def test_pdf_page_without_text_is_queued_for_ocr():
    parsed = parse_document("pdf", make_pdf(["", "This second page has real typed text."]))
    assert parsed.ocr_pages == [0]
    assert [s.page for s in parsed.segments] == [2]
    assert parsed.needs_ocr


def test_a_broken_pdf_is_reported_as_unreadable():
    with pytest.raises(IngestError) as caught:
        parse_document("pdf", b"%PDF-1.4 this is not really a pdf at all")
    assert caught.value.code == "unreadable_file"


def test_docx_headings_become_sections_and_tables_are_kept():
    from docx import Document

    document = Document()
    document.add_heading("Scheduling", level=1)
    document.add_paragraph("Round robin gives each process a time slice.")
    document.add_heading("Deadlocks", level=1)
    document.add_paragraph("A deadlock needs four conditions.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Algorithm"
    table.rows[0].cells[1].text = "Preemptive"
    buffer = io.BytesIO()
    document.save(buffer)

    parsed = parse_document("docx", buffer.getvalue())
    sections = [s.section for s in parsed.segments]
    assert sections[:2] == ["Scheduling", "Deadlocks"]
    assert "time slice" in parsed.segments[0].text
    assert any("Algorithm | Preemptive" in s.text for s in parsed.segments)


def test_pptx_slides_become_pages_with_titles():
    from pptx import Presentation

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Memory management"
    slide.placeholders[1].text = "Paging splits memory into fixed-size frames."
    buffer = io.BytesIO()
    presentation.save(buffer)

    parsed = parse_document("pptx", buffer.getvalue())
    assert len(parsed.segments) == 1
    assert parsed.segments[0].page == 1
    assert parsed.segments[0].section == "Memory management"
    assert "fixed-size frames" in parsed.segments[0].text


def test_markdown_is_split_at_headings():
    parsed = parse_document("md", b"Intro text here.\n\n# One\nfirst body\n\n## Two\nsecond body\n")
    assert [(s.section, s.text) for s in parsed.segments] == [
        (None, "Intro text here."),
        ("One", "first body"),
        ("Two", "second body"),
    ]


def test_text_encodings():
    assert parse_document("txt", "नमस्ते दुनिया".encode()).segments[0].text == "नमस्ते दुनिया"
    assert parse_document("txt", "﻿hello".encode()).segments[0].text == "hello"
    assert parse_document("txt", "café".encode("cp1252")).segments[0].text == "café"
    assert parse_document("txt", b"   \n  ").segments == []


def test_images_are_marked_for_ocr_and_unknown_types_are_refused():
    assert parse_document("png", b"\x89PNG....").ocr_image
    with pytest.raises(IngestError):
        parse_document("exe", b"MZ")
