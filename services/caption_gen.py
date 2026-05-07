"""
services/caption_gen.py

Instagram caption + hashtag generator.
- Takes image_id as input
- Reads genre, mood, lighting, subject_type, tags, color_palette, setting from images table
- Calls qwen2.5:14b via core/ollama.py with structured prompt
- Tone varies by genre
- Saves caption_draft back to images table
- Returns caption + hashtag array
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from core.database import get_db
from core.ollama import ollama
from services.hashtag_pool import build_hashtags

# Output token cap for caption-only JSON (caption text + JSON braces, no hashtags).
# A 4-sentence Instagram caption is ~120-160 tokens; 250 is a safe ceiling.
_CAPTION_NUM_PREDICT = 250

# Keep the text model resident for half an hour so batched captions skip cold-load.
_CAPTION_KEEP_ALIVE = "30m"

# How many tags we want per post. Hashtags come from the deterministic pool, not the LLM.
# IG was rejecting posts with more — capped at 5 per user observation 2026-05-05.
_HASHTAG_TARGET_COUNT = 5

# Sampling for caption generation. Higher temperature + a non-default repeat
# penalty break the cadence rut where every caption ended with the same
# "...pause and connect..." closer (user feedback 2026-05-06).
_CAPTION_TEMPERATURE = 1.0
_CAPTION_TOP_P = 0.95
_CAPTION_REPEAT_PENALTY = 1.15

# How many recent captions to feed back as "do not repeat this rhythm".
_RECENCY_VARIETY_LOOKBACK = 5

logger = logging.getLogger("lens.caption_gen")

# GENRE_TONES used to be a verbose per-genre adjective list — "meditative",
# "reverent", "invite the viewer to pause and connect with the landscape" — and
# the model was reading those words and putting them straight into the caption.
# Same caption on every nature post. Now empty: variety comes from the negative
# constraints in the user prompt, not from telling the model how to feel.
GENRE_TONES: dict[str, str] = {}

DEFAULT_TONE = ""

SYSTEM_PROMPTS = {
    "instagram": """You write Instagram captions for a Hudson Valley, NY photographer.

Voice: grounded, specific, observational. Describe what's actually in this
image — the light, the time, the place, the gesture, the texture, the
specific thing in front of the lens. Never generic poetry. Never preachy.

Vary sentence shape across captions. Sometimes a fragment, sometimes a
question, sometimes a single declarative line, sometimes a two-sentence
observation. Captions on this account should not all look the same.

Never close on stillness, pause, breath, embrace, reflection, slowing down,
or invitations to the viewer. Never start with "There's something about".

Respond with valid JSON only — no markdown, no extra text.""",

    "poem": """You are a poet who writes short, evocative poems inspired by photographs.
Your poems are original, vivid, and emotionally resonant — never cliché.
Always respond with valid JSON only — no markdown, no extra text.""",

    "artist_statement": """You are an art curator writing gallery-quality artist statements about photographs.
Your tone is thoughtful, intellectual, and deeply observant.
Always respond with valid JSON only — no markdown, no extra text.""",

    "minimal": """You are a minimalist copywriter for a photography brand.
You write clean, punchy, few-word captions. Less is more.
Always respond with valid JSON only — no markdown, no extra text.""",

    "story": """You are a storyteller who sees narratives within photographs.
