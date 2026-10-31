"""The student guide exists in all three languages with the same shape, and the printable
copies in docs/ match what the app shows."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GUIDE = ROOT / "apps/web/src/content/guide"
REQUIRED = {"title", "intro", "contents", "stepsLabel", "tipLabel", "topLabel", "sections"}


def load(code: str) -> dict:  # type: ignore[type-arg]
    return json.loads((GUIDE / f"{code}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("code", ["en", "hi", "gu"])
def test_guide_is_complete_and_has_no_blank_text(code: str) -> None:
    guide = load(code)
    assert REQUIRED <= set(guide)
    assert all(guide[key].strip() for key in REQUIRED - {"sections"})
    for section in guide["sections"]:
        assert section["title"].strip() and section["body"]
        texts = [*section["body"], *section.get("steps", []), section.get("tip", "x")]
        assert all(isinstance(text, str) and text.strip() for text in texts), section["id"]


@pytest.mark.parametrize("code", ["hi", "gu"])
def test_translations_follow_the_english_structure(code: str) -> None:
    english, other = load("en"), load(code)
    assert [s["id"] for s in other["sections"]] == [s["id"] for s in english["sections"]]
    for a, b in zip(english["sections"], other["sections"], strict=True):
        assert len(a["body"]) == len(b["body"]), a["id"]
        assert len(a.get("steps", [])) == len(b.get("steps", [])), a["id"]
        assert ("tip" in a) == ("tip" in b), a["id"]


def test_section_ids_are_unique_link_targets() -> None:
    ids = [s["id"] for s in load("en")["sections"]]
    assert len(ids) == len(set(ids)) and all(i.isalnum() for i in ids)


def test_printable_copies_are_up_to_date() -> None:
    spec = importlib.util.spec_from_file_location("build_guide_docs", ROOT / "scripts/build_guide_docs.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--check"]) == 0
