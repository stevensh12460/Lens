"""
content/seasonal.py

Seasonal intelligence for the content layer.
Pure code — no LLM calls.
"""

from datetime import date, timedelta
from typing import Optional

# ── Season definitions ────────────────────────────────────────────────────────

# Meteorological seasons (month → season)
_MONTH_SEASON: dict[int, str] = {
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
    12: "winter",
}

# Which genres perform best in each season
SEASONAL_GENRES: dict[str, list[str]] = {
    "spring": ["wedding", "portrait", "nature"],
    "summer": ["events", "commercial", "nature"],
    "autumn": ["nature", "portrait", "wedding"],
    "winter": ["boudoir", "portrait", "commercial"],
}

# Season-appropriate caption hooks for Hudson Valley
SEASONAL_CAPTION_HOOKS: dict[str, list[str]] = {
    "spring": [
        "There's something about spring light in the Hudson Valley that makes everything feel new again.",
        "First golden hour of the season hit different this year.",
        "Spring bookings are filling up — and so is the light.",
        "The Hudson Valley in bloom is everything I shoot for all winter.",
        "Soft greens, long evenings, the smell of mud and possibility — spring is here.",
        "Wedding season is officially starting and I am ready.",
        "If you've been thinking about a portrait session, spring light is calling your name.",
        "Every year I forget how good the Hudson Valley looks waking up.",
    ],
    "summer": [
        "Golden hour in July is practically its own season.",
        "Long days, warm evenings, and clients who actually want to be outside — summer is peak.",
        "Summer sessions are booking fast — the light this time of year is something else.",
        "There is nothing like Hudson Valley summer for events.",
        "Hot days, golden evenings, good people — that's what summer looks like through my lens.",
        "Summer is the season when everyone finally has a reason to look their best.",
        "The light at 7pm in August is the reason I became a photographer.",
        "Outdoor sessions, garden weddings, rooftop events — summer is the best season.",
    ],
    "autumn": [
        "The light this time of year is something I chase all summer waiting for.",
        "Hudson Valley in October is why I became a photographer.",
        "Peak foliage season in the Hudson Valley is something you have to see to believe.",
        "Autumn light is brutally honest — it shows everything exactly as it is, and it's gorgeous.",
        "October in the Hudson Valley feels like the whole valley is on fire in the best way.",
        "Fall portraits hit differently when the whole world is turning gold around you.",
        "The Hudson Valley turns into a painting every October and I get to work in it.",
        "Foliage season books up faster than any other time of year — plan accordingly.",
        "There's a week in late October where the light is so good I'd shoot every day if I could.",
        "Autumn weddings have a warmth no other season can touch.",
    ],
    "winter": [
        "Winter light is underrated — it's low, soft, and makes everyone look cinematic.",
        "Boudoir season is upon us — because winter is the perfect time to feel extraordinary.",
        "Short days mean golden hour practically starts at lunch. I'm not complaining.",
        "Cold mornings, bare trees, stark light — winter is honestly beautiful for portraits.",
        "January is when people start dreaming about spring weddings. I'm already booking them.",
        "The inquiry season is here — if you're planning a 2025 wedding, now is the time.",
        "There's a stillness to winter sessions that summer can't buy.",
        "Snow days make for the best last-minute portrait sessions.",
    ],
}

