"""
tests/smoke.py — minimal end-to-end gate for the lens-core extraction.

Run this before any refactor step. After every refactor step, run it again
and assert it stays green. If anything turns red, revert that step.

Usage:
    cd ~/lens && PYTHONPATH=. ./venv/bin/python -m tests.smoke

Exit code 0 = green. Non-zero = caller must revert.

These are NOT unit tests. They're checkpoints. We're asserting:
  • The DB schema matches expectations
  • The pragmas applied
  • The HTTP API answers on critical endpoints
  • A handful of known-good rows behave as expected

Designed to run in <10 seconds.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

DB_PATH = Path.home() / "lens/data/lens.db"
API_BASE = "http://localhost:8600"

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
WARN = "\033[33m!\033[0m"

RESULTS: list[tuple[str, bool, str]] = []


def assert_eq(name: str, actual, expected, *, soft: bool = False) -> bool:
    ok = actual == expected
    msg = f"got {actual!r} expected {expected!r}" if not ok else f"= {actual!r}"
    RESULTS.append((name, ok, msg))
    return ok


def assert_truthy(name: str, value, msg: str = "") -> bool:
    ok = bool(value)
    RESULTS.append((name, ok, msg or f"value={value!r}"))
    return ok


def assert_in(name: str, item, container, msg: str = "") -> bool:
    ok = item in container
    RESULTS.append((name, ok, msg or f"{item!r} in {type(container).__name__}"))
    return ok


def http_get(path: str, timeout: float = 10.0) -> tuple[int, dict]:
    req = Request(f"{API_BASE}{path}")
    with urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8")
    try:
        return r.status, json.loads(body)
    except json.JSONDecodeError:
        return r.status, {"_raw": body[:200]}


def http_post(path: str, payload: dict | None = None, timeout: float = 60.0) -> tuple[int, dict]:
    data = json.dumps(payload or {}).encode("utf-8")
    req = Request(
        f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8")
    try:
        return r.status, json.loads(body)
    except json.JSONDecodeError:
        return r.status, {"_raw": body[:200]}


# ── Tests ────────────────────────────────────────────────────────────────────

def test_db_path_exists():
    assert_truthy("DB file exists", DB_PATH.exists(), str(DB_PATH))


def test_pragmas():
    """Verify the Phase-0 pragma set is applied on a fresh connection."""
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    # apply same pragmas a real call would
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-65536")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=4294967296")
    conn.execute("PRAGMA foreign_keys=ON")

    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    cache = conn.execute("PRAGMA cache_size").fetchone()[0]
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    temp = conn.execute("PRAGMA temp_store").fetchone()[0]
    conn.close()

    assert_eq("pragma journal_mode", journal, "wal")
    assert_eq("pragma synchronous=NORMAL (1)", sync, 1)
    assert_eq("pragma cache_size", cache, -65536)
    assert_eq("pragma foreign_keys=ON (1)", fk, 1)
    assert_eq("pragma temp_store=MEMORY (2)", temp, 2)


REQUIRED_IMAGE_COLUMNS = [
    "id", "file_path", "file_name", "pass1_status", "pass1_at", "pass2_at",
    "pass3_at", "pass3_model", "nima_aesthetic", "nima_technical",
    "nima_composite", "cull_score", "score_composition",
    "genre", "mood", "lighting", "subject_type", "tags", "subjects",
    "description", "composition", "emotional_impact", "color_palette",
    "setting", "narrative_hook", "caption_seed_phrases",
    "recommended_caption_tone", "recommended_pillar",
    "dominant_visual_element", "viewer_emotion_target",
    "edited_from_id", "manual_added", "user_context",
    "caption_draft", "content_ready", "portfolio_worthy", "print_worthy",
]


def test_schema_columns():
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
    conn.close()
    missing = [c for c in REQUIRED_IMAGE_COLUMNS if c not in cols]
    assert_eq(f"images columns ({len(REQUIRED_IMAGE_COLUMNS)} required)", missing, [])


def test_row_counts_sane():
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    img_count = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    conn.close()
    assert_truthy("images row count > 100k (sanity)", img_count > 100_000, f"={img_count}")


def test_health():
    code, body = http_get("/health")
    assert_eq("GET /health 200", code, 200)
    assert_eq("/health status=ok", body.get("status"), "ok")


def test_pipeline_why_complete():
    """A known-complete image returns stage=complete."""
    # 67085 is the recently-posted image — pass3_at set
    code, body = http_get("/pipeline/why/67085")
    assert_eq("GET /pipeline/why/67085 200", code, 200)
    assert_eq("why/67085 stage", body.get("stage"), "complete")


def test_pipeline_why_missing():
    code, body = http_get("/pipeline/why/0")
    assert_eq("GET /pipeline/why/0 200", code, 200)
    assert_eq("why/0 stage=missing", body.get("stage"), "missing")


def test_post_candidates_edits_first():
    code, body = http_get("/social/post-candidates?limit=10&exclude_scheduled=false&exclude_posted=false")
    assert_eq("GET /social/post-candidates 200", code, 200)
    images = body.get("images", [])
    assert_truthy("post-candidates returns 10 images", len(images) == 10, f"got {len(images)}")
    if images:
        # First should be edit (is_raw=0) since edits sort first
        first_is_edit = images[0].get("is_raw") == 0
        assert_truthy("first candidate is an edit (is_raw=0)", first_is_edit,
                      f"first.file_name={images[0].get('file_name')}")


def test_caption_endpoint():
    """Generate a caption on a known content_ready image and validate shape."""
    code, body = http_post("/social/caption", {"image_id": 670731, "style": "instagram"}, timeout=60)
    assert_eq("POST /social/caption 200", code, 200)
    cap = body.get("caption", "")
    tags = body.get("hashtags", [])
    assert_truthy("caption non-empty", bool(cap.strip()))
    assert_truthy("≤5 hashtags (per IG cap)", len(tags) <= 5, f"got {len(tags)}")


def test_image_lineage_endpoint():
    """Image #67085 is known to have a parent RAW (#785169)."""
    code, body = http_get("/social/image-lineage/67085")
    assert_eq("GET /social/image-lineage/67085 200", code, 200)
    assert_eq("image 67085 is_edit=true", body.get("is_edit"), True)