You write short, immersive prose that pulls the reader into the scene.
Always respond with valid JSON only — no markdown, no extra text.""",
}


def _parse_tags(tags_raw: str) -> str:
    """Parse tags from JSON array string or comma-separated."""
    if not tags_raw:
        return ""
    if tags_raw.startswith("["):
        try:
            tags_list = json.loads(tags_raw)
            return ", ".join(tags_list) if isinstance(tags_list, list) else tags_raw
        except (json.JSONDecodeError, TypeError):
            return tags_raw
    return tags_raw


# Single source of truth for cliché phrases. Used by:
#   1. _scrub() — removes them from rich-context fields before they're injected
#      into the prompt (they were leaking from the 32b vision narrative_hook).
#   2. The instagram prompt's FORBIDDEN block (rendered from this list).
# Order matters: longer phrases first so they're matched before their substrings.
_FORBIDDEN_PHRASES: list[str] = [
    "invite the viewer to",
    "inviting the viewer to",
    "invite you to",
    "fleeting moments of",
    "fleeting moment",
    "fleeting beauty",
    "in this moment",
    "a moment of",
    "this moment",
    "every moment",
    "every ripple",
    "every glance",
    "every look",
    "stop and ",
    "take a moment to",
    "take a moment",
    "pause and",
    "pause to",
    "pause for",
    "be still",
    "find peace",
    "find yourself",
    "slow down",
    "speak volumes",
    "speaks volumes",
    "tells a story of",
    "embraced by",
    "captured this",
    "captured by",
    "capturing the",
    "capturing a",
    "capturing an",
    "There's something about",
    "There's something undeniable",
    "stillness",
    "pause",
    "embrace",
    "breathe",
    "reflect on",
    "connect with",
    "evoke",
    "evokes",
    "evoking",
]


def _scrub(text: str | None) -> str:
    """Remove forbidden cliché phrases from a text fragment before it's
    injected into the prompt. The 32b vision model writes narrative_hook
    fields like "...inviting the viewer to reflect on the fleeting moments..."
    and the 14b text model would echo those words verbatim.

    Substring removal (case-insensitive). If the result becomes too short or
    empty, return empty string so the caller can omit the line entirely.
    """
    if not text:
        return ""
    out = str(text)
    for phrase in _FORBIDDEN_PHRASES:
        # case-insensitive replace
        idx = 0
        while True:
            pos = out.lower().find(phrase.lower(), idx)
            if pos == -1:
                break
            out = out[:pos] + out[pos + len(phrase):]
            idx = pos
    # Collapse double spaces and trim trailing punctuation/comma artifacts
    out = " ".join(out.split())
    out = out.strip(" ,.;:—-")
    if len(out) < 8:
        return ""
    return out


def _recent_captions_block() -> str:
    """Pull the last N captions actually published or scheduled and feed them
    back as 'do not repeat the rhythm of these'.

    The model otherwise defaults to its own cadence rut. Showing it what it
    just wrote (and explicitly forbidding repetition of structure) is the
    cheapest way to force variation without hand-tuning per image.
    """
    try:
        with get_db() as conn:
            rows = conn.execute(
                """SELECT i.caption_draft
                   FROM calendar_posts cp
                   JOIN images i ON cp.image_id = i.id
                   WHERE cp.status IN ('posted', 'scheduled')
                     AND i.caption_draft IS NOT NULL
                     AND i.caption_draft != ''
                   ORDER BY COALESCE(cp.posted_at, cp.scheduled_at) DESC
                   LIMIT ?""",
                (_RECENCY_VARIETY_LOOKBACK,),
            ).fetchall()
    except Exception:
        return ""

    captions: list[str] = []
    for r in rows:
        raw = r["caption_draft"] or ""
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
            cap = parsed.get("caption") if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            cap = raw
        if cap:
            captions.append(cap.strip())

    if not captions:
        return ""

    bullets = "\n".join(f"  • {c}" for c in captions)
    return f"""

Recent captions on this account (do NOT repeat their cadence, length, or closing
move — your caption should feel different from each of these):
{bullets}"""


def _image_context(image: dict) -> str:
    """Build a lean context block from pass3 metadata.

    Tier-2 prompt diet: only fields that materially help prose-writing are included.
    Dropped from the prompt: color_palette, setting, composition, subjects, full
    description (each is either redundant with mood/genre or already implicit).
    Reduces input prompt from ~1000 tokens to ~250 tokens — prefill drops from
    ~10s to ~2s on the 32b text model.

    When pass3 has produced rich caption-fuel fields (32b retag), they take over
    via _rich_context(); see _build_prompt() for the dispatch.
    """
    genre = image.get("genre") or "portrait"
    mood = image.get("mood") or "natural"
    subject_type = image.get("subject_type") or "subject"
    lighting = image.get("lighting") or "natural light"
    emotional_impact = image.get("emotional_impact") or ""

    # Top 5 tags only, comma-joined.
    tags_raw = image.get("tags") or ""
    top_tags = ""
    if tags_raw:
        try:
            tag_list = json.loads(tags_raw) if tags_raw.startswith("[") else [t.strip() for t in tags_raw.split(",")]
            if isinstance(tag_list, list):
                top_tags = ", ".join(str(t) for t in tag_list[:5])
        except (json.JSONDecodeError, TypeError):
            top_tags = tags_raw

    ctx = f"""Image details:
