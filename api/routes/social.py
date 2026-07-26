from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime, timedelta
from pathlib import Path
import json
import subprocess
import calendar as cal_mod

from core.database import get_db
from core.config import settings
from core.ollama import ollama, get_mode
import services.caption_gen as caption_svc
import services.social_queue as queue_svc
import services.grid_aesthetic as grid_svc
import services.pixieset_sync as pixieset_svc
import services.post_scheduler as scheduler_svc
import services.retag_service as retag_svc

router = APIRouter()


# ── Caption endpoints ──────────────────────────────────────────────────────────

class CaptionRequest(BaseModel):
    image_id: int
    style: str = "instagram"  # instagram, poem, artist_statement, minimal, story


class BatchCaptionRequest(BaseModel):
    limit: int = 10
    genre: Optional[str] = None


@router.post("/caption")
async def generate_caption(req: CaptionRequest):
    """Generate an Instagram caption + hashtags for a single image."""
    try:
        result = await caption_svc.generate_caption(req.image_id, style=req.style)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Caption generation failed: {e}")


@router.post("/caption/batch")
async def generate_captions_batch(req: BatchCaptionRequest):
    """Generate captions for multiple content-ready images that have no caption yet."""
    result = await caption_svc.generate_captions_batch(
        limit=req.limit,
        genre=req.genre,
    )
    return result


