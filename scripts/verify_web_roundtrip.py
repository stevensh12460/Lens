#!/usr/bin/env python3
"""
verify_web_roundtrip.py — prove the database can reproduce the live website.

This is the safety interlock for the whole publish pipeline. Publishing works by
rewriting a fenced block of HTML from web_assets rows, so if the database cannot
reproduce the CURRENT site byte for byte, then publishing would silently rewrite
Steven's hand-written markup into something subtly different.

Run this before any publish work, and any time the site is hand-edited.

Usage:  ~/lens/venv/bin/python scripts/verify_web_roundtrip.py
Exit 0 = safe to publish.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import get_db  # noqa: E402
from services.web_publisher import (  # noqa: E402
    SECTIONS,
    extract_block,
    load_assets,
    render_block,
)


def main() -> int:
    print("Rendering each gallery from the database and diffing against the site.\n")
    failed = []

    with get_db() as conn:
        for section in SECTIONS:
            assets = load_assets(section, conn)
            if not assets:
                print(f"  EMPTY   {section:10} no rows — run seed_web_assets.py first")
                failed.append(section)
                continue

            rendered = render_block(assets)
            original = extract_block(section)

            if rendered == original:
                print(f"  MATCH   {section:10} {len(assets)} figures")
                continue

            failed.append(section)
            print(f"  DIFFER  {section:10} {len(assets)} figures")
            diff = difflib.unified_diff(
                original.split("\n"), rendered.split("\n"),
                "live-site", "from-database", lineterm="",
            )
            for line in list(diff)[:20]:
                print(f"        {line}")

    print()
    if failed:
        print(f"FAIL — {', '.join(failed)} cannot be reproduced from the database.")
        print("Do NOT publish. Either the site was hand-edited, or the data model")
        print("has lost information that render_block needs.")
        return 1

    print("PASS — every gallery reproduces byte for byte. Safe to publish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