# Upcoming seasonal opportunities calendar
# Format: (month, day_start, day_end, label, description)
_OPPORTUNITIES: list[tuple] = [
    # Spring
    (3, 1, 31, "Spring Booking Rush", "Couples and families start booking spring/summer sessions"),
    (3, 15, 31, "Spring Portrait Season Opens", "Light is back — soft, warm, outdoor-friendly"),
    (4, 1, 30, "Cherry Blossom Season", "Hudson Valley gardens and orchards in bloom"),
    (5, 1, 31, "Wedding Season Kickoff", "Peak season begins — schedule accordingly"),

    # Summer
    (6, 1, 30, "Summer Events Season", "Corporate events, galas, outdoor events ramp up"),
    (6, 15, 30, "Summer Portrait Peak", "Long evenings, golden hour after 8pm"),
    (7, 1, 31, "Peak Wedding Season", "Busiest wedding month — secondary shooters needed"),
    (8, 1, 31, "Late Summer Sessions", "Sunflower fields, late golden hour, summer heat"),
    (8, 15, 31, "Fall Booking Window Opens", "Clients start booking autumn foliage sessions"),

    # Autumn
    (9, 1, 30, "Early Foliage Prep", "Foliage dates vary — follow the tree reports"),
    (9, 15, 30, "Fall Portrait Season Opens", "Color change begins at higher elevations"),
    (10, 1, 14, "Early Peak Foliage", "Higher elevations at or near peak"),
    (10, 15, 31, "Peak Foliage Typically", "Lower Hudson Valley peak — book these dates now"),
    (11, 1, 15, "Holiday Mini Session Season", "Holiday mini sessions begin November 1"),
    (11, 1, 30, "End-of-Year Commercial Rush", "Brands need content before year-end"),

    # Winter
    (12, 1, 20, "Holiday Portrait Rush", "Last-minute family portraits and gifts"),
    (12, 26, 31, "Year-End Boudoir Season", "New Year transformation shoots spike"),
    (1, 1, 28, "Wedding Inquiry Peak", "January–February is highest wedding inquiry season"),
    (1, 15, 31, "Spring Planning Season", "Brides planning May–June weddings are in full research mode"),
    (2, 1, 28, "Valentine Boudoir Rush", "Boudoir bookings spike leading up to Valentine's Day"),
    (2, 1, 28, "Wedding Inquiry Season Continues", "Second-highest inquiry month of the year"),
]


# ── Public functions ──────────────────────────────────────────────────────────

def get_current_season(d: Optional[date] = None) -> str:
    """Return spring/summer/autumn/winter based on the given date (defaults to today)."""
    target = d or date.today()
    return _MONTH_SEASON[target.month]


def get_seasonal_genres(season: str) -> list[str]:
    """Return list of genres that perform best in the given season."""
    return SEASONAL_GENRES.get(season.lower(), [])


def get_seasonal_caption_hooks(season: Optional[str] = None) -> list[str]:
    """
    Return seasonal caption hooks/angles.
    Defaults to current season if none provided.
    """
    s = season or get_current_season()
    return SEASONAL_CAPTION_HOOKS.get(s.lower(), [])


def weight_queue_by_season(
    images_list: list[dict],
    season: Optional[str] = None,
    boost: float = 0.25,
) -> list[dict]:
    """
    Re-rank a list of image dicts by boosting genres that match the current season.
    Each dict should have at least 'genre' and optionally 'nima_composite' / 'quality_score'.

    Seasonal genres receive a `boost` multiplier added to their composite score.
    Returns a new list sorted descending by adjusted_score.
    """
    s = season or get_current_season()
    priority_genres = set(get_seasonal_genres(s))

    def _score(img: dict) -> float:
        base = (
            (img.get("nima_composite") or 0) * 0.6
            + (img.get("quality_score") or 0) * 0.4
        )
        if img.get("genre", "").lower() in priority_genres:
            base += boost
        return base

    return sorted(images_list, key=_score, reverse=True)


def get_upcoming_opportunities(
    days: int = 60,
    start: Optional[date] = None,
) -> list[dict]:
    """
    Return seasonal events/opportunities in the next `days` days.
    Useful for planning shoots and content topics in advance.
    """
    today = start or date.today()
    end = today + timedelta(days=days)
    results: list[dict] = []

    # Check each opportunity in the current year and next year
    for year_offset in range(2):
        year = today.year + year_offset
        for month, day_start, day_end, label, description in _OPPORTUNITIES:
            opp_start = date(year, month, day_start)
            try:
                opp_end = date(year, month, day_end)
            except ValueError:
                # Handle months with fewer days (e.g., Feb 28/29)
                import calendar as _cal
                last_day = _cal.monthrange(year, month)[1]
                opp_end = date(year, month, min(day_end, last_day))

            # Include if the opportunity window overlaps our search range
            if opp_end >= today and opp_start <= end:
                results.append(
                    {
                        "label": label,
                        "description": description,
                        "window_start": opp_start.isoformat(),
                        "window_end": opp_end.isoformat(),
                        "season": get_current_season(opp_start),
                        "days_away": (opp_start - today).days,
                    }
                )

    # Deduplicate (same label can appear from year_offset 0 and 1)
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in sorted(results, key=lambda x: x["window_start"]):
        key = f"{item['label']}|{item['window_start']}"
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    return deduped