@router.get("/image-preview/{image_id}")
def get_image_preview(image_id: int):
    """Return an image's full preview payload — same shape the Post Preview
    modal uses, but with no calendar post binding. Lets the frontend open the
    rich preview (caption, hashtags, vision analysis, lineage, file path)
    on a candidate that isn't scheduled yet.

    Status flag is set to 'image_only' so the modal can hide post-specific UI
    (Approve, calendar status badge, Save-to-calendar) and surface a
    "Schedule to Calendar" button instead.
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT id AS image_id,
                      file_path, file_name,
                      genre, mood, lighting, subject_type, tags,
                      color_palette, setting,
                      caption_draft, pixieset_url, grid_fit_score,
                      description, composition, emotional_impact, print_notes,
                      pass3_model, pass3_at,
                      narrative_hook, caption_seed_phrases,
                      recommended_caption_tone, recommended_pillar,
                      dominant_visual_element, viewer_emotion_target,
                      edited_from_id, user_context
               FROM images WHERE id = ?""",
            (image_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Image {image_id} not found")
    payload = dict(row)
    # Shape it to look like a calendar post so the frontend renderer can stay
    # the same. id=None signals "image only, no post yet"; status='image_only'
    # is the discriminator.
    payload.update({
        "id": None,
        "post_date": None,
        "post_time": None,
        "pillar": None,
        "status": "image_only",
        "scheduled_at": None,
        "posted_at": None,
        "image_genre": payload.get("genre"),
        "caption": None,
        "hashtags": None,
    })
    return payload


class _ImageCaptionDraftRequest(BaseModel):
    caption: str
    hashtags: Optional[str] = None  # space-separated hashtag string


_USER_CONTEXT_MAX = 500


class _UserContextRequest(BaseModel):
    user_context: Optional[str] = ""


@router.get("/images/{image_id}/user-context")
def get_image_user_context(image_id: int):
    """Return the photographer's free-form notes for this image."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, user_context FROM images WHERE id = ?", (image_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Image {image_id} not found")
    return {
        "image_id": image_id,
        "user_context": row["user_context"] or "",
        "max_chars": _USER_CONTEXT_MAX,
    }


@router.post("/images/{image_id}/user-context")
def save_image_user_context(image_id: int, req: _UserContextRequest):
    """Save free-form photographer notes ("things I know that the camera can't
    see") for this image. Used by caption_gen to inject as factual assertions
    into the LLM prompt. Capped at _USER_CONTEXT_MAX chars to keep the prompt
    bounded — if the user sends more, it's truncated server-side."""
    text = (req.user_context or "").strip()
    if len(text) > _USER_CONTEXT_MAX:
        text = text[:_USER_CONTEXT_MAX]
    with get_db() as conn:
        cur = conn.execute("SELECT id FROM images WHERE id = ?", (image_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Image {image_id} not found")
        conn.execute(
            "UPDATE images SET user_context = ? WHERE id = ?",
            (text or None, image_id),
        )
    return {
        "image_id": image_id,
        "user_context": text,
        "saved_chars": len(text),
        "max_chars": _USER_CONTEXT_MAX,
    }


@router.post("/images/{image_id}/caption-draft")
def save_image_caption_draft(image_id: int, req: _ImageCaptionDraftRequest):
    """Save edited caption text + hashtags directly onto the image row's
    caption_draft column, with no calendar post involved. Used by the
    image-only preview mode of the modal."""
    with get_db() as conn:
        row = conn.execute("SELECT id FROM images WHERE id = ?", (image_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Image {image_id} not found")
        hashtag_list = [
            h.strip() for h in (req.hashtags or "").split() if h.strip().startswith("#")
        ]
        caption_draft = json.dumps({"caption": req.caption, "hashtags": hashtag_list})
        conn.execute(
            "UPDATE images SET caption_draft = ? WHERE id = ?",
            (caption_draft, image_id),
        )
    return {"image_id": image_id, "saved": True}


@router.get("/image-lineage/{image_id}")
def get_image_lineage(image_id: int):
    """Return this image's edit-lineage payload: parent RAW (if any), child
    edits (if any), and a side-by-side score delta against the parent.

    Used by the Post Preview modal to show whether the editor's work actually
    moved the cull / NIMA / composition scores in the right direction.
    """
    from services.edit_lineage import lineage_for, link_if_edit

    # Lazy detection — if this row never went through the watcher hook (e.g.,
    # ingested before the feature existed), try linking now.
    with get_db() as conn:
        row = conn.execute(
            "SELECT file_path, edited_from_id FROM images WHERE id = ?",
            (image_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Image {image_id} not found")
    if row["edited_from_id"] is None and row["file_path"]:
        try:
            link_if_edit(image_id, row["file_path"])
        except Exception:
            pass

    return lineage_for(image_id)


@router.post("/reveal-image/{image_id}")
def reveal_image_in_finder(image_id: int):
    """Open macOS Finder with the image file selected. Used by the dashboard
    "Reveal in Finder" button so the user can quickly drag it into Pixieset."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, file_path FROM images WHERE id = ?", (image_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Image {image_id} not found")
    file_path = row["file_path"]
    if not file_path or not Path(file_path).exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not on disk: {file_path}",
        )
    try:
        subprocess.run(["open", "-R", file_path], check=True, timeout=10)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"Finder reveal failed: {e}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Finder reveal timed out")
    return {"image_id": image_id, "file_path": file_path, "revealed": True}


@router.post("/vision-analyze/{image_id}")
async def vision_analyze_single(image_id: int, restore_text_model: bool = True):
    """
    Run a deep 32b vision analysis on a single image and persist the rich
    caption-fuel fields. Used by the dashboard "Deep Analysis" button.

    Flow:
      1. Resolve image file_path
      2. Unload current text model (frees VRAM)
      3. Force qwen2.5vl:32b for this single call (does not change global config)
      4. Run preprocess + vision_json with the rich _TAG_PROMPT
      5. UPDATE images SET narrative_hook, caption_seed_phrases, ... = ...
      6. Optionally re-preload the text model so subsequent captions are fast

    ~96s wall time per image on M1 Max. Synchronous — caller blocks.
    """
    from pipeline.pass3_tag import _TAG_PROMPT
    from pipeline.preprocessor import preprocess

    with get_db() as conn:
        row = conn.execute(
            "SELECT id, file_path, file_name FROM images WHERE id = ?",
            (image_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Image {image_id} not found")

    image_path = Path(row["file_path"])
    if not image_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not on disk: {row['file_path']}",
        )

    saved_text_model = settings.text_model
    started = now_et()

    try:
        # Free VRAM for the 32b vision model.
        await ollama.unload_all()

        # Tag with 32b vision regardless of the global vision_model setting.
        previous_vision_model = ollama.vision_model
        ollama.vision_model = "qwen2.5vl:32b"
        try:
            prep_path = preprocess(image_path)
            result = await ollama.vision_json(prep_path, _TAG_PROMPT, num_predict=768)
        finally:
            ollama.vision_model = previous_vision_model

        # Persist the rich fields plus standard pass3 columns.
        tags_json         = json.dumps(result.get("tags", []))
        subjects_json     = json.dumps(result.get("subjects", []))
        seed_phrases_json = json.dumps(result.get("caption_seed_phrases", []))
        textures_json     = json.dumps(result.get("texture_vocabulary", []))
        verbs_json        = json.dumps(result.get("verb_seeds", []))

        with get_db() as conn:
            conn.execute(
                """UPDATE images SET
                   genre = ?, mood = ?, lighting = ?, subject_type = ?,
                   faces_present = ?, face_count = ?, color_palette = ?,
                   setting = ?, quality_score = ?, portfolio_worthy = ?,
                   content_ready = ?, tags = ?,
                   description = ?, composition = ?, subjects = ?, print_notes = ?,
                   technical_issues = ?, emotional_impact = ?,
                   narrative_hook = ?, caption_seed_phrases = ?,
                   recommended_caption_tone = ?, recommended_pillar = ?,
                   dominant_visual_element = ?, viewer_emotion_target = ?,
                   texture_vocabulary = ?, verb_seeds = ?, visual_tension = ?,
                   pass3_at = ?, pass3_model = ?
                   WHERE id = ?""",
                (
                    result.get("genre"),
                    result.get("mood"),
                    result.get("lighting"),
                    result.get("subject_type"),
                    result.get("faces_present", False),
                    result.get("face_count", 0),
                    result.get("color_palette", ""),
                    result.get("setting"),
                    result.get("quality_score"),
                    result.get("portfolio_worthy", False),
                    result.get("content_ready", False),
                    tags_json,
                    result.get("description"),
                    result.get("composition"),
                    subjects_json,
                    result.get("print_notes"),
                    result.get("technical_issues"),
                    result.get("emotional_impact"),
                    result.get("narrative_hook"),
                    seed_phrases_json,
                    result.get("recommended_caption_tone"),
                    result.get("recommended_pillar"),
                    result.get("dominant_visual_element"),
                    result.get("viewer_emotion_target"),
                    textures_json,
                    verbs_json,
                    result.get("visual_tension"),
                    now_et().isoformat(),
                    "qwen2.5vl:32b",
                    image_id,
                ),
            )
    finally:
        # Free the 32b vision and reload the text model so the next caption
        # click is fast. Best-effort — failures here don't undo the save.
        if restore_text_model:
            try:
                await ollama.unload_all()
                await ollama.preload(saved_text_model)
            except Exception:
                pass

    elapsed = (now_et() - started).total_seconds()
    return {
        "image_id": image_id,
        "file_name": row["file_name"],
        "elapsed_sec": round(elapsed, 1),
        "model": "qwen2.5vl:32b",
        "narrative_hook": result.get("narrative_hook"),
        "caption_seed_phrases": result.get("caption_seed_phrases", []),
        "recommended_caption_tone": result.get("recommended_caption_tone"),
        "recommended_pillar": result.get("recommended_pillar"),
        "dominant_visual_element": result.get("dominant_visual_element"),
        "viewer_emotion_target": result.get("viewer_emotion_target"),
        "description": result.get("description"),
        "emotional_impact": result.get("emotional_impact"),
        "composition": result.get("composition"),
        "color_palette": result.get("color_palette"),
        "setting": result.get("setting"),
        "lighting": result.get("lighting"),
        "mood": result.get("mood"),
        "genre": result.get("genre"),
        "subject_type": result.get("subject_type"),
        "tags": result.get("tags", []),
        "subjects": result.get("subjects", []),
        "quality_score": result.get("quality_score"),
        "print_notes": result.get("print_notes"),
        "technical_issues": result.get("technical_issues"),
        "texture_vocabulary": result.get("texture_vocabulary", []),
        "verb_seeds": result.get("verb_seeds", []),
        "visual_tension": result.get("visual_tension"),
    }


# ── Queue endpoints ────────────────────────────────────────────────────────────

@router.get("/queue")
def get_social_queue():
    """Return queue depth, unposted counts, and next 7 days schedule summary."""
    return queue_svc.get_queue_depth()


class FillQueueRequest(BaseModel):
    days_ahead: int = 14
    posts_per_day: int = 2
    start_date: Optional[date] = None
    included_genres: Optional[list] = None  # None = use default safe genres


@router.post("/queue/fill")
def fill_social_queue(req: FillQueueRequest):
    """
    DISABLED — auto-fill is locked off per user policy.
    Inappropriate photos were getting auto-selected; calendar is now
    manual-pick only. Use the Post Candidate Pool to schedule each post.
    """
    raise HTTPException(
        status_code=403,
        detail=(
            "Auto-fill is disabled. Pick each photo manually from the "
            "Post Candidate Pool — click an image, choose date/slot/pillar."
        ),
    )


@router.get("/queue/schedule")
def upcoming_schedule(days: int = 7):
    """Return scheduled calendar posts for the next N days."""
    return queue_svc.get_upcoming_schedule(days=days)


# ── Calendar endpoints (existing) ─────────────────────────────────────────────

class CalendarPostCreate(BaseModel):
    post_date: date
    pillar: str
    genre: Optional[str] = None
    format: Optional[str] = None
    concept: Optional[str] = None
    image_id: Optional[int] = None
    shoot_id: Optional[int] = None
    post_time: Optional[str] = "morning"  # morning | evening


@router.get("/calendar")
def get_calendar(start: Optional[date] = None, end: Optional[date] = None):
    with get_db() as conn:
        if start and end:
            rows = conn.execute(
                "SELECT * FROM calendar_posts WHERE post_date BETWEEN ? AND ? ORDER BY post_date",
                (str(start), str(end)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM calendar_posts ORDER BY post_date DESC LIMIT 30"
            ).fetchall()
        return [dict(r) for r in rows]


@router.post("/calendar")
def create_calendar_post(post: CalendarPostCreate):
    slot = (post.post_time or "morning").lower()
    if slot not in ("morning", "evening"):
        slot = "morning"
    with get_db() as conn:
        # Block double-booking the same slot
        existing = conn.execute(
            """SELECT id FROM calendar_posts
               WHERE post_date = ? AND post_time = ? AND status != 'posted'""",
            (str(post.post_date), slot),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"{slot.capitalize()} slot on {post.post_date} is already taken (post {existing['id']})",
            )
        cursor = conn.execute(
            """INSERT INTO calendar_posts
               (post_date, post_time, pillar, genre, format, concept, image_id, shoot_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned')""",
            (str(post.post_date), slot, post.pillar, post.genre, post.format,
             post.concept, post.image_id, post.shoot_id),
        )
        return {"id": cursor.lastrowid, "post_date": str(post.post_date), "post_time": slot}


# ── Monthly collection sync (Lightroom → planned calendar posts) ──────────────

# Full English month names → number, e.g. "january" → 1. cal_mod.month_name[0] is "".
_MONTH_NUM = {name.lower(): num for num, name in enumerate(cal_mod.month_name) if name}


class MonthSyncRequest(BaseModel):
    month: str              # e.g. "January 2026" (full month name + 4-digit year)
    file_paths: list[str]   # absolute master paths, in posting order (index 0 → day 1)


def _parse_month(label: str) -> tuple[int, int]:
    """'January 2026' → (2026, 1). Raises 422 on anything else."""
    parts = label.strip().split()
    if len(parts) == 2 and parts[0].lower() in _MONTH_NUM and parts[1].isdigit():
        return int(parts[1]), _MONTH_NUM[parts[0].lower()]
    raise HTTPException(
        status_code=422,
        detail=f"month must be '<Month> <YYYY>' (e.g. 'January 2026'), got {label!r}",
    )


# Genres that must never reach Instagram, whatever else happens. Boudoir is shot for
# the client and for Steven to review, never to publish — his rule, stated plainly.
# Enforced at all three gates rather than one, because the cost of a mistake here is
# not a bad caption, it is publishing someone's private session. sync-month refuses to
# plan it, the approval endpoint refuses to schedule it, and post_scheduler refuses to
# send it even if a row somehow reached 'scheduled'.
NEVER_PUBLISH_GENRES = {"boudoir"}


@router.post("/calendar/sync-month")
def sync_month(req: MonthSyncRequest):
    """Turn a Lightroom month collection's ordered photos into planned calendar
    posts: position N in the list becomes day N of the month, one post per day at
    the morning slot. Rebuilds only 'planned' rows for the month — already-approved
    ('scheduled') and 'posted' days are left untouched, so a re-sync after a reorder
    never clobbers work already committed."""
    year, month = _parse_month(req.month)
    days_in_month = cal_mod.monthrange(year, month)[1]
    first = date(year, month, 1)
    last = date(year, month, days_in_month)
    slot = "morning"

    created: list[dict] = []
    skipped_unresolved: list[str] = []
    skipped_protected: list[str] = []
    skipped_overflow: list[str] = []
    skipped_private: list[str] = []

    with get_db() as conn:
        # Resync-safe rebuild: drop this month's planned rows, keep posted/scheduled.
        conn.execute(
            """DELETE FROM calendar_posts
               WHERE post_date BETWEEN ? AND ? AND status NOT IN ('posted', 'scheduled')""",
            (str(first), str(last)),
        )
        for index, path in enumerate(req.file_paths):
            if index >= days_in_month:
                skipped_overflow.append(path)
                continue
            img = conn.execute(
                "SELECT id, genre FROM images WHERE file_path = ?", (path,)
            ).fetchone()
            if not img:
                skipped_unresolved.append(path)
                continue
            if (img["genre"] or "").lower() in NEVER_PUBLISH_GENRES:
                # Dragged into the month collection by accident. Skip the DAY too,
                # rather than sliding everything up a slot, so the rest of the month
                # keeps the position-to-day mapping the photographer arranged.
                skipped_private.append(path)
                continue
            post_date = first + timedelta(days=index)
            # After the delete above, any surviving row on this day+slot is posted
            # or scheduled — an approved day we must not overwrite.
            protected = conn.execute(
                "SELECT id FROM calendar_posts WHERE post_date = ? AND post_time = ?",
                (str(post_date), slot),
            ).fetchone()
            if protected:
                skipped_protected.append(str(post_date))
                continue
            cur = conn.execute(
                """INSERT INTO calendar_posts
                   (post_date, post_time, pillar, genre, image_id, status)
                   VALUES (?, ?, 'portfolio', ?, ?, 'planned')""",
                (str(post_date), slot, img["genre"], img["id"]),
            )
            created.append(
                {"id": cur.lastrowid, "post_date": str(post_date), "image_id": img["id"]}
            )

    return {
        "month": req.month,
        "year": year,
        "created": len(created),
        "posts": created,
        "skipped_unresolved": skipped_unresolved,
        "skipped_protected": skipped_protected,
        "skipped_overflow": skipped_overflow,
        "skipped_private": skipped_private,
    }


@router.patch("/calendar/{post_id}/posted")
def mark_posted(post_id: int, platform: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE calendar_posts SET status = 'posted', posted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (post_id,),
        )
        conn.execute(
            "UPDATE images SET posted_at = CURRENT_TIMESTAMP, posted_to = ? WHERE id = (SELECT image_id FROM calendar_posts WHERE id = ?)",
            (platform, post_id),
        )
        return {"status": "posted"}


# ── Schedule endpoints (day/week/month with morning/evening slots) ────────────

@router.get("/schedule")
def get_schedule(view: str = "week", date_str: Optional[str] = None):
    """
    Unified schedule endpoint.
    view = 'day' | 'week' | 'month'
    date_str = ISO date string (defaults to today)
    Returns posts organized by date with morning/evening slots.
    """
    try:
        ref_date = date.fromisoformat(date_str) if date_str else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    base_query = """
        SELECT cp.id, cp.post_date, cp.post_time, cp.pillar, cp.genre, cp.format,
               cp.concept, cp.caption, cp.hashtags, cp.image_id, cp.status,
               cp.posted_at, cp.scheduled_at,
               i.file_path, i.file_name, i.genre AS image_genre, i.mood,
               i.caption_draft, i.pixieset_url, i.grid_fit_score
        FROM calendar_posts cp
        LEFT JOIN images i ON cp.image_id = i.id
    """

    with get_db() as conn:
        if view == "day":
            rows = conn.execute(
                base_query + " WHERE cp.post_date = ? ORDER BY cp.post_time ASC",
                (str(ref_date),),
            ).fetchall()
            posts = [dict(r) for r in rows]
            morning = [p for p in posts if p.get("post_time") == "morning"]
            evening = [p for p in posts if p.get("post_time") == "evening"]
            unslotted = [p for p in posts if p.get("post_time") not in ("morning", "evening")]
            return {
                "view": "day",
                "date": str(ref_date),
                "morning": morning,
                "evening": evening,
                "unslotted": unslotted,
            }

        elif view == "week":
            dow = ref_date.weekday()  # 0=Mon
            monday = ref_date - timedelta(days=dow)
            sunday = monday + timedelta(days=6)
            rows = conn.execute(
                base_query + " WHERE cp.post_date BETWEEN ? AND ? ORDER BY cp.post_date ASC, cp.post_time ASC",
                (str(monday), str(sunday)),
            ).fetchall()
            posts = [dict(r) for r in rows]
            days = {}
            for i in range(7):
                d = monday + timedelta(days=i)
                ds = str(d)
                day_posts = [p for p in posts if p["post_date"] == ds]
                days[ds] = {
                    "date": ds,
                    "weekday": d.strftime("%A"),
                    "morning": [p for p in day_posts if p.get("post_time") == "morning"],
                    "evening": [p for p in day_posts if p.get("post_time") == "evening"],
                    "unslotted": [p for p in day_posts if p.get("post_time") not in ("morning", "evening")],
                }
            return {"view": "week", "start": str(monday), "end": str(sunday), "days": days}

        elif view == "month":
            first_day = ref_date.replace(day=1)
            last_day_num = cal_mod.monthrange(ref_date.year, ref_date.month)[1]
            last_day = ref_date.replace(day=last_day_num)
            rows = conn.execute(
                base_query + " WHERE cp.post_date BETWEEN ? AND ? ORDER BY cp.post_date ASC, cp.post_time ASC",
                (str(first_day), str(last_day)),
            ).fetchall()
            posts = [dict(r) for r in rows]
            days = {}
            for day_num in range(1, last_day_num + 1):
                d = ref_date.replace(day=day_num)
                ds = str(d)
                day_posts = [p for p in posts if p["post_date"] == ds]
                days[ds] = {
                    "date": ds,
                    "weekday": d.strftime("%A"),
                    "post_count": len(day_posts),
                    "morning": [p for p in day_posts if p.get("post_time") == "morning"],
                    "evening": [p for p in day_posts if p.get("post_time") == "evening"],
                    "unslotted": [p for p in day_posts if p.get("post_time") not in ("morning", "evening")],
                    "has_morning": any(p.get("post_time") == "morning" for p in day_posts),
                    "has_evening": any(p.get("post_time") == "evening" for p in day_posts),
                }
            return {
                "view": "month",
                "year": ref_date.year,
                "month": ref_date.month,
                "month_name": ref_date.strftime("%B %Y"),
                "days": days,
            }
        else:
            raise HTTPException(status_code=400, detail="view must be 'day', 'week', or 'month'")


@router.post("/approve/{post_id}")
def approve_post(post_id: int):
    """Move a planned post to 'scheduled' status, arming it for auto-posting."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT cp.id, cp.post_date, cp.post_time, cp.status,
                      COALESCE(cp.genre, i.genre) AS genre
               FROM calendar_posts cp
               LEFT JOIN images i ON i.id = cp.image_id
               WHERE cp.id = ?""",
            (post_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Post {post_id} not found")

        post = dict(row)
        # Second gate. A row can predate the sync-month check, or have been created by
        # another path, so approval refuses it again rather than trusting how it got here.
        if (post.get("genre") or "").lower() in NEVER_PUBLISH_GENRES:
            raise HTTPException(
                status_code=403,
                detail=f"Post {post_id} is genre '{post['genre']}', which is never "
                       f"published. Remove it from the calendar instead.",
            )
        if post["status"] not in ("planned",):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve post with status '{post['status']}'. Must be 'planned'.",
            )

        # Calculate scheduled_at from post_date + time slot.
        # CRITICAL: stored as tz-aware ET ISO ("2026-05-07T09:00:00-04:00").
        # Naive timestamps caused #131 to fire at 4:48 AM ET instead of 9 AM ET
        # because the publisher compared a naive "9 AM" string to UTC now.
        # See feedback_timezone.md and core/tz.py.
        from core.tz import at_et, to_iso_et
        post_time = post.get("post_time") or "morning"
        hour = (
            settings.instagram_morning_hour
            if post_time == "morning"
            else settings.instagram_evening_hour
        )
        scheduled_at = at_et(post["post_date"], hour=hour)

        conn.execute(
            "UPDATE calendar_posts SET status = 'scheduled', scheduled_at = ? WHERE id = ?",
            (to_iso_et(scheduled_at), post_id),
        )
        return {
            "status": "scheduled",
            "post_id": post_id,
            "scheduled_at": to_iso_et(scheduled_at),
            "slot": post_time,
        }


@router.get("/publish/{post_id}/preview")
def publish_preview(post_id: int):
    """
    Offline preview of what /publish would post. Pure read-only.
    No external API calls, no DB writes. Use to review BEFORE any real publish.
    Returns: full payload (image path, caption, hashtags), validation flags, and
    any blocking issues that would prevent IG from accepting the post.
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT cp.*, i.file_path, i.file_name, i.caption_draft,
                      i.pixieset_url, i.genre, i.subject_type
               FROM calendar_posts cp
               LEFT JOIN images i ON cp.image_id = i.id
               WHERE cp.id = ?""",
            (post_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")

    post = dict(row)
    caption = post.get("caption") or post.get("caption_draft") or ""
    hashtags_raw = post.get("hashtags") or ""
    # hashtags may be JSON list or plain string
    hashtags_list = []
    if hashtags_raw:
        try:
            parsed = json.loads(hashtags_raw)
            if isinstance(parsed, list):
                hashtags_list = [str(h).lstrip("#").strip() for h in parsed if h]
        except (ValueError, TypeError):
            hashtags_list = [t.lstrip("#").strip() for t in hashtags_raw.split() if t.strip()]

    hashtag_str = " ".join(f"#{h}" for h in hashtags_list)
    full_caption = f"{caption}\n\n{hashtag_str}".strip() if hashtag_str else caption

    file_path = post.get("file_path") or ""
    file_exists = bool(file_path) and Path(file_path).exists()
    file_size = Path(file_path).stat().st_size if file_exists else 0

    issues = []
    warnings = []
    # IG hard limits
    if len(full_caption) > 2200:
        issues.append(f"Caption too long: {len(full_caption)} chars (IG max 2200)")
    if len(hashtags_list) > 30:
        issues.append(f"Too many hashtags: {len(hashtags_list)} (IG max 30)")
    if not post.get("image_id"):
        issues.append("Post has no image_id attached")
    if not file_exists:
        issues.append(f"Image file missing on disk: {file_path}")
    if file_size > 8 * 1024 * 1024:
        warnings.append(f"Image is {file_size // 1024 // 1024} MB — IG may compress heavily (>8MB)")
    if not caption.strip():
        warnings.append("Caption is empty — only hashtags will post")
    if not settings.instagram_access_token or not settings.instagram_account_id:
        issues.append("Instagram not configured in .env")
    if not post.get("pixieset_url"):
        warnings.append("No pixieset_url — image needs public hosting before real publish (Cloudflare Tunnel etc)")

    return {
        "post_id": post_id,
        "status": post.get("status"),
        "post_date": post.get("post_date"),
        "post_time": post.get("post_time"),
        "pillar": post.get("pillar"),
        "genre": post.get("genre"),
        "subject_type": post.get("subject_type"),
        "image": {
            "id": post.get("image_id"),
            "file_path": file_path,
            "file_name": post.get("file_name"),
            "exists_on_disk": file_exists,
            "size_bytes": file_size,
            "size_mb": round(file_size / 1024 / 1024, 2) if file_size else 0,
            "pixieset_url": post.get("pixieset_url"),
            "thumbnail_endpoint": f"/intelligence/thumb/{post.get('image_id')}" if post.get("image_id") else None,
        },
        "caption_body": caption,
        "hashtags": hashtags_list,
        "hashtag_count": len(hashtags_list),
        "full_caption_preview": full_caption,
        "full_caption_length": len(full_caption),
        "ig_account": {
            "configured": bool(settings.instagram_access_token and settings.instagram_account_id),
            "account_id": settings.instagram_account_id or None,
        },
        "ready_to_publish": len(issues) == 0,
        "blocking_issues": issues,
        "warnings": warnings,
    }


@router.post("/publish/{post_id}")
async def publish_now(post_id: int, dry_run: bool = True):
    """
    Publish a post to Instagram.

    SAFETY: dry_run defaults to TRUE. To actually publish you must explicitly
    pass ?dry_run=false in the query string. With dry_run=true the flow goes
    as far as creating an IG media container (which is NOT publicly visible
    and expires unused in 24h) but stops before media_publish.
    """
    result = await scheduler_svc.publish_post(post_id, dry_run=dry_run)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/instagram/status")
def instagram_status():
    """Instagram connection status, token health, last post."""
    configured = bool(settings.instagram_access_token and settings.instagram_account_id)

    last_post = None
    with get_db() as conn:
        row = conn.execute(
            """SELECT cp.id, cp.post_date, cp.posted_at, cp.pillar, cp.genre
               FROM calendar_posts cp
               WHERE cp.status = 'posted' AND cp.posted_at IS NOT NULL
               ORDER BY cp.posted_at DESC LIMIT 1"""
        ).fetchone()
        if row:
            last_post = dict(row)

    return {
        "configured": configured,
        "account_id": settings.instagram_account_id or None,
        "token_set": bool(settings.instagram_access_token),
        "last_post": last_post,
        "morning_hour": settings.instagram_morning_hour,
        "evening_hour": settings.instagram_evening_hour,
    }


@router.get("/pixieset/status")
def pixieset_status():
    """Pixieset sync status -- catalog count, unsynced."""
    return pixieset_svc.get_sync_status()


@router.delete("/calendar/{post_id}")
def delete_calendar_post(post_id: int):
    """Remove a planned or scheduled post from the calendar."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, status FROM calendar_posts WHERE id = ?", (post_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Post {post_id} not found")
        if row["status"] == "posted":
            raise HTTPException(status_code=400, detail="Cannot remove an already-posted post")
        conn.execute("DELETE FROM calendar_posts WHERE id = ?", (post_id,))
    return {"status": "deleted", "post_id": post_id}


@router.get("/calendar/{post_id}")
def get_calendar_post(post_id: int):
    """Return a single calendar post with full image metadata, including rich
    32b-vision fields when present (narrative_hook etc.)."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT cp.id, cp.post_date, cp.post_time, cp.pillar, cp.genre,
                   cp.caption, cp.hashtags, cp.image_id, cp.status,
                   cp.posted_at, cp.scheduled_at,
                   i.file_path, i.file_name, i.genre AS image_genre, i.mood,
                   i.caption_draft, i.pixieset_url, i.grid_fit_score, i.tags,
                   i.description, i.composition, i.emotional_impact, i.lighting,
                   i.color_palette, i.setting, i.subject_type, i.print_notes,
                   i.pass3_model, i.pass3_at,
                   i.narrative_hook, i.caption_seed_phrases,
                   i.recommended_caption_tone, i.recommended_pillar,
                   i.dominant_visual_element, i.viewer_emotion_target,
                   i.texture_vocabulary, i.verb_seeds, i.visual_tension,
                   i.subjects,
                   i.user_context, i.edited_from_id, i.manual_added
            FROM calendar_posts cp
            LEFT JOIN images i ON cp.image_id = i.id
            WHERE cp.id = ?
        """, (post_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Post {post_id} not found")
    return dict(row)


class CaptionEditRequest(BaseModel):
    caption: str
    hashtags: Optional[str] = None  # space or newline separated hashtag string


@router.patch("/calendar/{post_id}/caption")
def update_post_caption(post_id: int, req: CaptionEditRequest):
    """Save edited caption and hashtags for a calendar post."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, image_id FROM calendar_posts WHERE id = ?", (post_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Post {post_id} not found")

        conn.execute(
            "UPDATE calendar_posts SET caption = ?, hashtags = ? WHERE id = ?",
            (req.caption, req.hashtags, post_id),
        )
        # Also update caption_draft on the image so it persists
        if row["image_id"]:
            import json as _json
            hashtag_list = [h.strip() for h in (req.hashtags or "").split() if h.strip().startswith("#")]
            caption_draft = _json.dumps({"caption": req.caption, "hashtags": hashtag_list})
            conn.execute(
                "UPDATE images SET caption_draft = ? WHERE id = ?",
                (caption_draft, row["image_id"]),
            )
    return {"status": "saved", "post_id": post_id}


@router.post("/caption/batch/scheduled")
async def generate_captions_for_scheduled(days: int = 7):
    """Generate captions for all scheduled posts in the next N days that have no caption."""
    today = date.today()
    end_date = today + timedelta(days=days)
    with get_db() as conn:
        rows = conn.execute("""
            SELECT cp.id, cp.image_id FROM calendar_posts cp
            JOIN images i ON cp.image_id = i.id
            WHERE cp.post_date BETWEEN ? AND ?
              AND cp.status IN ('planned', 'scheduled')
              AND (i.caption_draft IS NULL OR i.caption_draft = '')
              AND cp.image_id IS NOT NULL
        """, (str(today), str(end_date))).fetchall()

    if not rows:
        return {"generated": 0, "message": "All scheduled posts already have captions"}

    generated = 0
    errors = []
    for row in rows:
        try:
            await caption_svc.generate_caption(row["image_id"])
            generated += 1
        except Exception as e:
            errors.append({"post_id": row["id"], "error": str(e)})

    return {"generated": generated, "errors": errors,
            "message": f"Generated {generated} captions"}


@router.get("/grid")
def grid_snapshot():
    """Return the current visible 3x3 Instagram grid."""
    return grid_svc.get_grid_snapshot()


# ── Candidate Pool ────────────────────────────────────────────────────────────

@router.get("/post-candidates")
def get_post_candidates(
    genre: Optional[str] = None,
    subject_type: Optional[str] = None,
    tag: Optional[str] = None,
    min_nima: float = 0.0,
    min_grid_fit: float = 0.0,
    exclude_scheduled: bool = True,
    exclude_posted: bool = True,
    sort: str = "grid_fit",  # grid_fit | nima | random | recent
    limit: int = 500,
):
    """
    Rich candidate pool for IG calendar scheduling. Mirrors /print/candidates
    in shape: multi-filter, scoreable, returns up to 10000 cards with full
    metadata + scheduled/posted state flags.

    Filters:
      genre           — nature, portrait, wedding, boudoir, commercial, events
      subject_type    — landscape, solo portrait, couple, group, product
      tag             — case-insensitive substring match against pass3 tags
      min_nima        — minimum nima_composite score
      min_grid_fit    — minimum grid_fit_score
      exclude_scheduled — drop images already on the calendar
      exclude_posted    — drop images already posted to IG

    Sorts:
      grid_fit  — best aesthetic fit first (default)
      nima      — best technical quality first
      random    — randomized
      recent    — most recently captured first
    """
    if limit > 10000:
        limit = 10000
    where = ["content_ready = 1"]
    params: list = []
    if genre:
        where.append("genre = ?")
        params.append(genre)
    if subject_type:
        where.append("subject_type = ?")
        params.append(subject_type)
    if tag:
        where.append("LOWER(tags) LIKE ?")
        params.append(f"%{tag.lower()}%")
    if min_nima > 0:
        where.append("nima_composite >= ?")
        params.append(min_nima)
    if min_grid_fit > 0:
        where.append("grid_fit_score >= ?")
        params.append(min_grid_fit)
    if exclude_posted:
        where.append("(posted_at IS NULL)")
    if exclude_scheduled:
        where.append("id NOT IN (SELECT image_id FROM calendar_posts WHERE image_id IS NOT NULL AND status != 'posted')")

    # Universal ordering: edits (JPG / PNG / TIFF / HEIC / WebP) appear before
    # RAWs in every sort. RAWs aren't post-ready — user has to export them
    # first — so showing the edits at top matches the actual posting workflow.
    # is_raw = 1 for RAW formats, 0 for edit formats; we ORDER BY is_raw ASC
    # so 0 (edit) comes before 1 (raw) within each sort tier.
    is_raw_expr = """
        CASE WHEN
            LOWER(file_path) LIKE '%.arw' OR LOWER(file_path) LIKE '%.cr2' OR
            LOWER(file_path) LIKE '%.cr3' OR LOWER(file_path) LIKE '%.dng' OR
            LOWER(file_path) LIKE '%.nef' OR LOWER(file_path) LIKE '%.raf' OR
            LOWER(file_path) LIKE '%.orf' OR LOWER(file_path) LIKE '%.rw2' OR
            LOWER(file_path) LIKE '%.pef' OR LOWER(file_path) LIKE '%.srw' OR
            LOWER(file_path) LIKE '%.rwl' OR LOWER(file_path) LIKE '%.srf'
        THEN 1 ELSE 0 END
    """.strip()

    sort_inner = {
        "grid_fit": "COALESCE(grid_fit_score, 0) DESC, COALESCE(nima_composite, 0) DESC",
        "nima":     "COALESCE(nima_composite, 0) DESC, COALESCE(grid_fit_score, 0) DESC",
        "random":   "RANDOM()",
        "recent":   "captured_at DESC, id DESC",
    }.get(sort, "COALESCE(grid_fit_score, 0) DESC")
    sort_sql = f"ORDER BY {is_raw_expr} ASC, {sort_inner}"

    sql = f"""
        SELECT id, file_name, file_path, genre, subject_type, mood, setting,
               tags, caption_draft, pixieset_url,
               nima_composite, grid_fit_score, quality_score, print_score,
               posted_at, captured_at,
               COALESCE(manual_added, 0) AS manual_added,
               (user_context IS NOT NULL AND user_context != '') AS has_user_context,
               ({is_raw_expr}) AS is_raw,
               (id IN (SELECT image_id FROM calendar_posts
                       WHERE image_id IS NOT NULL AND status != 'posted')) AS scheduled
        FROM images
        WHERE {' AND '.join(where)}
        {sort_sql}
        LIMIT ?
    """
    params.append(limit)

    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        # also surface total count of matches without limit for the UI
        count_sql = f"SELECT COUNT(*) FROM images WHERE {' AND '.join(where)}"
        total = conn.execute(count_sql, params[:-1]).fetchone()[0]

    return {"count": len(rows), "total": total, "images": rows}


@router.get("/candidates")
def get_candidates(
    genres: Optional[str] = None,
    sort: str = "ranked",
    limit: int = 30,
    offset: int = 0,
):
    """
    Return candidate images for calendar slot filling.
    sort: 'ranked' (grid_fit_score/nima), 'unposted' (all content_ready), 'never_scheduled'
    genres: comma-separated list, defaults to nature+landscape
    """
    genre_list = [g.strip() for g in genres.split(",")] if genres else ["nature", "landscape"]
    placeholders = ",".join("?" * len(genre_list))

    score_expr = """COALESCE(
        grid_fit_score,
        COALESCE(nima_composite, 0) * 0.6 + COALESCE(quality_score, 0) * 0.4
    )"""

    base = f"""
        SELECT id, file_name, file_path, genre, mood,
               grid_fit_score, nima_composite, quality_score,
               content_ready, posted_at, social_queue
        FROM images
        WHERE content_ready = TRUE
          AND posted_at IS NULL
          AND genre IN ({placeholders})
    """

    if sort == "ranked":
        where = "AND social_queue = TRUE"
        order = f"ORDER BY {score_expr} DESC"
    elif sort == "never_scheduled":
        where = "AND id NOT IN (SELECT image_id FROM calendar_posts WHERE image_id IS NOT NULL)"
        order = f"ORDER BY {score_expr} DESC"
    else:  # unposted
        where = ""
        order = f"ORDER BY {score_expr} DESC"

    count_sql = f"SELECT COUNT(*) FROM images WHERE content_ready = TRUE AND posted_at IS NULL AND genre IN ({placeholders}) {where}"
    query = f"{base} {where} {order} LIMIT ? OFFSET ?"

    with get_db() as conn:
        total = conn.execute(count_sql, genre_list).fetchone()[0]
        rows = conn.execute(query, genre_list + [limit, offset]).fetchall()

    return {
        "images": [dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


class ImageSwapRequest(BaseModel):
    image_id: int


@router.patch("/calendar/{post_id}/image")
def swap_calendar_post_image(post_id: int, req: ImageSwapRequest):
    """Swap the image on a calendar post. Clears stale caption."""
    with get_db() as conn:
        post = conn.execute(
            "SELECT id, status FROM calendar_posts WHERE id = ?", (post_id,)
        ).fetchone()
        if not post:
            raise HTTPException(status_code=404, detail=f"Post {post_id} not found")
        if post["status"] == "posted":
            raise HTTPException(status_code=400, detail="Cannot swap image on an already-posted post")

        img = conn.execute(
            "SELECT id, genre FROM images WHERE id = ? AND content_ready = TRUE",
            (req.image_id,)
        ).fetchone()
        if not img:
            raise HTTPException(status_code=404, detail=f"Image {req.image_id} not found or not content-ready")

        conn.execute(
            "UPDATE calendar_posts SET image_id = ?, genre = ? WHERE id = ?",
            (req.image_id, img["genre"], post_id),
        )
    return {"status": "swapped", "post_id": post_id, "image_id": req.image_id}


# ── Mode Control ─────────────────────────────────────────────────────────────

@router.get("/mode")
def mode_status():
    """Return current operating mode: off, text, auto, or priority."""
    mode = get_mode()
    return {
        "mode": mode,
        "text_model": settings.text_model,
        "vision_model": settings.vision_model,
        "description": {
            "off": "All models unloaded. Pipeline paused. RAM free.",
            "text": f"{settings.text_model} loaded for captions/poems. Pipeline paused.",
            "auto": f"{settings.vision_model} loaded. Pipeline running pass3 tagging.",
            "priority": "Priority processing active. Rush-processing selected folder.",
        }.get(mode, "Unknown"),
    }


@router.post("/mode/{mode}")
async def set_mode(mode: str):
    """Switch operating mode: off, text, auto, or priority."""
    if mode not in ("off", "text", "auto", "priority"):
        raise HTTPException(status_code=400, detail="Mode must be 'off', 'text', 'auto', or 'priority'")
    result = await ollama.switch_mode(mode)
    return {
        **result,
        "text_model": settings.text_model,
        "vision_model": settings.vision_model,
    }


# ── Retag Queue ───────────────────────────────────────────────────────────────

class RetagFlagRequest(BaseModel):
    note: Optional[str] = None


@router.patch("/images/{image_id}/retag")
def flag_image_for_retag(image_id: int, req: RetagFlagRequest = RetagFlagRequest()):
    """Flag an image as mis-tagged. Removes from social queue until re-evaluated."""
    try:
        return retag_svc.flag_for_retag(image_id, note=req.note)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/images/{image_id}/retag")
def unflag_image_retag(image_id: int):
    """Remove the retag flag without re-processing."""
    return retag_svc.unflag_retag(image_id)


class ManualGenreRequest(BaseModel):
    genre: str


@router.patch("/images/{image_id}/genre")
def set_image_genre(image_id: int, req: ManualGenreRequest):
    """Manually set an image's genre. Clears retag flag, updates calendar posts."""
    _VALID_GENRES = {"wedding", "portrait", "boudoir", "commercial", "events", "nature", "landscape"}
    if req.genre not in _VALID_GENRES:
        raise HTTPException(status_code=400, detail=f"Invalid genre. Must be one of: {', '.join(sorted(_VALID_GENRES))}")

    with get_db() as conn:
        img = conn.execute("SELECT id, genre FROM images WHERE id = ?", (image_id,)).fetchone()
        if not img:
            raise HTTPException(status_code=404, detail=f"Image {image_id} not found")

        old_genre = img["genre"]
        conn.execute(
            """UPDATE images
               SET genre = ?, retag_queued = FALSE, retag_note = NULL
               WHERE id = ?""",
            (req.genre, image_id),
        )

        # Update any calendar posts using this image
        conn.execute(
            "UPDATE calendar_posts SET genre = ? WHERE image_id = ? AND status != 'posted'",
            (req.genre, image_id),
        )

        # Calendar posts are genre-agnostic: the genre change relabels the post
        # (above) but never removes it. Previously any non-nature/landscape image
        # was auto-dropped from the calendar, which broke scheduling other content.
        removed = 0

    return {
        "image_id": image_id,
        "old_genre": old_genre,
        "new_genre": req.genre,
        "calendar_posts_removed": removed,
    }


@router.get("/retag-queue")
def get_retag_queue():
    """List all images currently flagged for retagging."""
    items = retag_svc.get_retag_queue()
    return {"count": len(items), "images": items}


