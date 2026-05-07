"""
Phase 7b — Print Curator (rule-based)

Tiers portfolio-worthy images into print tiers using existing pass2 NIMA scores.
No LLM calls — all data is already available from pass2/pass3.

Tier thresholds (based on actual distribution in this catalog):
  fine_art    — nima_composite >= 7.0  (top ~0.1%)
  standard    — nima_composite >= 6.5 and < 7.0
  below       — nima_composite < 6.5  (not print-offered)

Legacy LLM-based scoring is kept as `score_single_with_llm` for optional
manual override on individual images.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from core.database import get_db
from core.ollama import ollama

logger = logging.getLogger(__name__)


# ─── Tier thresholds ─────────────────────────────────────────────────────────
FINE_ART_MIN = 7.0
STANDARD_MIN = 6.5


def _tier_for_score(score: float | None) -> tuple[str, bool, float]:
    """
    Given nima_composite, return (tier, print_worthy, print_score).
    print_score is a normalized 0-10 based on the nima_composite value.
    """
    if score is None:
        return ("below_threshold", False, 0.0)
    if score >= FINE_ART_MIN:
        return ("fine_art", True, round(score, 2))
    if score >= STANDARD_MIN:
        return ("standard", True, round(score, 2))
    return ("below_threshold", False, round(score, 2))


def score_print_candidates(limit: int = 5000) -> int:
    """
    Rule-based tiering for all pass2-scored images.
    Uses existing nima_composite — no LLM call, no portfolio_worthy gate.
    Returns count of images newly scored as print_worthy.
    """
    worthy_count = 0
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, nima_composite, composition FROM images
               WHERE nima_composite IS NOT NULL
                 AND print_score IS NULL
               ORDER BY nima_composite DESC NULLS LAST
               LIMIT ?""",
            (limit,),
        ).fetchall()

        for row in rows:
            tier, worthy, score = _tier_for_score(row["nima_composite"])
            # Guess print_technique from composition/tags if present
            technique = _guess_technique(row["composition"] or "")
            conn.execute(
                """UPDATE images
                   SET print_score = ?, print_worthy = ?, print_tier = ?,
                       print_technique = ?
                   WHERE id = ?""",
                (score, worthy, tier, technique, row["id"]),
            )
            if worthy:
                worthy_count += 1

    logger.info("Rule-based print tiering complete — %d of %d print_worthy.",
                worthy_count, len(rows))
    return worthy_count


def rescore_all() -> int:
    """
    Re-apply rule-based tiering to ALL pass2-scored images (incl. already scored).
    Useful after adjusting thresholds. Returns worthy count.
    """
    worthy_count = 0
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, nima_composite, composition FROM images
               WHERE nima_composite IS NOT NULL"""
        ).fetchall()
        for row in rows:
            tier, worthy, score = _tier_for_score(row["nima_composite"])
            technique = _guess_technique(row["composition"] or "")
            conn.execute(
                """UPDATE images
                   SET print_score = ?, print_worthy = ?, print_tier = ?,
                       print_technique = ?
                   WHERE id = ?""",
                (score, worthy, tier, technique, row["id"]),
            )
            if worthy:
                worthy_count += 1
    logger.info("Rescored %d images — %d print_worthy.", len(rows), worthy_count)
    return worthy_count


def _guess_technique(composition: str) -> str:
    """Pick a technique label from pass3 composition text. Falls back to 'standard'."""
    c = (composition or "").lower()
    if any(k in c for k in ("motion blur", "panning", "long exposure")):
        return "rotation"
    if "symmet" in c:
        return "orbit"
    return "standard"


# ─── Legacy LLM override (kept for manual per-image rescore) ─────────────────

_PRINT_PROMPT = """Assess this image for fine art print potential. Rate 0-10.
Return JSON: {"print_score": <float>, "strengths": "<one sentence>"}"""


async def score_single_with_llm(image_id: int) -> dict | None:
    """
    Optional: run qwen2.5vl on a single image to get a human-like print assessment.
    Use when you disagree with the rule-based tiering for a specific image.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT file_path FROM images WHERE id = ?", (image_id,)
        ).fetchone()
    if not row:
        return None
    path = Path(row["file_path"])
    if not path.exists():
        return None
    try:
        raw = await ollama.vision_json(path, _PRINT_PROMPT)
        score = float(raw.get("print_score", 0.0))
        tier, worthy, _ = _tier_for_score(score)
        with get_db() as conn:
            conn.execute(
                """UPDATE images
                   SET print_score = ?, print_worthy = ?, print_tier = ?
                   WHERE id = ?""",
                (round(score, 2), worthy, tier, image_id),
            )
        return {
            "image_id": image_id,
            "print_score": round(score, 2),
            "print_tier": tier,
            "print_worthy": worthy,
            "strengths": raw.get("strengths", ""),
        }
    except Exception as exc:
        logger.error("LLM override failed for image %d: %s", image_id, exc)
        return None


# ─── Read helpers (unchanged) ────────────────────────────────────────────────

def get_print_worthy_images(tier: str | None = None, limit: int = 50) -> list[dict]:
    """Return images assessed as print_worthy, optionally filtered by tier."""
    with get_db() as conn:
        if tier:
            rows = conn.execute(
                """SELECT * FROM images
                   WHERE print_worthy = 1 AND print_tier = ?
                   ORDER BY print_score DESC
                   LIMIT ?""",
                (tier, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM images
                   WHERE print_worthy = 1
                   ORDER BY print_score DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_top_prints(limit: int = 20) -> list[dict]:
    """Top print candidates by print_score, falling back to nima_composite."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, file_name, file_path, print_score, print_tier,
                      print_technique, print_worthy, nima_composite,
                      nima_aesthetic, portfolio_worthy, tags, caption_draft,
                      edition_title, editions_sold, edition_size,
                      print_total_revenue, print_times_sold
               FROM images
               WHERE print_score IS NOT NULL
               ORDER BY print_score DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        if not rows:
            rows = conn.execute(
                """SELECT id, file_name, file_path, NULL AS print_score,
                          NULL AS print_tier, NULL AS print_technique,
                          portfolio_worthy AS print_worthy,
                          nima_composite, nima_aesthetic, portfolio_worthy,
                          tags, caption_draft,
                          edition_title, editions_sold, edition_size,
                          print_total_revenue, print_times_sold
                   FROM images
                   WHERE portfolio_worthy = 1 AND pass3_at IS NOT NULL
                   ORDER BY nima_composite DESC NULLS LAST
                   LIMIT ?""",
                (limit,),
            ).fetchall()

    return [dict(r) for r in rows]
