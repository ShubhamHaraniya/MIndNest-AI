"""The fast rules. Plain functions, no model, no network: they run on every message.

Each function answers with a `Check`. A check is one of:

- "allow":   nothing found (or nothing worth acting on).
- "block":   stop here; `code` says why.
- "modify":  carry on, but with `text` instead of what came in (instructions quoted, links cut).
- "review":  looks risky but may be innocent (a student studying prompt injection, a sociology
             question about suicide). The engine asks the student's own model to decide; if no
             model is available `fallback` says what to do ("allow" or "block").

Nothing here keeps the text it looked at. Reasons are short fixed labels, so they can be stored
and traced without leaking what the student wrote.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from mindnest_core.aisafety import (
    SafeOutput,
    defang,
    mask_pii,
    sanitize_output,
    scan_injection,
    strip_invisible,
)

Action = Literal["allow", "block", "modify", "review"]

# Codes the app understands (the refusal text for each lives in messages.py).
INJECTION = "injection"
SELF_HARM = "self_harm"
HARMFUL = "harmful"
TOOL_BLOCKED = "tool_blocked"
OUTPUT_LEAK = "output_leak"

MAX_TOOL_ARG_CHARS = 4000
MAX_TOOL_RESULT_CHARS = 60000


@dataclass
class Check:
    action: Action = "allow"
    code: str = ""
    category: str = ""  # what kind of risk was seen, even when the final action is "allow"
    reasons: list[str] = field(default_factory=list)
    text: str | None = None  # the replacement text for "modify"
    counts: dict[str, int] = field(default_factory=dict)  # "pii:email": 1, "injection": 2, "hidden": 3
    fallback: Literal["allow", "block"] = "allow"  # for "review" when the judge cannot answer

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action, "code": self.code, "category": self.category,
            "reasons": list(self.reasons), "text": self.text, "fallback": self.fallback,
            "counts": dict(self.counts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Check":
        return cls(
            action=data.get("action", "allow"), code=data.get("code", ""),
            category=data.get("category", ""), reasons=list(data.get("reasons", [])),
            text=data.get("text"), fallback=data.get("fallback", "allow"),
            counts=dict(data.get("counts") or {}),
        )


# --------------------------------------------------------------------------- the student's message

_I = re.IGNORECASE
_SPACES = re.compile(r"\s+")


def _fold(text: str) -> str:
    """Lower-case, compatibility-folded, single-spaced text for matching."""
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", text)).strip().casefold()


# A person saying they want to die or hurt themselves. First-person and specific on purpose: the
# bare word "suicide" is a topic (sociology, psychology), not a statement.
_CRISIS_STRONG = [
    re.compile(
        r"\b(?:i(?:'m| am)? (?:want|wanna|going|plan(?:ning)?|thinking|ready|about)(?: to| of| about)? "
        r"(?:kill myself|end my life|end it all|take my (?:own )?life|commit suicide|die|hurt myself|harm myself))\b", _I),
    re.compile(r"\b(?:i )?(?:don'?t|do not) want to (?:live|be alive|exist|wake up)(?: anymore| any more)?\b", _I),
    re.compile(r"\b(?:i )?(?:will|am going to|gonna|might) (?:kill myself|end my life|commit suicide)\b", _I),
    re.compile(r"\b(?:thinking|thoughts) (?:about|of) (?:suicide|killing myself|ending my life|self[- ]harm)\b", _I),
    re.compile(r"\bi (?:want|wish) (?:i were|i was|to be) dead\b", _I),
    # Hindi
    re.compile(r"(?:मैं|मुझे|मै)\s*(?:अब\s*)?(?:जीना\s+नहीं\s+चाहता|जीना\s+नहीं\s+चाहती|मरना\s+चाहता|मरना\s+चाहती|"
               r"आत्महत्या\s+करना\s+चाहता|आत्महत्या\s+करना\s+चाहती|खुद\s+को\s+खत्म)"),
    re.compile(r"(?:जान\s+दे\s+दूँ|जान\s+दे\s+दूं|खुदकुशी\s+कर\s+लू|आत्महत्या\s+कर\s+लू)"),
    # Gujarati
    re.compile(r"(?:મારે|મને)\s*(?:હવે\s*)?(?:જીવવું\s+નથી|મરી\s+જવું\s+છે|મરવું\s+છે|આત્મહત્યા\s+કરવી\s+છે)"),
    re.compile(r"(?:જીવન\s+ટૂંકાવી|જાન\s+આપી\s+દઉં|આત્મહત્યા\s+કરી\s+લઉં)"),
]

# The topic words alone: worth a second look, not an alarm.
_CRISIS_TOPIC = re.compile(
    r"\b(?:suicid\w*|self[- ]?harm|kill(?:ing)? myself|end(?:ing)? my life)\b|आत्महत्या|खुदकुशी|આત્મહત્યા", _I
)

# Asking for how to build a weapon or a drug, or to write malware.
_HARMFUL_STRONG = [
    re.compile(
        r"\b(?:how (?:to|do i|can i|do you)|steps? to|instructions? (?:for|to)|teach me (?:to|how to)|help me)\b[^.\n]{0,25}"
        r"\b(?:make|build|create|assemble|synthesi[sz]e|cook|produce)\b[^.\n]{0,25}"
        r"\b(?:bomb|explosive|pipe bomb|molotov|nerve agent|sarin|ricin|anthrax|meth(?:amphetamine)?|fentanyl|"
        r"homemade gun|untraceable gun|ghost gun)\b", _I),
]
_HARMFUL_REVIEW = re.compile(
    r"\b(?:write|create|build|code|make|give me)\b[^.\n]{0,30}\b(?:ransomware|keylogger|botnet|"
    r"credential stealer|computer virus|malware|phishing (?:page|kit|site)|ddos (?:tool|script))\b"
    r"|\b(?:hack(?:ing)? into|break into|crack)\b[^.\n]{0,25}\b(?:account|wifi|wi-fi|password|phone|someone)\b", _I
)


def check_input(text: str) -> Check:
    """The student's own message, already cleaned and masked by the app."""
    folded = _fold(text)
    cleaned, hidden = strip_invisible(text)
    reasons: list[str] = []
    if hidden:
        reasons.append("hidden_characters")

    # 1. A person in distress comes first: that is never treated as an attack.
    if any(p.search(folded) or p.search(cleaned) for p in _CRISIS_STRONG):
        return Check("review", SELF_HARM, "self_harm", [*reasons, "crisis_phrase"], fallback="block")
    # 2. Plain requests for weapons or drugs are refused outright.
    if any(p.search(folded) for p in _HARMFUL_STRONG):
        return Check("block", HARMFUL, "harmful", [*reasons, "weapon_or_drug_instructions"])

    findings = scan_injection(cleaned)
    kinds = sorted({f.kind for f in findings})
    category = ""
    if findings:
        category = "injection"
        reasons.append("injection:" + "+".join(kinds))
    if _CRISIS_TOPIC.search(folded):
        category = category or "self_harm"
        reasons.append("crisis_topic")
    if _HARMFUL_REVIEW.search(folded):
        category = category or "harmful"
        reasons.append("harmful_topic")

    if not findings and "crisis_topic" not in reasons and "harmful_topic" not in reasons:
        return Check("allow", "", "", reasons)

    # Something to look at. Instruction-like text that tries to take over (ignore the rules, you
    # are now ..., reveal your prompt) is the one risky pattern. A single weak signal is only noted.
    strong = bool({"override", "role", "reveal", "template"} & set(kinds)) or len(kinds) >= 2
    if category == "injection" and not strong:
        return Check("allow", "", "injection", reasons)
    code = {"injection": INJECTION, "self_harm": SELF_HARM, "harmful": HARMFUL}[category]
    return Check("review", code, category, reasons, fallback="allow")


