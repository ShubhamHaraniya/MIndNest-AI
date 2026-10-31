#!/usr/bin/env python3
"""Writes docs/student-guide.<lang>.md from the guide shown in the app.

The text lives in apps/web/src/content/guide/<lang>.json (one source of truth, so the in-app Help
page and the printable copy cannot drift apart). Run this after editing those files:

    python scripts/build_guide_docs.py          write the files
    python scripts/build_guide_docs.py --check  exit 1 if they are out of date (used by a test)
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apps/web/src/content/guide"
TARGET = ROOT / "docs"
LANGUAGES = ("en", "hi", "gu")


def render(guide: dict) -> str:
    lines = [f"# {guide['title']}", "", guide["intro"], "", f"**{guide['contents']}**", ""]
    for section in guide["sections"]:
        lines.append(f"- [{section['title']}](#{section['id']})")
    lines.append("")
    for section in guide["sections"]:
        lines += [f'<a id="{section["id"]}"></a>', "", f"## {section['title']}", ""]
        for paragraph in section["body"]:
            lines += [paragraph, ""]
        if section.get("steps"):
            lines += [f"**{guide['stepsLabel']}**", ""]
            lines += [f"{number}. {step}" for number, step in enumerate(section["steps"], 1)]
            lines.append("")
        if section.get("tip"):
            lines += [f"> **{guide['tipLabel']}:** {section['tip']}", ""]
    return "\n".join(lines).rstrip() + "\n"


def generated() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for code in LANGUAGES:
        guide = json.loads((SOURCE / f"{code}.json").read_text(encoding="utf-8"))
        out[TARGET / f"student-guide.{code}.md"] = render(guide)
    return out


def main(argv: list[str]) -> int:
    files = generated()
    if "--check" in argv:
        stale = [p.name for p, text in files.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        if stale:
            print("Out of date: " + ", ".join(stale) + ". Run: python scripts/build_guide_docs.py")
            return 1
        return 0
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
