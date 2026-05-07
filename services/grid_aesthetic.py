"""
services/grid_aesthetic.py

Instagram grid aesthetic analysis — tracks the visible 3x3 grid
and scores how well a candidate image fits the current layout.
No LLM calls — pure database analysis.
"""

from core.database import get_db

# Palette temperature classification keywords
_WARM_KEYWORDS = {"warm", "golden", "amber", "orange", "red", "sunset", "earth", "honey", "copper", "rust"}
_COOL_KEYWORDS = {"cool", "blue", "teal", "silver", "ice", "cold", "ocean", "steel", "slate", "navy"}
_MORNING_MOODS = {"playful", "bold", "energetic", "joyful", "celebratory", "bright", "vibrant", "fun"}
_EVENING_MOODS = {"dramatic", "serene", "ethereal", "moody", "intimate", "romantic", "dreamy", "dark", "meditative"}


def _classify_palette(palette_text: str) -> str:
    """Classify a color_palette string as warm/cool/neutral."""
    if not palette_text:
        return "neutral"
    low = palette_text.lower()
    warm = sum(1 for w in _WARM_KEYWORDS if w in low)
    cool = sum(1 for w in _COOL_KEYWORDS if w in low)
    if warm > cool:
        return "warm"
    elif cool > warm:
        return "cool"
    return "neutral"


def _recommend_slot(mood: str) -> str:
    """Recommend morning or evening based on mood."""
    if not mood:
        return "morning"
    low = mood.lower()
    if low in _EVENING_MOODS or any(m in low for m in _EVENING_MOODS):
        return "evening"
    return "morning"


