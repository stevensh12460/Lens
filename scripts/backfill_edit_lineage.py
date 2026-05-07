"""
scripts/backfill_edit_lineage.py

One-shot backfill: scan all images that don't yet have edited_from_id set
and run the lineage detector on each. Sets the link where a parent RAW exists.

Run: cd ~/lens && PYTHONPATH=. ./venv/bin/python -m scripts.backfill_edit_lineage

Safe to re-run; only touches rows where edited_from_id IS NULL.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import get_db
from services.edit_lineage import link_if_edit, _EDIT_EXTS


def main(batch_size: int = 1000, limit: int | None = None) -> None:
    started = time.time()
    # Only candidates: edit-format extensions, no link yet.
    ext_clause = " OR ".join("LOWER(file_path) LIKE ?" for _ in _EDIT_EXTS)
    params = [f"%{ext}" for ext in _EDIT_EXTS]
    sql = f"""
        SELECT id, file_path FROM images
        WHERE edited_from_id IS NULL
          AND ({ext_clause})
        ORDER BY id ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    total = len(rows)
    print(f"[backfill] {total} candidate edit-format images to scan")
    linked = 0
    failed = 0
    for i, row in enumerate(rows, 1):
        try:
            parent = link_if_edit(row["id"], row["file_path"])
            if parent:
                linked += 1
        except Exception as e:
            failed += 1
            print(f"  ERR id={row['id']}: {e}")
        if i % batch_size == 0:
            elapsed = time.time() - started
            print(f"  {i}/{total} scanned, {linked} linked, {failed} errored ({elapsed:.1f}s)")

    elapsed = time.time() - started
    print(f"[backfill] done: scanned={total} linked={linked} errored={failed} elapsed={elapsed:.1f}s")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="cap rows for testing")
    parser.add_argument("--batch", type=int, default=1000, help="progress print interval")
    args = parser.parse_args()
    main(batch_size=args.batch, limit=args.limit)
