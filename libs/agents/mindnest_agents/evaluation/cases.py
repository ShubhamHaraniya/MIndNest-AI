"""Test cases for the agents: one JSON object per line.

    {"id": "route-quiz-1", "category": "routing", "message": "Make me a quiz on cells",
     "expect": {"agents": ["quiz"], "tools": ["create_quiz"], "cards": ["quiz"]}}

Everything under `expect` is optional; a case checks only what it lists.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KNOWN_EXPECT = {
    "agents", "tools", "forbid_tools", "cards", "answer_any", "answer_all", "answer_none", "guard",
    "guard_offline", "awaiting_approval", "grounded", "cites", "on_topic", "max_ms", "error",
}


@dataclass
class Case:
    id: str
    category: str
    message: str
    subject: bool = True  # search inside the evaluation subject (False: all of the student's subjects)
    requires: list[str] = field(default_factory=list)  # "google": needs a connected Google Calendar
    writes: bool = False  # changes the student's data (planner); skipped unless writes are allowed
    offline: bool = False  # can be checked by the guardrails alone, with no model and no server
    expect: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Case":
        unknown = set(raw.get("expect", {})) - KNOWN_EXPECT
        if unknown:
            raise ValueError(f"case {raw.get('id')}: unknown expectation(s) {sorted(unknown)}")
        for key in ("id", "category", "message"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise ValueError(f"case {raw.get('id', '?')}: '{key}' is required")
        return cls(
            id=raw["id"], category=raw["category"], message=raw["message"],
            subject=bool(raw.get("subject", True)), requires=list(raw.get("requires", [])),
            writes=bool(raw.get("writes", False)), offline=bool(raw.get("offline", False)),
            expect=dict(raw.get("expect", {})),
        )


def load_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            case = Case.from_dict(json.loads(line))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path.name} line {number}: {exc}") from exc
        if case.id in seen:
            raise ValueError(f"{path.name} line {number}: duplicate id {case.id}")
        seen.add(case.id)
        cases.append(case)
    return cases
