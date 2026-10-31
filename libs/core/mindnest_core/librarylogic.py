"""Rules for the Materials Library: what a visibility choice means. Pure functions, no database."""

DOC_TYPES = ("notes", "past_paper", "textbook", "slides", "reference", "other")
VISIBILITIES = ("private", "institution", "public")
SCOPES = ("college", "others", "global", "mine")
REPORT_REASONS = ("copyright", "inappropriate", "wrong_content", "other")

# How many items one student may keep in the library.
MAX_ITEMS_PER_USER = 200
# Different students who report a published item before it is held back for a moderator.
HOLD_AT_REPORTS = 3

# A library item becomes an ordinary course material of this kind when a student adds it.
_MATERIAL_KIND = {"past_paper": "past_paper", "notes": "note"}


def status_for_owner_change(visibility: str) -> str:
    """The status an item gets whenever its owner saves it with this visibility.

    Private stays a draft nobody else can see. Institution-only is published at once, because it
    only reaches students who typed the same institution (it can still be reported and taken down).
    Public goes through review first, and every later edit of a public item is reviewed again.
    """
    if visibility == "private":
        return "draft"
    if visibility == "institution":
        return "published"
    return "pending_review"


def material_kind(doc_type: str) -> str:
    return _MATERIAL_KIND.get(doc_type, "material")


def is_wider(old: str, new: str) -> bool:
    """True when the new visibility lets more people see the file (so rights must be confirmed)."""
    order = {"private": 0, "institution": 1, "public": 2}
    return order[new] > order[old]
