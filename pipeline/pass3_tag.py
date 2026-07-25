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
from lens_core.tz import now_et

_WORKERS = 3

_TAG_PROMPT = """You are a working photographer reviewing your own image for portfolio
+ social use. Look at it the way you would in front of a print: what is actually
in the frame, what light is doing, where the eye lands, what the image is about.

Respond with ONLY a valid JSON object — no explanation, no markdown, no code fences.

{
  "genre": one of: wedding | portrait | boudoir | commercial | events | nature,
  "mood": string. concrete + specific (e.g. "humid afternoon stillness", "post-storm relief"). avoid "serene", "peaceful", "moody".
  "lighting": string. name the light source AND its direction (e.g. "low east sun, raked across stone", "overcast, soft from camera-left", "single window, warm, behind subject").
  "subject_type": string (e.g. "couple", "solo portrait", "group", "landscape", "product"),
  "faces_present": boolean,
  "face_count": integer,
  "color_palette": string. 1-3 words (e.g. "amber + char", "wet slate + moss", "high-key on white"). no "warm earth tones".
  "setting": string. specific (e.g. "north-facing dunes, late afternoon", "second-floor walkup kitchen", "limestone cliff face") — not "outdoors" or "indoors".
  "quality_score": float 0.0–10.0,
  "portfolio_worthy": boolean,
  "content_ready": boolean,
  "tags": array of 6-10 strings. concrete nouns + materials + textures, no clichés.
  "subjects": array of strings (specific named things visible — animals, flowers, landmarks, objects),
  "description": string. 2-3 sentences. what is in the frame. specific, sensory, no fluff. tell me what you see, not what you feel about it.
  "composition": string. one sentence on framing + light direction + depth (e.g. "centered subject, light raking from left, foreground out of focus, distant ridge anchors the bottom third").
  "print_notes": string or null. if this would make an exceptional print, ONE specific reason — otherwise null.
  "technical_issues": string or null. only if visible — motion blur, chromatic aberration, blown highlights, noise. otherwise null.
  "emotional_impact": string. one sentence. what the viewer feels.

  // Caption-fuel fields — these are what the writer pulls from. Keep them
  // tight, specific, image-grounded. ABSOLUTELY NO "stillness", "pause",
  // "embrace", "moment of", "captures the essence of". Concrete, not abstract.
  "narrative_hook": string. ONE short evocative line, under 12 words. concrete noun + concrete verb. NOT a feeling-word; a thing-doing-something. Example: "Cold rain hammered the slate while the cat watched from the eaves."
  "caption_seed_phrases": array of 3-5 strings, each 3-7 words. sensory phrases the writer can anchor prose around. NOT abstract. Example: ["wet glint on the stone", "sky going to bruise", "wind that won't sit still"].
  "texture_vocabulary": array of 3-5 single-word texture words observed in the image. concrete and image-specific. Example: ["char", "glass", "gravel", "wool", "smoke"].
  "verb_seeds": array of 3-5 active verbs/gerunds the writer can use as the spine of the sentence. NOT generic ("being", "having"). Do NOT use "spill"/"spilling". Example: ["raking", "leaning into", "cresting", "splitting", "guttering"].
  "visual_tension": string. ONE short phrase naming the productive contradiction in the frame — what makes the image refuse to be flat. Example: "warm light, cold ground" or "stillness mid-action".
  "recommended_caption_tone": one of: observational | lyrical | declarative | confessional | journalistic,
  "recommended_pillar": one of: portfolio | personality | transformation | behind_scenes | storytelling,
  "dominant_visual_element": string. what the eye lands on first — name it specifically (e.g. "the diagonal slash of red across the shoulder", "the empty chair in the foreground").
  "viewer_emotion_target": string. what the viewer should FEEL — distinct from the image's mood. concrete (e.g. "the pull to drive home faster", "the urge to put a hand on the wall").
}

Be specific. Avoid: "stillness", "pause", "moment of", "embrace", "captures the
essence of", "serene", "peaceful", "timeless"."""


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
            textures_json      = json.dumps(result.get("texture_vocabulary", []))
            verbs_json         = json.dumps(result.get("verb_seeds", []))
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
                       texture_vocabulary = ?, verb_seeds = ?, visual_tension = ?,
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
                        textures_json,
                        verbs_json,
                        result.get("visual_tension"),
                        now_et().isoformat(),
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
