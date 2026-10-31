"""Rules for the chat that need no database: what may be attached to a conversation, how a
conversation's search scope is read, the checks on diagram blocks, citation integrity, the
suggested follow-up questions and clarifying choices an answer may end with, and message feedback.

Everything here is a plain function so it can be tested without a server."""

import io
import json
import re
import unicodedata
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from mindnest_core.filetypes import looks_like


class ChatRuleError(ValueError):
    """A rule was broken. `code` is a short stable string the web app can show in the student's language."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ----------------------------------------------------------------------------------- attachments

# What can be attached to a conversation. The worker reads PDF and Word files directly and
# runs OCR on pictures (and on scanned PDF pages), so a picture is only useful when it contains
# readable text: nothing here "looks at" photographs or drawings.
ATTACHMENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_ATTACHMENTS_PER_CONVERSATION = 5
ATTACHMENT_STATUSES = ("uploaded", "processing", "ready", "failed")
MAX_ATTACHMENT_TEXT = 60_000  # characters kept from one file
MAX_ATTACHMENT_CONTEXT = 24_000  # characters of all attached files together that one answer may read

_ATTACHMENT_TAG = re.compile(r"<(/?)\s*attachment", re.IGNORECASE)


def attachment_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def attachment_kind(extension: str) -> str | None:
    """"pdf", "docx" or "image"; None when the type cannot be attached."""
    if extension not in ATTACHMENT_TYPES:
        return None
    return "image" if extension in {"png", "jpg", "jpeg"} else extension


@dataclass(frozen=True)
class AttachmentCheck:
    ok: bool
    code: str | None
    extension: str
    kind: str | None


def check_attachment(
    filename: str,
    head: bytes,
    size: int,
    *,
    existing: int = 0,
    max_bytes: int = MAX_ATTACHMENT_BYTES,
    max_files: int = MAX_ATTACHMENTS_PER_CONVERSATION,
) -> AttachmentCheck:
    """Decide whether a file may be attached. The extension names the type (never the type the
    browser claims) and the first bytes must agree with it, so a renamed program is refused.

    Codes: too_many_attachments, unsupported_type, empty_file, file_too_large, type_mismatch."""
    extension = attachment_extension(filename)
    kind = attachment_kind(extension)

    def fail(code: str) -> AttachmentCheck:
        return AttachmentCheck(False, code, extension, kind)

    if existing >= max_files:
        return fail("too_many_attachments")
    if kind is None:
        return fail("unsupported_type")
    if size <= 0:
        return fail("empty_file")
    if size > max_bytes:
        return fail("file_too_large")
    if not looks_like(extension, head):
        return fail("type_mismatch")
    return AttachmentCheck(True, None, extension, kind)


def attachment_context(
    files: Sequence[tuple[str, str]], limit: int = MAX_ATTACHMENT_CONTEXT
) -> tuple[str, list[str]]:
    """The attached files as one block of text for the AI. Each file gets an equal share of `limit`
    characters; `files` is (file name, its text). Returns the block and the names of the files that
    were cut short. A file cannot close its own tag or open a fake one."""
    usable = [(name, body) for name, body in files if body.strip()]
    if not usable:
        return "", []
    share = max(1, limit // len(usable))
    parts: list[str] = []
    cut: list[str] = []
    for name, body in usable:
        shown = body[:share]
        if len(body) > share:
            cut.append(name)
        safe_name = name.replace('"', "'").replace("<", "").replace(">", "")
        safe_body = _ATTACHMENT_TAG.sub(lambda m: f"&lt;{m.group(1)}attachment", shown)
        flag = ' truncated="yes"' if len(body) > share else ""
        parts.append(f'<attachment file="{safe_name}"{flag}>\n{safe_body}\n</attachment>')
    return "\n".join(parts), cut


def is_word_document(data: bytes) -> bool:
    """A .docx is a zip file; a PowerPoint or Excel file renamed to .docx is also a zip, so look
    for the part that only a Word document has."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except (zipfile.BadZipFile, ValueError, OSError):
        return False


# ---------------------------------------------------------------------------------------- scope

SCOPES = ("all", "subject", "materials")
MAX_SCOPE_MATERIALS = 50


@dataclass(frozen=True)
class Scope:
    """What a conversation may search: every course of the student, one course, or chosen files."""

    kind: str = "all"
    subject_id: UUID | None = None
    material_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class SearchFilter:
    subject_id: UUID | None
    material_ids: tuple[UUID, ...] | None
    # True when nothing may be searched at all (the course or all chosen files are gone).
    nothing: bool


