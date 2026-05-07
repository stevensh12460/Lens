"""
content/hashtags.py

Hudson Valley location and genre hashtag bank.
Pure code — no LLM calls.
"""

from typing import Optional
from difflib import get_close_matches

# ── Tag banks ─────────────────────────────────────────────────────────────────

LOCATION_TAGS: dict[str, list[str]] = {
    "hudson_valley": [
        "#hudsonvalley",
        "#hudsonvalleyny",
        "#hudsonvalleyphotographer",
        "#hudsonvalleyphotography",
        "#hudsonvalleywedding",
        "#hudsonvalleylife",
        "#explorehudsonvalley",
        "#upstateny",
        "#upstatenewyork",
        "#upstatenewyorkphotographer",
        "#newyorkphotographer",
        "#hvphotographer",
    ],
    "catskills": [
        "#catskills",
        "#catskillmountains",
        "#catskillsphotographer",
        "#catskillsphotography",
        "#catskillsny",
        "#catskillswedding",
        "#thecatskills",
        "#catskillsliving",
        "#catskillslife",
    ],
    "rhinebeck": [
        "#rhinebeck",
        "#rhinebeckny",
        "#rhinebeckphotographer",
        "#rhinebeckwedding",
        "#visitrhinebeck",
        "#rhinebecknewyork",
    ],
    "woodstock": [
        "#woodstockny",
        "#woodstockphotographer",
        "#woodstocknewyork",
        "#woodstockphotography",
        "#visitwoodstock",
        "#woodstocklife",
    ],
    "beacon": [
        "#beaconny",
        "#beaconphotographer",
        "#beaconnewyork",
        "#beaconphotography",
        "#visitbeacon",
        "#beaconlife",
    ],
    "hudson": [
        "#hudsonnY",
        "#hudsonny",
        "#hudsonnewYork",
        "#hudsonphotographer",
        "#visitHudson",
        "#hudsonlife",
    ],
    "kingston": [
        "#kingstonny",
        "#kingstonphotographer",
        "#kingstonnewYork",
        "#visitkingston",
        "#kingstonlife",
        "#kingstonphotography",
    ],
    "new_paltz": [
        "#newpaltz",
        "#newpaltzny",
        "#newpaltznewYork",
        "#newpaltZphotographer",
        "#visitnewpaltz",
        "#shawangunks",
        "#gunks",
    ],
    "poughkeepsie": [
        "#poughkeepsie",
        "#poughkeepsieny",
        "#poughkeepsiephotographer",
        "#midhudson",
        "#midhudsonvalley",
    ],
    "millbrook": [
        "#millbrookny",
        "#millbrooknewYork",
        "#dutchesscounty",
        "#dutchesscountyphotographer",
    ],
    "cold_spring": [
        "#coldspring",
        "#coldspringny",
        "#coldspringphotographer",
        "#putnamcounty",
    ],
}

GENRE_TAGS: dict[str, list[str]] = {
    "wedding": [
        "#weddingphotographer",
        "#weddingphotography",
        "#hudsonvalleywedding",
        "#hudsonvalleyweddingphotographer",
        "#weddingday",
        "#bridetobe",
        "#engaged",
        "#justmarried",
        "#realwedding",
        "#authenticwedding",
        "#documentarywedding",
        "#weddinginspo",
        "#weddingstyle",
        "#brideandgroom",
        "#weddingseason",
    ],
    "portrait": [
        "#portraitphotographer",
        "#portraitphotography",
        "#hudsonvalleyportraitphotographer",
        "#portraitmode",
        "#portraits",
        "#portraiture",
        "#naturallight",
        "#naturallightphotography",
        "#portraitshots",
        "#environmentalportrait",
        "#lifestyleportrait",
        "#authenticportraits",
    ],
    "boudoir": [
        "#boudoirphotographer",
        "#boudoirphotography",
        "#empowerment",
        "#bodypositivity",
        "#boudoirshoot",
        "#boudoirinspiration",
        "#feminineportraiture",
        "#selflovephotography",
        "#intimateportraiture",
        "#hudsonvalleyboudoir",
        "#empowerphotography",
        "#confidentwomen",
    ],
    "commercial": [
        "#commercialphotography",
        "#brandphotography",
        "#branding",
        "#brandphotographer",
        "#commercialphotographer",
        "#productphotography",
        "#businessportrait",
        "#personalbranding",
        "#smallbusiness",
        "#businessphotography",
        "#contentcreation",
        "#brandstory",
    ],
    "events": [
        "#eventphotographer",
        "#eventphotography",
        "#events",
        "#eventcoverage",
        "#corporateevents",
        "#partyphotographer",
        "#eventdocumentation",
        "#liveevent",
        "#hudsonvalleyevents",
        "#galaphotographer",
        "#conferencephotographer",
    ],
    "nature": [
        "#naturephotography",
        "#landscapephotography",
        "#hudsonvalleynature",
        "#hudsonvalleylandscape",
        "#landscapes",
        "#naturephotographer",
        "#outdoorphotography",
        "#wildlifephotography",
        "#earthpix",
        "#natgeo",
        "#landscapephotographer",
        "#goldenhour",
        "#goldenhourphotography",
        "#sunsetphotography",
    ],
}

