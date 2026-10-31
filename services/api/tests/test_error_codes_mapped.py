"""Every error code the API can raise has a translated message in the web app.

The web app never shows server wording (it is English only), so a code missing from the KNOWN
map in apps/web/src/lib/errors.ts would show students the generic "something went wrong".
"""

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "services/api/mindnest_api"
ERRORS_TS = ROOT / "apps/web/src/lib/errors.ts"
MESSAGES = ROOT / "apps/web/src/i18n/messages"

# Codes that are deliberately shown with the generic message. Keep this empty unless there is a
# reason written next to the entry.
GENERIC_ON_PURPOSE: set[str] = set()


def raised_codes() -> dict[str, str]:
    """Every literal error code passed to AppError(status, code, message), with where it is."""
    found: dict[str, str] = {}
    for path in sorted(API.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "AppError"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
            ):
                found.setdefault(node.args[1].value, f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def known_map() -> dict[str, str]:
    source = ERRORS_TS.read_text(encoding="utf-8")
    block = source.split("const KNOWN", 1)[1].split("};", 1)[0]
    return dict(re.findall(r'^\s*"?(\w+)"?:\s*"(errors\.\w+)"', block, flags=re.M))


def test_every_raised_code_is_mapped_to_a_message() -> None:
    known = known_map()
    assert len(known) > 50, "could not read the KNOWN map"
    missing = {
        code: where
        for code, where in raised_codes().items()
        if code not in known and code not in GENERIC_ON_PURPOSE
    }
    assert not missing, f"add these to KNOWN in apps/web/src/lib/errors.ts and the catalogs: {missing}"


def test_every_mapped_message_exists_in_all_languages() -> None:
    for locale in ("en", "hi", "gu"):
        catalog = json.loads((MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))
        absent = sorted(key for key in known_map().values() if not str(catalog.get(key, "")).strip())
        assert not absent, f"{locale}.json is missing {absent}"
