"""Splitting extracted text into passages that fit the embedding model."""

import re
from dataclasses import dataclass

from mindnest_worker.language import Language, detect_language

# Sentence ends in English (. ! ?) and Hindi/Gujarati (danda । and double danda ॥).
_SENTENCE_END = re.compile(r"(?<=[.!?।॥])\s+")
_PARAGRAPH = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class Segment:
    """A piece of a document with its location, before it is split into chunks."""

    text: str
    page: int | None = None
    section: str | None = None


@dataclass(frozen=True)
class Chunk:
    text: str
    page: int | None
    section: str | None
    language: Language


def _hard_split(text: str, max_chars: int) -> list[str]:
    """Last resort for text with no sentence ends: cut at spaces, or mid-word if there are none."""
    pieces: list[str] = []
    while len(text) > max_chars:
        cut = text.rfind(" ", 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        pieces.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        pieces.append(text)
    return pieces


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(paragraph):
        if len(sentence) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_hard_split(sentence, max_chars))
        elif not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current += " " + sentence
        else:
            pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)
    return pieces


def _overlap_tail(text: str, overlap: int) -> str:
    """The end of the previous chunk, started at a word boundary, repeated at the start of the
    next chunk so a sentence cut by a chunk edge is still found by search."""
    if overlap <= 0 or len(text) <= overlap:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if space != -1 else ""


def split_text(text: str, max_chars: int = 800, overlap: int = 120) -> list[str]:
    """Split text into chunks of at most max_chars, preferring paragraph and sentence edges."""
    # Pieces cut from a long paragraph are made smaller than max_chars so the overlap carried
    # from the previous chunk still fits in front of them.
    piece_limit = max(max_chars - max(overlap, 0), max_chars // 2)
    pieces: list[str] = []
    for paragraph in _PARAGRAPH.split(text):
        # PDFs break lines in the middle of sentences, so fold single newlines into spaces.
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
        else:
            pieces.extend(_split_long(paragraph, piece_limit))

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + 1 + len(piece) <= max_chars:
            current += "\n" + piece
        else:
            chunks.append(current)
            tail = _overlap_tail(current, overlap)
            current = f"{tail}\n{piece}" if tail and len(tail) + 1 + len(piece) <= max_chars else piece
    if current:
        chunks.append(current)
    return chunks


def chunk_segments(segments: list[Segment], max_chars: int, overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for segment in segments:
        for text in split_text(segment.text, max_chars, overlap):
            # Skip fragments with no letters or digits (page numbers, rules, stray symbols).
            if sum(ch.isalnum() for ch in text) < 4:
                continue
            chunks.append(Chunk(text, segment.page, segment.section, detect_language(text)))
    return chunks
