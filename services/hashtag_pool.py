"""
services/hashtag_pool.py

Deterministic hashtag assembly. Replaces in-prompt hashtag generation —
the 32b text model used to spend 30% of its output budget guessing tags.
Now we look them up in O(1) and merge with image-specific tags from pass3.

Usage:
    from services.hashtag_pool import build_hashtags
    tags = build_hashtags(genre="nature", subject_type="landscape",
                          mood="serene", pass3_tags=["golden hour", "river"],
                          target_count=22)

Editable: tweak the dicts below to refine the brand voice.
"""

from __future__ import annotations

import json
from typing import Iterable

# Core brand identity — appears on every post.
BRAND_TAGS = [
    "MoodyValleyStills",
    "HudsonValleyNY",
    "HudsonValleyPhotographer",
]

# Generic photography reach tags — broad audience, every post.
REACH_TAGS = [
    "Photography",
    "PhotoOfTheDay",
    "FineArtPhotography",
]

# Per-genre core set. Picked for engagement, not just volume.
GENRE_TAGS: dict[str, list[str]] = {
    "nature": [
        "NaturePhotography", "LandscapePhotography", "NatureLovers",
        "EarthFocus", "OutdoorPhotography", "NaturalLight",
        "WildernessCulture", "RoamThePlanet", "ArtOfVisuals",
    ],
    "wedding": [
        "WeddingPhotography", "HudsonValleyWedding", "WeddingPhotographer",
        "BrideAndGroom", "WeddingDay", "WeddingInspiration",
        "RealWedding", "WeddingMoments", "LoveStory",
    ],
    "portrait": [
        "PortraitPhotography", "PortraitMood", "PortraitPage",
        "PortraitGames", "FacesOfTheWorld", "Portraiture",
        "EnvironmentalPortrait", "AuthenticPortrait",
    ],
    "boudoir": [
        "BoudoirPhotography", "BoudoirInspiration", "EmpoweredWomen",
        "SelfLoveJourney", "BodyPositive", "FineArtBoudoir",
        "ConfidenceShoot",
    ],
    "events": [
        "EventPhotography", "ConcertPhotography", "LivePerformance",
        "BehindTheLens", "StagePhotography", "PerformanceArt",
        "HudsonValleyEvents",
    ],
    "commercial": [
        "CommercialPhotography", "BrandPhotography", "ProductPhotography",
        "SmallBusinessPhotography", "ContentCreation",
    ],
}

# Mood-specific colour. Mostly atmospheric tags.
MOOD_TAGS: dict[str, list[str]] = {
    "serene":     ["StillnessInNature", "QuietMoments", "Tranquility"],
    "dramatic":   ["DramaticLight", "MoodyTones", "ShadowPlay"],
    "romantic":   ["RomanticMood", "LoveInTheLens", "TenderMoments"],
    "playful":    ["JoyfulMoments", "CandidPhotography", "AuthenticJoy"],
    "moody":      ["MoodyPhotography", "DarkAndMoody", "MoodyGrams"],
    "ethereal":   ["EtherealLight", "DreamyPhotography", "SoftLight"],
    "vibrant":    ["VibrantColors", "ColorfulWorld", "BoldColor"],
    "intimate":   ["IntimatePortrait", "QuietIntimacy"],
    "natural":    ["AuthenticMoments", "RealLife"],
    "contemplative": ["ContemplativeMood", "Solitude"],
}

# Lighting / time-of-day flavor.
LIGHTING_TAGS: dict[str, list[str]] = {
    "golden hour":   ["GoldenHour", "GoldenHourPhotography", "MagicHour"],
    "blue hour":     ["BlueHour", "TwilightPhotography"],
    "overcast":      ["OvercastLight", "SoftDaylight"],
    "studio strobe": ["StudioPortrait", "StudioLighting"],
    "window light":  ["WindowLight", "NaturalWindowLight"],
    "harsh midday":  ["HighContrastPhotography"],
    "natural light": ["NaturalLightPhotography"],
}

# Subject-type flavor — adds specificity.
SUBJECT_TAGS: dict[str, list[str]] = {
    "landscape":     ["LandscapeLovers", "LandscapesOfTheWorld"],
    "couple":        ["CouplePhotography", "EngagementShoot"],
    "solo portrait": ["SoloPortrait"],
    "group":         ["GroupPortrait"],
    "performer":     ["PerformerLife"],
    "product":       ["ProductShoot"],
}


def _slugify_tag(raw: str) -> str | None:
    """Convert a free-text tag like 'oak tree' or 'mother-son' into '#OakTree' / '#MotherSon'.
    Returns None if unusable (too short, all digits, etc.).
    Hyphens, underscores, and slashes are treated as word separators so camelcase preserves.
    """
    if not raw or not isinstance(raw, str):
        return None
    # Replace separators with spaces before stripping non-alnum so word boundaries survive.
    normalized = raw.strip()
    for sep in ("-", "_", "/", "\\"):
        normalized = normalized.replace(sep, " ")
    cleaned = "".join(c for c in normalized if c.isalnum() or c.isspace())
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return None
    slug = "".join(p[:1].upper() + p[1:].lower() for p in parts)
    if len(slug) < 3 or slug.isdigit():
        return None
    return slug


def _parse_pass3_tags(tags_field: str | list | None) -> list[str]:
    """Pass3 stores tags as JSON array string. Parse and slugify."""
    if not tags_field:
        return []
    if isinstance(tags_field, list):
        raw_list = tags_field
    else:
        try:
            raw_list = json.loads(tags_field)
            if not isinstance(raw_list, list):
                return []
        except (json.JSONDecodeError, TypeError):
            return []
    out: list[str] = []
    for t in raw_list:
        slug = _slugify_tag(str(t))
        if slug:
            out.append(slug)
    return out


def build_hashtags(
    genre: str | None,
    subject_type: str | None = None,
    mood: str | None = None,
    lighting: str | None = None,
    pass3_tags: str | list | None = None,
    target_count: int = 22,
) -> list[str]:
    """Assemble a deterministic hashtag list for an Instagram post.

    Order of inclusion (each appended only if not already present, capped at target_count):
      1. Brand tags (always)
      2. Genre tags
      3. Mood tags
      4. Lighting tags
      5. Subject tags
      6. Image-specific pass3 tags (slugified)
      7. Reach tags (filler)

    Returns a list of strings WITH leading '#' so callers can splice directly.
    """
    seen: set[str] = set()
    out: list[str] = []

    def add(tag: str) -> None:
        key = tag.lower()
        if key in seen or len(out) >= target_count:
            return
        seen.add(key)
        out.append(f"#{tag}")

    for t in BRAND_TAGS:
        add(t)

    if genre:
        for t in GENRE_TAGS.get(genre.lower(), []):
            add(t)

    if mood:
        for t in MOOD_TAGS.get(mood.lower(), []):
            add(t)

    if lighting:
        for t in LIGHTING_TAGS.get(lighting.lower(), []):
            add(t)

    if subject_type:
        for t in SUBJECT_TAGS.get(subject_type.lower(), []):
            add(t)

    for t in _parse_pass3_tags(pass3_tags):
        add(t)

    for t in REACH_TAGS:
        add(t)

    return out
