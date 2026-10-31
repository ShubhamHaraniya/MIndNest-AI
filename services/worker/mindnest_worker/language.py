"""Script-based language detection for the three supported languages."""

from typing import Literal

Language = Literal["en", "hi", "gu"]


def detect_language(text: str) -> Language:
    """Guess English, Hindi or Gujarati from the writing system.

    Devanagari letters mean Hindi and Gujarati letters mean Gujarati (Marathi and Sanskrit
    also use Devanagari and will read as Hindi, which is acceptable for retrieval). A script
    needs about a third of all letters to win, so English text with a Hindi word stays English.
    """
    devanagari = gujarati = latin = 0
    for ch in text:
        code = ord(ch)
        if 0x0900 <= code <= 0x097F:
            devanagari += 1
        elif 0x0A80 <= code <= 0x0AFF:
            gujarati += 1
        elif ch.isascii() and ch.isalpha():
            latin += 1
    total = devanagari + gujarati + latin
    if total == 0:
        return "en"
    if gujarati >= devanagari and gujarati / total >= 0.3:
        return "gu"
    if devanagari > gujarati and devanagari / total >= 0.3:
        return "hi"
    return "en"
