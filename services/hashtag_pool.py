"""
services/hashtag_pool.py — LENS-specific hashtag taxonomy.

The engine moved to `lens_core.caption.hashtag_engine` 2026-05-07. This file
now defines the LENS taxonomy data and re-exports `build_hashtags()` so the
existing call sites (`from services.hashtag_pool import build_hashtags`)
keep working unchanged.

Edit the dicts below to refine the LENS brand voice.
"""

from __future__ import annotations

from lens_core.caption.hashtag_engine import (
    HashtagTaxonomy,
    build_hashtags as _build_hashtags,
    parse_pass3_tags,
    slugify_tag,
)

# ── LENS taxonomy ────────────────────────────────────────────────────────────

BRAND_TAGS = [
    "MoodyValleyStills",
    "HudsonValleyNY",
    "HudsonValleyPhotographer",
]

REACH_TAGS = [
    "Photography",
    "PhotoOfTheDay",
    "FineArtPhotography",
]

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

LIGHTING_TAGS: dict[str, list[str]] = {
    "golden hour":   ["GoldenHour", "GoldenHourPhotography", "MagicHour"],
    "blue hour":     ["BlueHour", "TwilightPhotography"],
    "overcast":      ["OvercastLight", "SoftDaylight"],
    "studio strobe": ["StudioPortrait", "StudioLighting"],
    "window light":  ["WindowLight", "NaturalWindowLight"],
    "harsh midday":  ["HighContrastPhotography"],
    "natural light": ["NaturalLightPhotography"],
}

SUBJECT_TAGS: dict[str, list[str]] = {
    "landscape":     ["LandscapeLovers", "LandscapesOfTheWorld"],
    "couple":        ["CouplePhotography", "EngagementShoot"],
    "solo portrait": ["SoloPortrait"],
    "group":         ["GroupPortrait"],
    "performer":     ["PerformerLife"],
    "product":       ["ProductShoot"],
}

LENS_TAXONOMY = HashtagTaxonomy(
    brand_tags=BRAND_TAGS,
    genre_tags=GENRE_TAGS,
    mood_tags=MOOD_TAGS,
    lighting_tags=LIGHTING_TAGS,
    subject_tags=SUBJECT_TAGS,
    reach_tags=REACH_TAGS,
)


# ── Compatibility wrapper ────────────────────────────────────────────────────

def build_hashtags(
    genre: str | None,
    subject_type: str | None = None,
    mood: str | None = None,
    lighting: str | None = None,
    pass3_tags: str | list | None = None,
    target_count: int = 22,
) -> list[str]:
    """LENS-flavored shortcut. Same signature the rest of LENS already calls."""
    return _build_hashtags(
        LENS_TAXONOMY,
        genre=genre,
        subject_type=subject_type,
        mood=mood,
        lighting=lighting,
        pass3_tags=pass3_tags,
        target_count=target_count,
    )


# Re-export the helpers in case any other module imports them from here.
__all__ = [
    "BRAND_TAGS", "REACH_TAGS", "GENRE_TAGS", "MOOD_TAGS",
    "LIGHTING_TAGS", "SUBJECT_TAGS", "LENS_TAXONOMY",
    "build_hashtags", "slugify_tag", "parse_pass3_tags",
]
