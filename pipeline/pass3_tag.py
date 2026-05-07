"""
Pass 3 — Vision tagging via Ollama qwen2.5vl:7b.
3 parallel asyncio workers. Writes structured JSON to images table.
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.config import settings
from core.database import get_db
from core.ollama import ollama
from pipeline.preprocessor import preprocess

_WORKERS = 3

_TAG_PROMPT = """Analyze this photograph and respond with ONLY a valid JSON object.
No explanation, no markdown, no code fences. Just the JSON.

{
  "genre": one of: wedding | portrait | boudoir | commercial | events | nature,
  "mood": string (e.g. "romantic", "playful", "dramatic", "serene"),
  "lighting": string (e.g. "golden hour", "overcast", "studio strobe", "window light"),
  "subject_type": string (e.g. "couple", "solo portrait", "group", "landscape", "product"),
  "faces_present": boolean,
  "face_count": integer,
  "color_palette": string (e.g. "warm earth tones", "cool blues", "high contrast B&W"),
  "setting": string (e.g. "outdoor forest", "urban street", "indoor studio", "beach"),
  "quality_score": float 0.0–10.0 (overall image quality as a photographer would judge),
  "portfolio_worthy": boolean (would you proudly show this in a professional portfolio?),
  "content_ready": boolean (is this image good enough to post on social media as-is?),
  "tags": array of strings (5–10 descriptive tags),
  "description": string (2-3 sentences describing this photo as a photographer would — what makes it special, the emotion, the moment),
  "composition": string (dominant compositional technique, e.g. "rule of thirds", "leading lines", "negative space", "symmetry", "foreground framing"),
  "subjects": array of strings (specific named things visible — animals, flowers, landmarks, objects, e.g. ["oak tree", "spider web", "wedding veil", "tattoo sleeve"]),
  "print_notes": string or null (if this image would make an exceptional print, explain why in one sentence — otherwise null),
  "technical_issues": string or null (any technical problems visible — motion blur, chromatic aberration, noise, blown highlights, etc. — otherwise null),
  "emotional_impact": string (one sentence on the emotional response this image evokes in the viewer),

  // Caption-fuel fields — these turn pass3 metadata into directly usable
  // material for the 32b text caption generator. Keep them tight and specific.
  "narrative_hook": string (ONE sentence that captures the story-in-a-line of this image. Not a description — a story seed. Example: "A solitary performer reaches into the spotlight as the audience disappears into shadow."),
  "caption_seed_phrases": array of 2-3 strings (evocative fragments a writer could anchor prose around. Example: ["hush of the second balcony", "weight of waiting", "spotlight as a held breath"]),
  "recommended_caption_tone": one of: observational | lyrical | declarative | confessional | journalistic,
  "recommended_pillar": one of: portfolio | personality | transformation | behind_scenes | storytelling,
  "dominant_visual_element": string (what the eye lands on first — name it specifically, e.g. "the diagonal slash of red across the shoulder", "the empty chair in the foreground"),
  "viewer_emotion_target": string (what the viewer should FEEL when they see this — distinct from the image's own mood. Example: "longing", "the pull to slow down", "complicit joy")
}"""


_PER_FILE_TIMEOUT = 600  # 10 min max per image


async def _tag_single(image_path: Path, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        try:
            prep_path = preprocess(image_path)
            # Bumped num_predict 512 -> 768 to fit the new caption-fuel fields
            # (narrative_hook + seed phrases + tone + pillar + dominant + emotion target
            # add ~150-200 tokens of output).
            result = await asyncio.wait_for(
                ollama.vision_json(prep_path, _TAG_PROMPT, num_predict=768),
                timeout=_PER_FILE_TIMEOUT,
            )

            tags_json          = json.dumps(result.get("tags", []))
            subjects_json      = json.dumps(result.get("subjects", []))
            seed_phrases_json  = json.dumps(result.get("caption_seed_phrases", []))
            color_palette      = result.get("color_palette", "")

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
                       pass3_at = ?, pass3_model = ?
                       WHERE file_path = ?""",
                    (
                        result.get("genre"),
                        result.get("mood"),
                        result.get("lighting"),
                        result.get("subject_type"),
                        result.get("faces_present", False),
                        result.get("face_count", 0),
                        color_palette,
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
                        datetime.utcnow().isoformat(),
                        settings.vision_model,
                        str(image_path),
                    ),
                )

            return {"file_path": str(image_path), "status": "tagged", **result}

        except asyncio.TimeoutError:
            return {"file_path": str(image_path), "status": "error", "error": f"timeout ({_PER_FILE_TIMEOUT}s)"}
        except Exception as e:
            return {"file_path": str(image_path), "status": "error", "error": str(e)}


async def process_batch_async(image_paths: list[Path]) -> list[dict]:
    semaphore = asyncio.Semaphore(_WORKERS)
    tasks = [_tag_single(path, semaphore) for path in image_paths]
    return await asyncio.gather(*tasks)


def process_batch(image_paths: list[Path]) -> list[dict]:
    return asyncio.run(process_batch_async(image_paths))


def get_eligible_images(limit: int = 500) -> list[Path]:
    """Images ready for pass3: not yet tagged, OR tagged by 7b (missing description)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT file_path FROM images
               WHERE pass1_status = 'pass' AND pass2_at IS NOT NULL
               AND (pass3_at IS NULL OR description IS NULL)
               ORDER BY nima_composite DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [Path(r["file_path"]) for r in rows]
