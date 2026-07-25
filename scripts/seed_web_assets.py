#!/usr/bin/env python3
"""
seed_web_assets.py — one-shot: teach LENS what is currently on the website.

The site was hand-built, so the database starts out knowing nothing about it.
This reads the four gallery pages in DOM order and records one web_assets row
per figure, preserving the hand-tuned sequence and layout rhythm exactly.

Seeding in the CURRENT order is what makes the promise "the first publish
changes nothing" true. If this instead sorted by filename, the first publish
would silently reshuffle the live site (landscape runs 01,02,03,05,04,07,06 by
deliberate choice, not by accident).

lr_photo_uuid is left NULL — nothing links a 2400px sRGB export back to a photo
in a 400k-image catalog. That mapping happens later, at M4, via perceptual hash
plus human confirmation.

Idempotent: re-running updates rows in place rather than duplicating them.

Usage:  ~/lens/venv/bin/python scripts/seed_web_assets.py [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from core.database import get_db, init_db  # noqa: E402
from lens_core.tz import now_et  # noqa: E402
from services.web_publisher import (  # noqa: E402
    SECTIONS,
    SITE_ROOT,
    extract_block,
    parse_gallery,
    render_block,
)


def file_facts(path: Path) -> tuple[str, int, int]:
    """(sha256, width, height) for a deployed JPEG."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with Image.open(path) as img:
        width, height = img.size
    return digest, width, height


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="verify the round-trip and report, but write nothing")
    args = ap.parse_args()

    # Guard: refuse to seed unless the renderer can reproduce every gallery
    # byte for byte. A mismatch means the data model has lost information, and
    # seeding anyway would bake that loss in.
    print("Verifying round-trip fidelity before writing anything...")
    parsed: dict[str, list] = {}
    for section in SECTIONS:
        assets = parse_gallery(section)
        if render_block(assets) != extract_block(section):
            print(f"  ABORT: {section} does not round-trip byte-for-byte.")
            return 1
        parsed[section] = assets
        print(f"  ok  {section:10} {len(assets)} figures")

    if not args.dry_run:
        init_db()

    stamp = now_et().isoformat()
    total = 0

    with get_db() as conn:
        for section, assets in parsed.items():
            for asset in assets:
                media = SITE_ROOT / "media" / section / asset.file_name
                if not media.exists():
                    print(f"  ABORT: {media} is referenced but missing on disk.")
                    return 1
                sha, width, height = file_facts(media)

                if args.dry_run:
                    print(f"  would seed {section}/{asset.slug} "
                          f"idx={asset.sort_index} layout={asset.layout} "
                          f"{width}x{height} sha={sha[:8]}")
                    total += 1
                    continue

                conn.execute(
                    """INSERT INTO web_assets
                         (section, slug, file_name, sha256, width, height, layout,
                          alt_text, caption, sort_index, state, first_published_at,
                          last_published_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,'live',?,?)
                       ON CONFLICT(section, slug) DO UPDATE SET
                         file_name        = excluded.file_name,
                         sha256           = excluded.sha256,
                         width            = excluded.width,
                         height           = excluded.height,
                         layout           = excluded.layout,
                         alt_text         = excluded.alt_text,
                         caption          = excluded.caption,
                         sort_index       = excluded.sort_index,
                         state            = 'live'""",
                    (section, asset.slug, asset.file_name, sha, width, height,
                     asset.layout, asset.alt_text, asset.caption,
                     asset.sort_index, stamp, stamp),
                )
                total += 1

    verb = "would seed" if args.dry_run else "seeded"
    print(f"\n{verb} {total} assets across {len(SECTIONS)} sections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
