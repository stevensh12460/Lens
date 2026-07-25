"""
Phase 11 — Nightly Report
Generates overnight/session processing reports for the dashboard.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from core.database import get_db
from lens_core.tz import now_et

logger = logging.getLogger("lens.nightly_report")

_REPORT_PATH = Path("/tmp/lens_nightly_report.json")
_BASELINE_RATE = 230  # images per hour

_OVERNIGHT_REPORTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS overnight_reports (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date          DATE DEFAULT (date('now')),
    images_processed     INTEGER,
    new_portfolio_worthy INTEGER,
    new_social_ready     INTEGER,
    library_coverage_pct REAL,
    priority_1_pct       REAL,
    priority_2_pct       REAL,
    report_json          TEXT,
    generated_at         DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def _ensure_table() -> None:
    """Create overnight_reports table if it doesn't exist."""
    with get_db() as conn:
        conn.executescript(_OVERNIGHT_REPORTS_SCHEMA)


def generate_report() -> dict:
    """
    Compute stats for the last 8 hours and return a report dict.
    """
    _ensure_table()
    cutoff = (now_et() - timedelta(hours=8)).isoformat()
    now_iso = now_et().isoformat()

    with get_db() as conn:
        # Images processed in the last 8 hours (pass3 completed)
        images_processed = conn.execute(
            "SELECT COUNT(*) FROM images WHERE pass3_at > ?", (cutoff,)
        ).fetchone()[0]

        # New portfolio-worthy (portfolio_worthy = TRUE, pass3 in last 8h)
        new_portfolio_worthy = conn.execute(
            "SELECT COUNT(*) FROM images WHERE portfolio_worthy = TRUE AND pass3_at > ?",
            (cutoff,),
        ).fetchone()[0]

        # New social-ready (content_ready = TRUE, pass3 in last 8h)
        new_social_ready = conn.execute(
            "SELECT COUNT(*) FROM images WHERE content_ready = TRUE AND pass3_at > ?",
            (cutoff,),
        ).fetchone()[0]

        # New print candidates (print_worthy = TRUE, updated in last 8h via pass3_at)
        new_print_candidates = conn.execute(
            "SELECT COUNT(*) FROM images WHERE print_worthy = TRUE AND pass3_at > ?",
            (cutoff,),
        ).fetchone()[0]

        # Total vision-tagged (pass3 complete)
        pass3_complete = conn.execute(
            "SELECT COUNT(*) FROM images WHERE pass3_at IS NOT NULL"
        ).fetchone()[0]

        # Total images needing pass3 (have pass2 but no pass3)
        pass3_remaining = conn.execute(
            "SELECT COUNT(*) FROM images WHERE pass2_at IS NOT NULL AND pass3_at IS NULL"
        ).fetchone()[0]

        # Total imported
        total_imported = conn.execute(
            "SELECT COUNT(*) FROM images"
        ).fetchone()[0]

        # Library coverage
        library_coverage_pct = (
            round(pass3_complete / total_imported * 100, 2) if total_imported > 0 else 0.0
        )

        # Priority 1 status — top 500 by nima_composite
        p1_total = 500
        p1_complete = conn.execute("""
            SELECT COUNT(*) FROM images
            WHERE id IN (
                SELECT id FROM images
                WHERE nima_composite IS NOT NULL
                ORDER BY nima_composite DESC
                LIMIT 500
            )
            AND pass3_at IS NOT NULL
        """).fetchone()[0]

        # Priority 2 status — lr_pick = 'pick'
        p2_total = conn.execute(
            "SELECT COUNT(*) FROM images WHERE lr_pick = 'pick'"
        ).fetchone()[0]
        p2_complete = conn.execute(
            "SELECT COUNT(*) FROM images WHERE lr_pick = 'pick' AND pass3_at IS NOT NULL"
        ).fetchone()[0]

        # Estimated completion
        estimated_completion_hours = round(pass3_remaining / _BASELINE_RATE, 2)

    report = {
        "images_processed": images_processed,
        "new_portfolio_worthy": new_portfolio_worthy,
        "new_social_ready": new_social_ready,
        "new_print_candidates": new_print_candidates,
        "pass3_complete": pass3_complete,
        "pass3_remaining": pass3_remaining,
        "total_imported": total_imported,
        "library_coverage_pct": library_coverage_pct,
        "priority_1_status": {"complete": p1_complete, "total": p1_total},
        "priority_2_status": {"complete": p2_complete, "total": p2_total},
        "estimated_completion_hours": estimated_completion_hours,
        "baseline_rate_per_hour": _BASELINE_RATE,
        "generated_at": now_iso,
    }
    return report


def save_report(report_dict: dict) -> None:
    """
    Save the report to /tmp/lens_nightly_report.json and to the overnight_reports table.
    """
    _ensure_table()

    # Save to JSON file
    _REPORT_PATH.write_text(json.dumps(report_dict, indent=2))
    logger.info(f"[nightly_report] Saved to {_REPORT_PATH}")

    # Save to DB
    p1 = report_dict.get("priority_1_status", {})
    p2 = report_dict.get("priority_2_status", {})
    p1_total = p1.get("total", 0)
    p2_total = p2.get("total", 0)

    p1_pct = round(p1.get("complete", 0) / p1_total * 100, 2) if p1_total > 0 else 0.0
    p2_pct = round(p2.get("complete", 0) / p2_total * 100, 2) if p2_total > 0 else 0.0

    with get_db() as conn:
        conn.execute(
            """INSERT INTO overnight_reports
               (images_processed, new_portfolio_worthy, new_social_ready,
                library_coverage_pct, priority_1_pct, priority_2_pct, report_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                report_dict.get("images_processed", 0),
                report_dict.get("new_portfolio_worthy", 0),
                report_dict.get("new_social_ready", 0),
                report_dict.get("library_coverage_pct", 0.0),
                p1_pct,
                p2_pct,
                json.dumps(report_dict),
            ),
        )
    logger.info("[nightly_report] Saved to overnight_reports table")


def get_latest_report() -> dict:
    """
    Return the latest nightly report.
    Reads from /tmp/lens_nightly_report.json; falls back to DB if file is missing.
    """
    # Try the JSON file first
    if _REPORT_PATH.exists():
        try:
            return json.loads(_REPORT_PATH.read_text())
        except Exception as e:
            logger.warning(f"[nightly_report] Could not read JSON file: {e}")

    # Fall back to DB
    _ensure_table()
    with get_db() as conn:
        row = conn.execute(
            "SELECT report_json FROM overnight_reports ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()
        if row and row["report_json"]:
            try:
                return json.loads(row["report_json"])
            except Exception as e:
                logger.error(f"[nightly_report] Could not parse DB report JSON: {e}")

    return {"error": "No report available", "generated_at": None}