def resolve_scope(
    scope: str | None,
    subject_id: UUID | None,
    material_ids: Iterable[UUID] | None,
    *,
    current: Scope | None = None,
) -> Scope:
    """The scope a request asks for. Without an explicit `scope`, the fields given decide: files
    mean "materials", a subject means "subject", nothing means keep the current scope (or "all").

    Codes: invalid_scope, scope_needs_subject, scope_needs_materials, too_many_materials."""
    ids = tuple(dict.fromkeys(material_ids or ()))
    if scope is None:
        if ids:
            scope = "materials"
        elif subject_id is not None:
            scope = "subject"
        else:
            return current or Scope()
    if scope not in SCOPES:
        raise ChatRuleError("invalid_scope")
    if scope == "all":
        return Scope("all")
    if scope == "subject":
        if subject_id is None:
            raise ChatRuleError("scope_needs_subject")
        return Scope("subject", subject_id)
    if not ids:
        raise ChatRuleError("scope_needs_materials")
    if len(ids) > MAX_SCOPE_MATERIALS:
        raise ChatRuleError("too_many_materials")
    return Scope("materials", None, ids)


def scope_from_row(scope: str | None, subject_id: UUID | None, material_ids: Iterable[UUID] | None) -> Scope:
    """The scope stored on a conversation. Unknown values fall back to the narrowest reading."""
    ids = tuple(material_ids or ())
    if scope == "materials":
        return Scope("materials", None, ids)
    if scope == "subject":
        return Scope("subject", subject_id)
    return Scope("all")


def search_filter(scope: Scope) -> SearchFilter:
    """What retrieval must be limited to. A course-scoped conversation whose course was deleted
    searches nothing (it must not quietly widen to every other course)."""
    if scope.kind == "subject":
        return SearchFilter(scope.subject_id, None, scope.subject_id is None)
    if scope.kind == "materials":
        return SearchFilter(None, scope.material_ids, not scope.material_ids)
    return SearchFilter(None, None, False)


# ------------------------------------------------------------------------------------- diagrams

DIAGRAM_FENCE = "mindnest-diagram"
DIAGRAM_TYPES = ("binary_tree", "linked_list", "graph", "array")
MAX_DIAGRAM_CHARS = 8000
MAX_TITLE = 80
MAX_LABEL = 16
MAX_NOTE = 160
MAX_STEPS = 60
MAX_TREE_NODES = 31
MAX_TREE_DEPTH = 5  # levels below the root
MAX_LIST_NODES = 12
MAX_GRAPH_NODES = 14
MAX_GRAPH_EDGES = 30
MAX_ARRAY_LEN = 14
MAX_POINTERS = 4

# Something that reads as an HTML tag or comment. A lone "<" ("while i<n") is ordinary text.
_HTML_LIKE = re.compile(r"<\s*/?[A-Za-z!?][^<>]*>")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ID = re.compile(r"^[A-Za-z0-9_\-]{1,12}$")


@dataclass(frozen=True)
class DiagramResult:
    ok: bool
    spec: dict[str, Any] | None = None
    error: str | None = None