# --------------------------------------------------------------------------- tool calls and results

_WRITE_PREFIXES = ("add_", "update_", "move_", "remove_", "delete_", "create_", "start_", "generate_", "set_")
_URL = re.compile(r"https?://[^\s)\]>\"'<]+", _I)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*https?://", _I)


def is_write_tool(name: str) -> bool:
    return name.startswith(_WRITE_PREFIXES)


def _strings(value: Any) -> list[str]:
    """Every string inside tool arguments, however deeply nested."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def check_tool_call(name: str, args: Any, user_text: str, allowed: set[str] | None = None) -> Check:
    """A tool call the model asked for. The student never typed these arguments, so they are held
    to a stricter standard than the student's own words:

    - the tool must exist for this agent;
    - the arguments must be a sensible size;
    - a change (add, move, remove ...) may not carry a link or instruction-like text that is not in
      the student's own message. That is what an attack hidden in a document looks like.
    """
    reasons: list[str] = []
    if allowed is not None and name not in allowed:
        return Check("block", TOOL_BLOCKED, "tool", ["unknown_tool"])
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
        return Check("block", TOOL_BLOCKED, "tool", ["bad_tool_name"])
    try:
        size = len(json.dumps(args, default=str, ensure_ascii=False))
    except (TypeError, ValueError):
        return Check("block", TOOL_BLOCKED, "tool", ["unreadable_arguments"])
    if size > MAX_TOOL_ARG_CHARS:
        return Check("block", TOOL_BLOCKED, "tool", ["arguments_too_large"])

    strings = _strings(args)
    own = _fold(user_text)
    if is_write_tool(name):
        for s in strings:
            for url in _URL.findall(s):
                if _fold(url) not in own:
                    reasons.append("link_not_from_student")
            if _MD_IMAGE.search(s):
                reasons.append("image_link")
            injected = [f for f in scan_injection(s) if f.kind in ("override", "role", "reveal", "template", "exfil")]
            if injected and not any(_fold(s[f.start : f.end]) in own for f in injected if f.end > f.start):
                reasons.append("instructions_not_from_student")
    if reasons:
        return Check("block", TOOL_BLOCKED, "tool", sorted(set(reasons)))
    return Check("allow")


def check_tool_result(text: str, *, mask_optional: bool = True) -> Check:
    """What a tool returned: notes, titles from a calendar, text from a PDF. All of it is data
    written by someone else, so instruction-like phrases are quoted (they stay readable but cannot
    pass for orders), hidden characters go, and personal data is masked. Running it twice on the
    same text changes nothing the second time."""
    reasons: list[str] = []
    counts: dict[str, int] = {}
    cleaned, hidden = strip_invisible(text)
    if hidden:
        reasons.append("hidden_characters")
        counts["hidden"] = hidden
    quoted, findings = defang(cleaned)
    if findings:
        reasons.append("injection:" + "+".join(sorted({f.kind for f in findings})))
        counts["injection"] = len(findings)
    masked = mask_pii(quoted, include_optional=mask_optional)
    if masked.changed:
        reasons.append("pii")
        for kind, n in masked.counts.items():
            counts[f"pii:{kind}"] = n
    if len(masked.text) > MAX_TOOL_RESULT_CHARS:
        reasons.append("truncated")
        masked.text = masked.text[:MAX_TOOL_RESULT_CHARS]
    if not reasons:
        return Check("allow")
    return Check("modify", "", "injection" if findings else "data", reasons, text=masked.text, counts=counts)


# --------------------------------------------------------------------------- the answer

def check_output(text: str, canary: str | None, mask_optional: bool = False) -> tuple[Check, SafeOutput]:
    """The finished answer. Reuses sanitize_output: a leaked marker blocks the answer; links that
    could smuggle data out, images, active HTML and personal data are cleaned."""
    safe = sanitize_output(text, canary=canary, mask_optional=mask_optional)
    if safe.leaked:
        return Check("block", OUTPUT_LEAK, "leak", ["canary"]), safe
    if safe.changes:
        return Check("modify", "", "output", list(safe.changes), text=safe.text), safe
    return Check("allow"), safe
