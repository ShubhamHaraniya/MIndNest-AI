"""The Hindi and Gujarati catalogs must stay in step with the English source of truth."""

import json
import re
from pathlib import Path

import pytest

MESSAGES = Path(__file__).resolve().parents[3] / "apps/web/src/i18n/messages"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _load(code: str) -> dict[str, str]:
    return json.loads((MESSAGES / f"{code}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("code", ["hi", "gu"])
def test_catalog_has_exactly_the_english_keys(code: str) -> None:
    english, other = _load("en"), _load(code)
    assert sorted(set(english) - set(other)) == [], f"{code} is missing keys"
    assert sorted(set(other) - set(english)) == [], f"{code} has keys English does not"


@pytest.mark.parametrize("code", ["hi", "gu"])
def test_placeholders_match_english(code: str) -> None:
    english, other = _load("en"), _load(code)
    for key, text in english.items():
        assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(other[key])), key


@pytest.mark.parametrize("code", ["en", "hi", "gu"])
def test_no_empty_messages(code: str) -> None:
    assert all(value.strip() for value in _load(code).values())