class _Bad(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _label(value: Any, limit: int, *, required: bool = True) -> str:
    """Text shown inside the picture. Numbers are allowed; markup is not. Long text is shortened."""
    if isinstance(value, bool) or value is None or not isinstance(value, (str, int, float)):
        if required:
            raise _Bad("bad_label")
        return ""
    text = _CONTROL.sub("", unicodedata.normalize("NFC", str(value))).strip()
    if _HTML_LIKE.search(text):
        raise _Bad("html_not_allowed")
    if not text and required:
        raise _Bad("bad_label")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _index_list(value: Any, length: int) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > length:
        raise _Bad("bad_index")
    out: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item < length:
            raise _Bad("bad_index")
        if item not in out:
            out.append(item)
    return out


def _steps_of(raw: Mapping[str, Any]) -> list[Any]:
    steps = raw.get("steps")
    if steps is None:
        return []
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise _Bad("too_many_steps")
    for step in steps:
        if not isinstance(step, dict):
            raise _Bad("bad_step")
    return steps


def _title_of(raw: Mapping[str, Any]) -> str:
    return _label(raw.get("title"), MAX_TITLE, required=False)


def _tree_node(raw: Any, depth: int, counter: list[int]) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _Bad("bad_tree")
    if depth > MAX_TREE_DEPTH:
        raise _Bad("tree_too_deep")
    counter[0] += 1
    if counter[0] > MAX_TREE_NODES:
        raise _Bad("too_many_nodes")
    value = raw.get("value", raw.get("label"))
    return {
        "value": _label(value, MAX_LABEL),
        "left": _tree_node(raw.get("left"), depth + 1, counter),
        "right": _tree_node(raw.get("right"), depth + 1, counter),
    }


def _tree_values(node: dict[str, Any] | None, out: list[str]) -> None:
    if node is None:
        return
    out.append(node["value"])
    _tree_values(node["left"], out)
    _tree_values(node["right"], out)


def _binary_tree(raw: Mapping[str, Any]) -> dict[str, Any]:
    root = _tree_node(raw.get("root"), 0, [0])
    if root is None:
        raise _Bad("empty_diagram")
    values: list[str] = []
    _tree_values(root, values)
    known = set(values)
    steps = []
    for step in _steps_of(raw):
        marked = step.get("highlight") or []
        if not isinstance(marked, list) or len(marked) > MAX_TREE_NODES:
            raise _Bad("bad_step")
        highlight = [_label(v, MAX_LABEL) for v in marked]
        if any(v not in known for v in highlight):
            raise _Bad("unknown_node")
        steps.append({"highlight": highlight, "note": _label(step.get("note"), MAX_NOTE, required=False)})
    return {"type": "binary_tree", "title": _title_of(raw), "root": root, "steps": steps}


def _linked_list(raw: Mapping[str, Any]) -> dict[str, Any]:
    nodes = raw.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise _Bad("empty_diagram")
    if len(nodes) > MAX_LIST_NODES:
        raise _Bad("too_many_nodes")
    labels = [_label(n, MAX_LABEL) for n in nodes]
    steps = []
    for step in _steps_of(raw):
        steps.append({
            "highlight": _index_list(step.get("highlight"), len(labels)),
            "note": _label(step.get("note"), MAX_NOTE, required=False),
        })
    return {
        "type": "linked_list", "title": _title_of(raw), "nodes": labels,
        "doubly": raw.get("doubly") is True, "circular": raw.get("circular") is True, "steps": steps,
    }


def _graph(raw: Mapping[str, Any]) -> dict[str, Any]:
    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise _Bad("empty_diagram")
    if len(raw_nodes) > MAX_GRAPH_NODES:
        raise _Bad("too_many_nodes")
    nodes: list[dict[str, str]] = []
    for item in raw_nodes:
        if isinstance(item, dict):
            node_id = item.get("id")
            label = item.get("label", node_id)
        else:
            node_id = label = item
        node_id = _label(node_id, 12)
        if not _ID.match(node_id):
            raise _Bad("bad_node_id")
        nodes.append({"id": node_id, "label": _label(label, MAX_LABEL)})
    ids = [n["id"] for n in nodes]
    if len(set(ids)) != len(ids):
        raise _Bad("duplicate_node")
    known = set(ids)

    raw_edges = raw.get("edges", [])
    if not isinstance(raw_edges, list) or len(raw_edges) > MAX_GRAPH_EDGES:
        raise _Bad("too_many_edges")
    edges: list[dict[str, Any]] = []
    for item in raw_edges:
        if not isinstance(item, dict):
            raise _Bad("bad_edge")
        source = _label(item.get("from"), 12)
        target = _label(item.get("to"), 12)
        if source not in known or target not in known:
            raise _Bad("unknown_node")
        weight = item.get("weight")
        edges.append({"from": source, "to": target, "weight": _label(weight, 8, required=False) or None})

    def node_list(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > MAX_GRAPH_NODES:
            raise _Bad("bad_step")
        out = [_label(v, 12) for v in value]
        if any(v not in known for v in out):
            raise _Bad("unknown_node")
        return out

    steps = []
    for step in _steps_of(raw):
        current = step.get("current")
        steps.append({
            "current": _label(current, 12) if current is not None else None,
            "visited": node_list(step.get("visited")),
            "frontier": node_list(step.get("frontier", step.get("queue", step.get("stack")))),
            "note": _label(step.get("note"), MAX_NOTE, required=False),
        })
        if steps[-1]["current"] is not None and steps[-1]["current"] not in known:
            raise _Bad("unknown_node")
    return {
        "type": "graph", "title": _title_of(raw), "directed": raw.get("directed") is True,
        "nodes": nodes, "edges": edges, "steps": steps,
    }


def _array(raw: Mapping[str, Any]) -> dict[str, Any]:
    values = raw.get("values")
    if not isinstance(values, list) or not values:
        raise _Bad("empty_diagram")
    if len(values) > MAX_ARRAY_LEN:
        raise _Bad("too_many_nodes")
    initial = [_label(v, 8) for v in values]
    steps = []
    for step in _steps_of(raw):
        state = step.get("values")
        if state is None:
            shown = list(initial)
        else:
            if not isinstance(state, list) or len(state) != len(initial):
                raise _Bad("bad_step")
            shown = [_label(v, 8) for v in state]
        pointers_raw = step.get("pointers") or {}
        if not isinstance(pointers_raw, dict) or len(pointers_raw) > MAX_POINTERS:
            raise _Bad("bad_step")
        pointers: dict[str, int] = {}
        for name, position in pointers_raw.items():
            if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position < len(initial):
                raise _Bad("bad_index")
            pointers[_label(name, 8)] = position
        steps.append({
            "values": shown,
            "highlight": _index_list(step.get("highlight"), len(initial)),
            "swapped": _index_list(step.get("swapped"), len(initial)),
            "sorted": _index_list(step.get("sorted"), len(initial)),
            "pointers": pointers,
            "note": _label(step.get("note"), MAX_NOTE, required=False),
        })
    return {"type": "array", "title": _title_of(raw), "values": initial, "steps": steps}


_BUILDERS = {"binary_tree": _binary_tree, "linked_list": _linked_list, "graph": _graph, "array": _array}


def validate_diagram(source: str | Mapping[str, Any]) -> DiagramResult:
    """Check a `mindnest-diagram` block and return a clean copy of it.

    Only the four known diagram types are accepted, only the fields this function knows are kept,
    counts and lengths are capped, and any text that looks like markup is refused. The result is
    drawn by the web app as SVG text, never as HTML. Error codes: too_large, invalid_json,
    not_an_object, unknown_type, empty_diagram, too_many_nodes, too_many_edges, too_many_steps,
    tree_too_deep, unknown_node, duplicate_node, bad_node_id, bad_label, bad_index, bad_step,
    bad_edge, bad_tree, html_not_allowed."""
    raw: Any = source
    if isinstance(source, str):
        if len(source) > MAX_DIAGRAM_CHARS:
            return DiagramResult(False, None, "too_large")
        try:
            raw = json.loads(source)
        except ValueError:
            return DiagramResult(False, None, "invalid_json")
    if not isinstance(raw, dict):
        return DiagramResult(False, None, "not_an_object")
    builder = _BUILDERS.get(str(raw.get("type")))
    if builder is None:
        return DiagramResult(False, None, "unknown_type")
    try:
        spec = builder(raw)
    except _Bad as exc:
        return DiagramResult(False, None, exc.code)
    return DiagramResult(True, spec, None)


# ------------------------------------------------------------------------------------ code spans

_CODE = re.compile(r"(```[\s\S]*?```|`[^`\n]*`)")
_FENCE_BLOCK = re.compile(r"```([\w+-]*)[ \t]*\n([\s\S]*?)\n?```")


def sanitize_diagram_blocks(text: str) -> tuple[str, int]:
    """Check every ```mindnest-diagram block in an answer. A valid block is rewritten as its clean,
    compact JSON; an invalid one is turned into a plain ```text block (so the student still sees
    what was meant and nothing tries to draw it). Returns the new text and how many were refused."""
    refused = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal refused
        if match.group(1) != DIAGRAM_FENCE:
            return match.group(0)
        result = validate_diagram(match.group(2))
        if result.ok and result.spec is not None:
            return f"```{DIAGRAM_FENCE}\n{json.dumps(result.spec, ensure_ascii=False, separators=(',', ':'))}\n```"
        refused += 1
        return f"```text\n{match.group(2)}\n```"

    return _FENCE_BLOCK.sub(replace, text), refused


# ------------------------------------------------------------------------------------- citations

_CITATION = re.compile(r"(?<![\w)])\[(\d{1,3})\](?!\()")
# Some models (the gpt-oss family, for one) write a citation as 【1】, 【1†L3-L5】 or ［1］ instead of [1].
_ALT_CITATION = re.compile(r"[【［]\s*(\d{1,3})\s*(?:†[^】］\n]{0,40})?[】］]")


def normalize_citation_marks(text: str) -> str:
    """Turn 【1】-style citation marks into [1], so the screen, the source check and the evaluation all
    see the same mark. Code is left alone."""
    parts = _CODE.split(text)
    for index in range(0, len(parts), 2):
        parts[index] = _ALT_CITATION.sub(lambda m: f"[{int(m.group(1))}]", parts[index])
    return "".join(parts)


def cited_numbers(text: str) -> list[int]:
    """The source numbers an answer cites, in order of first use (code is not looked at)."""
    found: list[int] = []
    for index, part in enumerate(_CODE.split(text)):
        if index % 2 == 1:
            continue
        for match in _CITATION.finditer(part):
            n = int(match.group(1))
            if n not in found:
                found.append(n)
    return found


def strip_unknown_citations(text: str, valid: Iterable[int]) -> tuple[str, list[int]]:
    """Remove citation marks such as [4] that do not name a passage retrieved for this answer, so an
    answer can never point at a source that was not used. Returns the text and the numbers removed."""
    allowed = set(valid)
    removed: list[int] = []
    parts = _CODE.split(text)
    for index, part in enumerate(parts):
        if index % 2 == 1:
            continue

        def drop(match: re.Match[str]) -> str:
            n = int(match.group(1))
            if n in allowed:
                return match.group(0)
            removed.append(n)
            return ""

        cleaned = _CITATION.sub(drop, part)
        if cleaned != part:
            cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
            cleaned = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", cleaned)
        parts[index] = cleaned
    return "".join(parts), removed


def citations_are_grounded(text: str, sources: Iterable[Mapping[str, Any]]) -> bool:
    """True when every number cited in the text belongs to a retrieved source."""
    valid = {int(s["n"]) for s in sources}
    return all(n in valid for n in cited_numbers(text))


# --------------------------------------------------------------- follow-up questions and choices

FOLLOWUPS_FENCE = "mindnest-followups"
CHOICES_FENCE = "mindnest-choices"
MAX_FOLLOWUPS = 3
MIN_SUGGESTION = 8
MAX_SUGGESTION = 120
MAX_OPTIONS = 5
MAX_OPTION = 80
MAX_CHOICE_QUESTION = 200

_TAIL_BLOCK = re.compile(
    r"\n*```(" + FOLLOWUPS_FENCE + "|" + CHOICES_FENCE + r")[ \t]*\n([\s\S]*?)\n?```[ \t]*"
)
_TAIL_OPEN = re.compile(r"\n*```(?:" + FOLLOWUPS_FENCE + "|" + CHOICES_FENCE + r")[ \t]*(?:\n[\s\S]*)?$")
_URL_LIKE = re.compile(r"https?://|www\.|[\w.-]+@[\w.-]+\.\w", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+")


@dataclass(frozen=True)
class Choices:
    question: str
    options: tuple[str, ...]


@dataclass
class Tail:
    text: str
    followups: list[str] = field(default_factory=list)
    choices: Choices | None = None


def _plain(value: Any, low: int, high: int) -> str | None:
    """One short line of ordinary text, or None when it is not fit to show as a button."""
    if not isinstance(value, str):
        return None
    line = _CONTROL.sub("", " ".join(value.split())).strip().strip('"')
    if not low <= len(line) <= high:
        return None
    if _HTML_LIKE.search(line) or _URL_LIKE.search(line) or "`" in line or re.search(r"\[\d{1,3}\]", line):
        return None
    return line


def _json_or_lines(body: str) -> Any:
    try:
        return json.loads(body)
    except ValueError:
        lines = [_BULLET.sub("", line).strip() for line in body.splitlines() if line.strip()]
        return lines or None


def parse_followups(body: str, *, asked: str = "") -> list[str]:
    """Up to three follow-up questions from a block's body. Anything unsuitable (too short or long,
    links, markup, a repeat of the question just asked) is dropped; unsure means none."""
    data = _json_or_lines(body)
    if isinstance(data, dict):
        data = data.get("questions", data.get("followups"))
    if not isinstance(data, list):
        return []
    seen = {" ".join(asked.casefold().split())}
    out: list[str] = []
    for item in data:
        line = _plain(item, MIN_SUGGESTION, MAX_SUGGESTION)
        if line is None:
            continue
        key = " ".join(line.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
        if len(out) == MAX_FOLLOWUPS:
            break
    return out


def parse_choices(body: str) -> Choices | None:
    """A clarifying question with 2 to 5 short options, or None if the block is not usable."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("options"), list):
        return None
    options: list[str] = []
    for item in data["options"]:
        line = _plain(item, 1, MAX_OPTION)
        if line is not None and line.casefold() not in {o.casefold() for o in options}:
            options.append(line)
    if not 2 <= len(options) <= MAX_OPTIONS:
        return None
    question = _plain(data.get("question", ""), 0, MAX_CHOICE_QUESTION) or ""
    return Choices(question, tuple(options))


def split_tail(text: str, *, asked: str = "") -> Tail:
    """Take the machine-readable blocks off the end of an answer. They are always removed from the
    visible text (also when half-written or invalid); a block is only used when it passes the checks.
    When the answer asks for a choice, no follow-up questions are offered."""
    followups: list[str] = []
    choices: Choices | None = None

    def take(match: re.Match[str]) -> str:
        nonlocal followups, choices
        if match.group(1) == FOLLOWUPS_FENCE:
            followups = parse_followups(match.group(2), asked=asked)
        else:
            choices = parse_choices(match.group(2))
        return ""

    visible = _TAIL_BLOCK.sub(take, text)
    visible = _TAIL_OPEN.sub("", visible).rstrip()
    if choices is not None:
        followups = []
    return Tail(visible, followups, choices)


def strip_partial_tail(text: str) -> str:
    """The same cut for text that is still being written, so a half-streamed block never flashes
    on screen (also when only the first few characters of the opening fence have arrived).
    The web app has an equivalent."""
    cut = _TAIL_OPEN.sub("", _TAIL_BLOCK.sub("", text))
    last = cut.rsplit("\n", 1)[-1]
    if len(last) > 3 and any(f"```{name}".startswith(last) for name in (FOLLOWUPS_FENCE, CHOICES_FENCE)):
        return cut[: len(cut) - len(last)].rstrip()
    return cut


# --------------------------------------------------------------------------------------- feedback

FEEDBACK_RATINGS = ("up", "down")
FEEDBACK_REASONS = ("incorrect", "not_in_materials", "unclear", "too_long", "unsafe", "other")
MAX_FEEDBACK_COMMENT = 500


def validate_feedback(rating: str, reason: str | None, comment: str | None) -> tuple[str, str | None, str]:
    """Check a thumbs up/down. A reason and a comment are optional and only kept for a thumbs down.

    Codes: invalid_rating, invalid_reason."""
    if rating not in FEEDBACK_RATINGS:
        raise ChatRuleError("invalid_rating")
    if rating == "up":
        return "up", None, ""
    chosen = (reason or "").strip() or None
    if chosen is not None and chosen not in FEEDBACK_REASONS:
        raise ChatRuleError("invalid_reason")
    note = _CONTROL.sub("", (comment or "")).strip()
    return "down", chosen, note[:MAX_FEEDBACK_COMMENT]


# ------------------------------------------------------------------------- regenerate and versions


@dataclass(frozen=True)
class RegeneratePlan:
    user_message_id: str
    assistant_message_id: str


def plan_regenerate(turns: list[tuple[str, str]], message_id: str) -> RegeneratePlan:
    """Which question is asked again. `turns` is the conversation as (id, role) pairs in order, without
    answers that were already replaced. Only the newest answer can be regenerated, and it needs the
    student's message right before it. Codes: not_last_answer, no_question."""
    if not turns or turns[-1][0] != message_id or turns[-1][1] != "assistant":
        raise ChatRuleError("not_last_answer")
    if len(turns) < 2 or turns[-2][1] != "user":
        raise ChatRuleError("no_question")
    return RegeneratePlan(turns[-2][0], message_id)


def previous_versions(message_id: str, replaces: Mapping[str, str | None], limit: int = 10) -> list[str]:
    """The answers a message replaced, newest first. `replaces` maps a message id to the id it
    replaced. Loops (which should never exist) end the walk."""
    out: list[str] = []
    seen = {message_id}
    current = replaces.get(message_id)
    while current is not None and current not in seen and len(out) < limit:
        out.append(current)
        seen.add(current)
        current = replaces.get(current)
    return out


# ----------------------------------------------------------------------------- history searching


def like_pattern(term: str) -> str:
    """A LIKE pattern that matches `term` as plain text (with ESCAPE '\\')."""
    escaped = term.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def excerpt(text: str, term: str, width: int = 80) -> str:
    """A short piece of `text` around the first match of `term`, for showing why a chat matched."""
    flat = " ".join(text.split())
    needle = term.strip().casefold()
    if not flat or not needle:
        return ""
    at = flat.casefold().find(needle)
    if at < 0:
        return ""
    start = max(0, at - width // 2)
    end = min(len(flat), at + len(needle) + width // 2)
    return ("…" if start > 0 else "") + flat[start:end] + ("…" if end < len(flat) else "")