MOOD_TAGS: dict[str, list[str]] = {
    "dramatic": [
        "#dramaticphotography",
        "#moodyphotography",
        "#darkmoody",
        "#moodygrams",
        "#moodyports",
        "#darkandmoody",
        "#cinematicphotography",
        "#moodyfilm",
        "#dramaticlighting",
        "#contrastphotography",
    ],
    "romantic": [
        "#romanticphotography",
        "#loveshot",
        "#lovephotography",
        "#romanticphotos",
        "#softromantic",
        "#romanticvibes",
        "#lovestory",
        "#couplegoals",
        "#romanticlight",
    ],
    "playful": [
        "#funphotos",
        "#candidphotography",
        "#candidmoments",
        "#authenticmoments",
        "#realmoments",
        "#joyfulphotography",
        "#laughtershots",
        "#genuinesmile",
        "#joyfullife",
    ],
    "serene": [
        "#peacefulphotography",
        "#minimalistphotography",
        "#quietmoments",
        "#stilllife",
        "#serenephotography",
        "#calmvibes",
        "#minimalist",
        "#peaceful",
        "#breathe",
        "#slowliving",
    ],
    "bold": [
        "#boldphotography",
        "#powerfulportrait",
        "#strongwomen",
        "#boldcolors",
        "#highcontrast",
        "#impactful",
        "#visualsoflife",
    ],
    "ethereal": [
        "#etherealphotography",
        "#dreamyphotography",
        "#softlight",
        "#dreamy",
        "#filmgrain",
        "#filmphotography",
        "#analogvibes",
        "#softdreamy",
    ],
}

SEASONAL_TAGS: dict[str, list[str]] = {
    "spring": [
        "#springphotography",
        "#hudsonvalleyspring",
        "#springblossoms",
        "#springlight",
        "#goldenhourspring",
        "#springportraits",
        "#bloomingseason",
        "#springtime",
        "#freshstart",
        "#springvibes",
    ],
    "summer": [
        "#summerphotography",
        "#goldenhoursummer",
        "#summerportraits",
        "#summerglow",
        "#summervibes",
        "#summerlight",
        "#hudsonvalleysummer",
        "#summersessions",
        "#goldenhour",
        "#summerdays",
    ],
    "autumn": [
        "#fallphotography",
        "#autumnleaves",
        "#hudsonvalleyfall",
        "#fallfoliage",
        "#autumnphotography",
        "#fallportraits",
        "#autumnvibes",
        "#foliageseason",
        "#peakfoliage",
        "#autumnlight",
        "#fallcolors",
        "#hudsonvalleyautumn",
    ],
    "winter": [
        "#winterphotography",
        "#snowphotography",
        "#winterportraits",
        "#winterlight",
        "#snowday",
        "#winterwonderland",
        "#hudsonvalleywinter",
        "#colddays",
        "#wintervibes",
        "#frostyphotos",
    ],
}

# Normalised lookup map: lowercase key → canonical dict key
_LOCATION_KEY_MAP: dict[str, str] = {
    k.replace("_", " "): k for k in LOCATION_TAGS
}
_LOCATION_KEY_MAP.update({k: k for k in LOCATION_TAGS})  # include underscore forms too


# ── Public functions ──────────────────────────────────────────────────────────

def get_season() -> str:
    """Return the current meteorological season based on today's date."""
    from datetime import date as _date
    today = _date.today()
    month = today.month
    if month in (3, 4, 5):
        return "spring"
    elif month in (6, 7, 8):
        return "summer"
    elif month in (9, 10, 11):
        return "autumn"
    else:
        return "winter"


def add_location_tags(location_name: str) -> list[str]:
    """
    Fuzzy-match `location_name` to the tag bank and return matching tags.
    Returns empty list if no close match found.
    """
    normalised = location_name.lower().strip()

    # Direct match (underscore or space form)
    if normalised in _LOCATION_KEY_MAP:
        return LOCATION_TAGS[_LOCATION_KEY_MAP[normalised]]

    # Replace spaces with underscores and try again
    slug = normalised.replace(" ", "_")
    if slug in LOCATION_TAGS:
        return LOCATION_TAGS[slug]

    # Fuzzy match against all keys (both forms)
    candidates = list(_LOCATION_KEY_MAP.keys())
    matches = get_close_matches(normalised, candidates, n=1, cutoff=0.6)
    if matches:
        return LOCATION_TAGS[_LOCATION_KEY_MAP[matches[0]]]

    return []


def get_hashtags(
    genre: str,
    mood: Optional[str] = None,
    location: Optional[str] = None,
    season: Optional[str] = None,
    limit: int = 30,
) -> list[str]:
    """
    Return a combined, deduplicated hashtag list for the given parameters.
    Always includes genre tags. Adds mood/location/season tags when provided.
    Result is trimmed to `limit` tags (default 30 — Instagram max is 30).
    """
    seen: set[str] = set()
    tags: list[str] = []

    def _add(source: list[str]) -> None:
        for t in source:
            low = t.lower()
            if low not in seen:
                seen.add(low)
                tags.append(t)

    # Genre (always included — highest priority)
    _add(GENRE_TAGS.get(genre.lower(), []))

    # Location
    if location:
        _add(add_location_tags(location))

    # Mood
    if mood:
        _add(MOOD_TAGS.get(mood.lower(), []))

    # Season
    if season:
        _add(SEASONAL_TAGS.get(season.lower(), []))

    # Always top up with base Hudson Valley location tags if space remains
    if len(tags) < limit:
        _add(LOCATION_TAGS["hudson_valley"])

    return tags[:limit]