- Genre: {genre}
- Mood: {mood}
- Subject: {subject_type}
- Lighting: {lighting}"""
    if top_tags:
        ctx += f"\n- Key elements: {top_tags}"
    if emotional_impact:
        ctx += f"\n- Emotional impact: {emotional_impact}"

    return ctx


def _rich_context(image: dict) -> str | None:
    """If pass3 was run with the 32b retag schema (narrative_hook etc), use the
    facts it extracted as raw material — but explicitly tell the model NOT to
    echo the phrasing.

    Two things changed here vs. the original 2026-05-05 version (user feedback
    2026-05-06: "always follows the same cadence"):
      • Removed the `Recommended tone: lyrical` line — it pushed the model
        toward flowery prose every time.
      • Re-labelled `narrative_hook` as raw material to paraphrase, not as
        a sentence to copy. The 32b vision tends to write hooks like
        "inviting the viewer to reflect on..." which the 14b would just echo.

    These fields are written only by the deeper vision pass. If absent, return
    None and let _image_context() fall back to the lean view.
    """
    hook_raw = image.get("narrative_hook")
    if not hook_raw:
        return None

    # Scrub each rich-context field of forbidden cliché phrases before the
    # prompt is built. The 32b vision model often writes hooks like
    # "...inviting the viewer to reflect on the fleeting moments..." — leaving
    # those words in the prompt gives the 14b license to echo them.
    hook = _scrub(hook_raw)
    dominant = _scrub(image.get("dominant_visual_element"))
    emotion_target = _scrub(image.get("viewer_emotion_target"))
    genre = image.get("genre") or "portrait"
    mood = image.get("mood") or "natural"

    # Parse and scrub seed phrases (each phrase scrubbed individually so the
    # whole array isn't lost when one phrase contains "stillness").
    seed_raw = image.get("caption_seed_phrases") or ""
    phrases_list: list[str] = []
    try:
        if seed_raw.startswith("["):
            arr = json.loads(seed_raw)
            if isinstance(arr, list):
                phrases_list = [str(p) for p in arr]
        elif seed_raw:
            phrases_list = [seed_raw]
    except (json.JSONDecodeError, TypeError):
        phrases_list = [seed_raw] if seed_raw else []
    phrases_list = [s for s in (_scrub(p) for p in phrases_list) if s]
    phrases = " | ".join(phrases_list[:3])

    # If after scrubbing the hook is empty, fall back to lean context — better
    # to show no narrative seed than a stripped, garbled fragment.
    if not hook:
        return None

    ctx = f"""Image facts (raw material — do NOT echo this phrasing, paraphrase only):
- One-line scene summary: {hook}
- Genre: {genre} | Mood: {mood}"""
    if dominant:
        ctx += f"\n- Eye lands on first: {dominant}"
    if emotion_target:
        ctx += f"\n- Image evokes (a fact, not a directive): {emotion_target}"
    if phrases:
        ctx += f"\n- Sense words present in the scene: {phrases}"

    return ctx


def _user_context_block(image: dict) -> str:
    """Inject the photographer's free-form notes as factual assertions the
    model should weave in. NOT scrubbed — user has full control over their
    own words. If empty, returns empty string (nothing added to prompt).
    """
    notes = (image.get("user_context") or "").strip()
    if not notes:
        return ""
    # Don't scrub — these are the user's words, not LLM-generated cliché.
    return f"""