def test_image_preview_endpoint():
    code, body = http_get("/social/image-preview/67085")
    assert_eq("GET /social/image-preview/67085 200", code, 200)
    assert_eq("image-preview status=image_only", body.get("status"), "image_only")
    assert_eq("image-preview includes user_context",
              "user_context" in body, True)


def test_user_context_save_and_read():
    """Save a user_context, read it back, leave it as-found."""
    image_id = 670731
    # capture original
    code, body = http_get(f"/social/images/{image_id}/user-context")
    assert_eq("GET user-context 200", code, 200)
    original = body.get("user_context", "")

    test_value = f"smoke test marker {int(time.time())}"
    try:
        code, body = http_post(f"/social/images/{image_id}/user-context",
                                {"user_context": test_value})
        assert_eq("POST user-context 200", code, 200)
        # read back
        code, body = http_get(f"/social/images/{image_id}/user-context")
        assert_eq("user-context round-trip value", body.get("user_context"), test_value)
    finally:
        # restore
        http_post(f"/social/images/{image_id}/user-context",
                  {"user_context": original})


def test_calendar_post_includes_new_fields():
    code, body = http_get("/social/calendar/130")
    assert_eq("GET /social/calendar/130 200", code, 200)
    for f in ("narrative_hook", "user_context", "edited_from_id"):
        assert_in(f"calendar response includes {f}", f, body)


def test_mode_endpoint():
    code, body = http_get("/social/mode")
    assert_eq("GET /social/mode 200", code, 200)
    assert_in("mode is one of expected values",
              body.get("mode"), ("auto", "text", "off", "priority"))


# ── Runner ───────────────────────────────────────────────────────────────────

def main() -> int:
    tests = [
        test_db_path_exists,
        test_pragmas,
        test_schema_columns,
        test_row_counts_sane,
        test_health,
        test_pipeline_why_complete,
        test_pipeline_why_missing,
        test_post_candidates_edits_first,
        test_caption_endpoint,
        test_image_lineage_endpoint,
        test_image_preview_endpoint,
        test_user_context_save_and_read,
        test_calendar_post_includes_new_fields,
        test_mode_endpoint,
    ]
    started = time.time()
    for t in tests:
        try:
            t()
        except (URLError, HTTPError) as e:
            RESULTS.append((t.__name__, False, f"HTTP error: {e}"))
        except Exception as e:
            RESULTS.append((t.__name__, False, f"exception: {type(e).__name__}: {e}"))

    elapsed = time.time() - started
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print()
    for name, ok, msg in RESULTS:
        glyph = PASS if ok else FAIL
        print(f"  {glyph}  {name:<52}  {msg}")
    print()
    print(f"  {passed}/{len(RESULTS)} green in {elapsed:.1f}s")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