def evaluate_grid_fit(image_id: int) -> dict:
    """
    Score how well an image fits the current Instagram grid.
    Returns {"score": 0-1.0, "reason": str, "recommended_slot": str, "conflicts": list}
    Also writes grid_fit_score and grid_fit_reason to the images table.
    """
    with get_db() as conn:
        # Get the candidate image
        candidate = conn.execute(
            """SELECT id, genre, mood, color_palette, composition, lighting
               FROM images WHERE id = ?""", (image_id,)
        ).fetchone()
        if not candidate:
            return {"score": 0.0, "reason": "Image not found", "recommended_slot": "morning", "conflicts": []}
        candidate = dict(candidate)

        # Get last 9 posted images (the visible 3x3 grid)
        grid = conn.execute(
            """SELECT i.genre, i.mood, i.color_palette, i.composition, i.lighting
               FROM calendar_posts cp JOIN images i ON cp.image_id = i.id
               WHERE cp.status = 'posted' AND cp.posted_at IS NOT NULL
               ORDER BY cp.posted_at DESC LIMIT 9"""
        ).fetchall()
        grid = [dict(r) for r in grid]

    # If grid is empty, everything fits
    if not grid:
        score = 0.85
        reason = "Empty grid — any image works well as a starter"
        slot = _recommend_slot(candidate.get("mood"))
        with get_db() as conn:
            conn.execute("UPDATE images SET grid_fit_score=?, grid_fit_reason=? WHERE id=?",
                         (score, reason, image_id))
        return {"score": score, "reason": reason, "recommended_slot": slot, "conflicts": []}

    conflicts = []
    scores = {}

    # --- 1. Palette consistency (0.30) ---
    cand_palette = _classify_palette(candidate.get("color_palette"))
    grid_palettes = [_classify_palette(g.get("color_palette")) for g in grid]
    last_palette = grid_palettes[0] if grid_palettes else "neutral"

    # Reward matching the grid's dominant temperature
    from collections import Counter
    palette_counts = Counter(grid_palettes)
    dominant_palette = palette_counts.most_common(1)[0][0] if palette_counts else "neutral"

    if cand_palette == dominant_palette:
        palette_score = 0.9
    elif cand_palette == "neutral":
        palette_score = 0.7  # neutral always okay
    else:
        palette_score = 0.4
        conflicts.append(f"Palette mismatch: image is {cand_palette}, grid is mostly {dominant_palette}")

    # Slight penalty for exact same palette as last post
    if cand_palette == last_palette and cand_palette != "neutral":
        palette_score = max(palette_score - 0.15, 0.3)
    scores["palette"] = palette_score

    # --- 2. Mood variety (0.25) ---
    cand_mood = (candidate.get("mood") or "").lower()
    grid_moods = [(g.get("mood") or "").lower() for g in grid]
    last_mood = grid_moods[0] if grid_moods else ""

    if cand_mood == last_mood and cand_mood:
        mood_score = 0.3
        conflicts.append(f"Same mood as last post: {cand_mood}")
    elif cand_mood in grid_moods[:3]:
        mood_score = 0.6  # appeared in last 3
    else:
        mood_score = 0.95  # fresh mood
    scores["mood"] = mood_score

    # --- 3. Genre balance (0.20) ---
    cand_genre = (candidate.get("genre") or "").lower()
    grid_genres = [(g.get("genre") or "").lower() for g in grid]

    recent_same_genre = sum(1 for g in grid_genres[:3] if g == cand_genre)
    if recent_same_genre >= 2:
        genre_score = 0.3
        conflicts.append(f"Genre '{cand_genre}' appeared {recent_same_genre}x in last 3 posts")
    elif recent_same_genre == 1:
        genre_score = 0.7
    else:
        genre_score = 0.95
    scores["genre"] = genre_score

    # --- 4. Composition diversity (0.15) ---
    cand_comp = (candidate.get("composition") or "").lower()
    last_comp = (grid[0].get("composition") or "").lower() if grid else ""

    if cand_comp and cand_comp == last_comp:
        comp_score = 0.4
    else:
        comp_score = 0.9
    scores["composition"] = comp_score

    # --- 5. Time-of-day recommendation (0.10) ---
    slot = _recommend_slot(candidate.get("mood"))
    tod_score = 0.8  # baseline
    scores["time_of_day"] = tod_score

    # Weighted total
    weights = {"palette": 0.30, "mood": 0.25, "genre": 0.20, "composition": 0.15, "time_of_day": 0.10}
    total = sum(scores[k] * weights[k] for k in weights)
    total = round(total, 3)

    # Build reason
    best = max(scores, key=scores.get)
    worst = min(scores, key=scores.get)
    reason_parts = []
    if total >= 0.75:
        reason_parts.append("Strong grid fit")
    elif total >= 0.6:
        reason_parts.append("Acceptable grid fit")
    else:
        reason_parts.append("Weak grid fit")
    if conflicts:
        reason_parts.append("; ".join(conflicts))
    reason = ". ".join(reason_parts)

    # Save to DB
    with get_db() as conn:
        conn.execute("UPDATE images SET grid_fit_score=?, grid_fit_reason=? WHERE id=?",
                     (total, reason, image_id))

    return {"score": total, "reason": reason, "recommended_slot": slot, "conflicts": conflicts}


def get_grid_snapshot() -> dict:
    """
    Return the current visible 3x3 Instagram grid (last 9 posted images).
    Returns list of images with their metadata, ordered newest-first.
    """
    with get_db() as conn:
        rows = conn.execute(
            """SELECT i.id, i.file_path, i.file_name, i.genre, i.mood,
                      i.grid_fit_score, i.color_palette,
                      cp.post_date, cp.pillar, cp.posted_at
               FROM calendar_posts cp
               JOIN images i ON cp.image_id = i.id
               WHERE cp.status = 'posted' AND cp.posted_at IS NOT NULL
               ORDER BY cp.posted_at DESC
               LIMIT 9""",
        ).fetchall()

    grid = [dict(r) for r in rows]
    genres = {}
    moods = {}
    for img in grid:
        g = img.get("genre") or "unknown"
        genres[g] = genres.get(g, 0) + 1
        m = img.get("mood") or "unknown"
        moods[m] = moods.get(m, 0) + 1

    return {
        "grid": grid,
        "count": len(grid),
        "genre_distribution": genres,
        "mood_distribution": moods,
    }