Photographer notes (facts the camera couldn't see — incorporate as truths,
do NOT echo verbatim):
{notes}"""


def _build_prompt(image: dict, style: str = "instagram") -> str:
    """Build the user-side prompt.

    Hashtags are NOT requested from the model anymore — they're assembled
    deterministically from a taxonomy after the caption returns. The model's
    only job is the prose.

    If pass3 wrote the rich caption-fuel fields (32b retag), use them as the
    seed; otherwise fall back to the lean context.

    `user_context` (photographer's free-form notes) is appended to the context
    block when present. Applies to all caption styles.
    """
    genre = image.get("genre") or "portrait"
    ctx = (_rich_context(image) or _image_context(image)) + _user_context_block(image)

    if style == "poem":
        return f"""Write a short poem (4–12 lines) inspired by this {genre} photograph.

{ctx}

Requirements:
- The poem should feel original, vivid, and emotionally connected to what's in the image.
- Use imagery, metaphor, and sensory language. No rhyming unless it feels natural.
- Do NOT mention "photograph" or "camera" — write as if experiencing the scene directly.

Respond with this exact JSON structure:
{{
  "caption": "the full poem text"
}}"""

    elif style == "artist_statement":
        return f"""Write a gallery-style artist statement (3–5 sentences) about this {genre} photograph.

{ctx}

Requirements:
- Discuss the artistic intent, what draws the eye, what the image evokes.
- Reference composition, light, or mood as an art critic would.
- Thoughtful and intellectual but accessible — not pretentious.

Respond with this exact JSON structure:
{{
  "caption": "the artist statement"
}}"""

    elif style == "minimal":
        return f"""Write a minimal caption (1–2 short lines max) for this {genre} photograph.

{ctx}

Requirements:
- Ultra-brief. A phrase, a feeling, a moment. Think poetry, not prose.
- No calls to action. No questions. Just the essence.

Respond with this exact JSON structure:
{{
  "caption": "the minimal caption"
}}"""

    elif style == "story":
        return f"""Write a short narrative paragraph (4–6 sentences) that tells the story within or behind this {genre} photograph.

{ctx}

Requirements:
- Immersive, sensory storytelling. Pull the reader into the scene.
- Write as if narrating a moment — what happened before, during, or after.
- Evocative and human. Make the viewer feel present.

Respond with this exact JSON structure:
{{
  "caption": "the narrative paragraph"
}}"""

    else:  # instagram (default)
        recent = _recent_captions_block()
        # Render the FORBIDDEN block from the canonical list so adding a new
        # ban-word in one place reaches both the prompt and the rich-context
        # scrubber. Bullet-formatted for the model's attention.
        forbidden_block = "  • " + "\n  • ".join(f'"{p}"' for p in _FORBIDDEN_PHRASES)
        return f"""Write an Instagram caption for this {genre} photograph.

{ctx}{recent}

Length: 1–3 sentences. Fragments and incomplete sentences are allowed and
encouraged. A single declarative line works. A direct question works. Do not
always follow the same shape.

FORBIDDEN PHRASES — these are clichés the model defaults to. Do not use any
of them, and do not use near-synonyms or stems of them. Read this list before
writing and re-read it after writing. If your draft contains any item from
this list, rewrite it.
{forbidden_block}

Write what's in front of the camera. Specific time, specific light, specific
gesture, specific object. Skip closing calls to action and skip "invitations".

Examples of acceptable shapes (illustrative — DO NOT copy phrasing, just
notice the structural variety):
  • Fragment: "Sunset, second balcony."
  • Specific observation: "The light at 6:47 PM, after the rain, is unreasonable."
  • Direct question: "What do you do with a sky like this?"
  • Two-sentence: "Three takes to get her laugh. The one that landed wasn't the one I planned for."

Do NOT include hashtags — they are added separately. Just write the caption prose.

Respond with this exact JSON structure:
{{
  "caption": "..."
}}"""


async def generate_caption(image_id: int, style: str = "instagram") -> dict:
    """
    Generate a caption for the given image_id in the requested style.

    Tier 1: server-side JSON-format constrained decoding (`format: "json"`),
    output capped at _CAPTION_NUM_PREDICT tokens, keep_alive=30m so the 32b
    model stays resident across batched calls.

    Tier 2: prompt is lean — only mood/genre/subject/lighting/top-tags/emotion.
    Hashtags are NOT requested from the model — they're assembled
    deterministically from services.hashtag_pool after the prose returns.

    When pass3 has been run with the 32b retag schema (narrative_hook etc.),
    those richer fields take over via _rich_context().

    Saves the result to images.caption_draft.
    Returns: {"image_id": int, "caption": str, "hashtags": list[str], "style": str}
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, genre, mood, lighting, subject_type, tags,
                      color_palette, setting, file_name, file_path, caption_draft,
                      description, composition, subjects, emotional_impact, print_notes,
                      narrative_hook, caption_seed_phrases, recommended_caption_tone,
                      recommended_pillar, dominant_visual_element, viewer_emotion_target,
                      user_context
               FROM images WHERE id = ?""",
            (image_id,),
        ).fetchone()

    if not row:
        raise ValueError(f"Image {image_id} not found")

    image = dict(row)

    prompt = _build_prompt(image, style=style)
    system = SYSTEM_PROMPTS.get(style, SYSTEM_PROMPTS["instagram"])
    logger.info(
        f"[caption] Generating {style} caption for image {image_id} "
        f"({image.get('genre')}, rich={'yes' if image.get('narrative_hook') else 'no'})"
    )

    # text_json() forces format=json — Ollama validates the response server-side.
    # Higher temperature + repeat_penalty break the "...stillness/pause/connect..."
    # cadence rut where every caption ended the same way.
    try:
        result = await ollama.text_json(
            prompt,
            system=system,
            num_predict=_CAPTION_NUM_PREDICT,
            keep_alive=_CAPTION_KEEP_ALIVE,
            temperature=_CAPTION_TEMPERATURE,
            top_p=_CAPTION_TOP_P,
            repeat_penalty=_CAPTION_REPEAT_PENALTY,
        )
    except json.JSONDecodeError as e:
        raise ValueError(f"Caption JSON parse failed despite format=json: {e}")

    caption = (result.get("caption") or "").strip()
    if not caption:
        raise ValueError(f"Empty caption returned from model for image {image_id}")

    # Deterministic hashtag assembly — no LLM call.
    hashtags = build_hashtags(
        genre=image.get("genre"),
        subject_type=image.get("subject_type"),
        mood=image.get("mood"),
        lighting=image.get("lighting"),
        pass3_tags=image.get("tags"),
        target_count=_HASHTAG_TARGET_COUNT,
    )

    # Append Pixieset print link if the image has one
    with get_db() as conn:
        pix_row = conn.execute(
            "SELECT pixieset_url FROM images WHERE id = ?", (image_id,)
        ).fetchone()
    if pix_row and pix_row["pixieset_url"]:
        caption += "\n\n\U0001f5bc Available as a print \u2192 link in bio"  # noqa: emoji + arrow

    # Save caption_draft back to DB as JSON with both parts
    caption_draft = json.dumps({"caption": caption, "hashtags": hashtags})
    with get_db() as conn:
        conn.execute(
            "UPDATE images SET caption_draft = ? WHERE id = ?",
            (caption_draft, image_id),
        )

    return {
        "image_id": image_id,
        "genre": image.get("genre"),
        "caption": caption,
        "hashtags": hashtags,
        "style": style,
    }


async def generate_captions_batch(
    limit: int = 10,
    genre: Optional[str] = None,
) -> list[dict]:
    """
    Generate captions for images that are content_ready but have no caption_draft.
    Returns list of results.
    """
    with get_db() as conn:
        query = """SELECT id FROM images
                   WHERE content_ready = TRUE AND (caption_draft IS NULL OR caption_draft = '')"""
        params: list = []
        if genre:
            query += " AND genre = ?"
            params.append(genre)
        query += " ORDER BY nima_composite DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()

    image_ids = [r["id"] for r in rows]
    results = []
    errors = []

    for image_id in image_ids:
        try:
            result = await generate_caption(image_id)
            results.append(result)
        except Exception as e:
            errors.append({"image_id": image_id, "error": str(e)})

    return {
        "processed": len(results),
        "errors": errors,
        "results": results,
    }
