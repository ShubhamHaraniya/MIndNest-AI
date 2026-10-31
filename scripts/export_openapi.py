"""Export or verify the OpenAPI document that the web client types are generated from.

    python scripts/export_openapi.py          write packages/contracts/openapi.json
    python scripts/export_openapi.py --check  exit 1 if the committed file is missing or stale
"""

import argparse
import json
import sys
from pathlib import Path

from mindnest_api.main import create_app

TARGET = Path(__file__).resolve().parents[1] / "packages" / "contracts" / "openapi.json"


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args()

    text = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            print(
                "packages/contracts/openapi.json is missing or out of date. "
                "Run `python scripts/export_openapi.py` and commit the result.",
                file=sys.stderr,
            )
            return 1
        return 0

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
