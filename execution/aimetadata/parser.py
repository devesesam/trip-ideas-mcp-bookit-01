"""Robust parser for the `aiMetadata` JSON-string field on Sanity `page` docs.

Source field has stable top-level keys (19 fields, present on 99.8% of docs)
but unstable value types — `amenities` is sometimes a string, sometimes a
list[str]; `track_trail_details` is sometimes a dict, sometimes a string,
sometimes null; `location` is usually a dict but 25 docs have list[dict]; etc.

This parser:
- Decodes the JSON string and catches `JSONDecodeError` for truncated docs
  (~206 in the corpus), returning a `parse_error=True` result instead of
  raising. Tools can then either skip those docs or surface a "thin data" note.
- Normalizes value-type variance so every field has a single predictable
  shape on `ParsedAiMetadata` (most list-or-string fields become `list[str]`).
- Parses derived signals deterministically — duration band from the
  `duration_text` regex, dog-friendly enum from text classification, settlement
  hints from the location field — so tools don't need their own ad-hoc parsing.

No LLM calls. Everything here runs in microseconds per doc.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional


# =====================================================================
# Public dataclasses
# =====================================================================


@dataclass
class NearbyPlace:
    name: str
    type: Optional[str] = None        # town, city, suburb, bay, etc. (free-form)
    context: Optional[str] = None     # free-form description of the relationship
    distance_text: Optional[str] = None
    confidence: Optional[float] = None


@dataclass
class TrackTrail:
    name: Optional[str] = None
    primary_type: Optional[str] = None        # walk | hike | tramp | cycle | drive | scenic_drive | None
    difficulty: Optional[str] = None          # easy | moderate | demanding | unknown | None
    duration_text: Optional[str] = None
    description: Optional[str] = None
    exposed: Optional[bool] = None
    steps_present: Optional[bool] = None
    surface: Optional[str] = None
    classification_confidence: Optional[float] = None
    article_focus: Optional[str] = None       # e.g., "place_with_tracks"
    raw: Optional[Any] = None                  # original value, for debugging


@dataclass
class LocationHint:
    region: Optional[str] = None
    subregion: Optional[str] = None
    subregion2: Optional[str] = None
    suburb_place: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass
class ParsedAiMetadata:
    # Parse status
    parse_error: bool = False
    parse_error_message: Optional[str] = None
    raw_length: int = 0

    # Always-stable fields
    title: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    coordinates: Optional[dict] = None        # {lat, lng} or None

    # Normalized to list[str] regardless of source type
    attractions: list[str] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)
    transportation: list[str] = field(default_factory=list)
    amenities: list[str] = field(default_factory=list)
    accessibility_notes: list[str] = field(default_factory=list)
    local_tips: list[str] = field(default_factory=list)
    ideal_for: list[str] = field(default_factory=list)
    historical_significance: list[str] = field(default_factory=list)
    water_safety_notes: list[str] = field(default_factory=list)
    best_time_to_visit: list[str] = field(default_factory=list)
    inline_tags: list[str] = field(default_factory=list)

    # Structured derivations
    nearby_places: list[NearbyPlace] = field(default_factory=list)
    track_trail: Optional[TrackTrail] = None
    locations: list[LocationHint] = field(default_factory=list)
    dog_friendly_kind: str = "unknown"        # allowed | on_leash_only | seasonal | not_allowed | unknown
    dog_friendly_raw: str = ""

    # ----- convenience helpers -----

    def primary_location(self) -> Optional[LocationHint]:
        return self.locations[0] if self.locations else None

    def settlement(self) -> Optional[str]:
        loc = self.primary_location()
        if not loc:
            return None
        # Prefer most specific name available
        return loc.suburb_place or loc.subregion2 or loc.subregion or None

    def duration_band(self) -> Optional[str]:
        """Bucket the duration_text from track_trail into sub_hour / 1_to_2_hours / half_day / full_day / multi_day."""
        if not self.track_trail or not self.track_trail.duration_text:
            return None
        return _parse_duration_band(self.track_trail.duration_text)

    def physical_intensity_hint(self) -> Optional[str]:
        """Return what aiMetadata says about intensity, normalized to easy / moderate / demanding.

        Tool callers should also consult tag-based intensity hints separately and combine.
        """
        if not self.track_trail or not self.track_trail.difficulty:
            return None
        d = self.track_trail.difficulty.strip().lower()
        if d in ("easy",):
            return "easy"
        if d in ("moderate", "medium", "intermediate"):
            return "moderate"
        if d in ("hard", "difficult", "demanding", "advanced"):
            return "demanding"
        # "unknown" / "n/a" / etc.
        return None


# =====================================================================
# Public entry point
# =====================================================================


def parse(raw: Optional[str]) -> ParsedAiMetadata:
    """Parse an `aiMetadata` JSON-encoded string into a `ParsedAiMetadata`.

    Returns a `parse_error=True` instance for truncated / malformed input
    rather than raising. Callers can check `.parse_error` to decide whether
    to skip the doc or use whatever partial data they have.
    """
    if not raw:
        return ParsedAiMetadata(parse_error=False, raw_length=0)

    out = ParsedAiMetadata(raw_length=len(raw))

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        out.parse_error = True
        out.parse_error_message = str(e)[:200]
        return out

    if not isinstance(data, dict):
        # Unexpected top-level shape; surface as parse_error
        out.parse_error = True
        out.parse_error_message = f"Top-level is {type(data).__name__}, expected dict"
        return out

    # ----- stable scalars -----
    out.title = _as_str(data.get("title"))
    out.description = _as_str(data.get("description"))
    out.keywords = _as_list(data.get("keywords"))
    out.coordinates = _parse_coordinates(data.get("coordinates"))

    # ----- list-or-string fields normalized to list[str] -----
    out.attractions = _as_list(data.get("attractions"))
    out.activities = _as_list(data.get("activities"))
    out.transportation = _as_list(data.get("transportation"))
    out.amenities = _as_list(data.get("amenities"))
    out.accessibility_notes = _as_list(data.get("accessibility"))
    out.local_tips = _as_list(data.get("local_tips"))
    out.ideal_for = _as_list(data.get("ideal_for"))
    out.historical_significance = _as_list(data.get("historical_significance"))
    out.water_safety_notes = _as_list(data.get("water_safety_notes"))
    out.best_time_to_visit = _as_list(data.get("best_time_to_visit"))
    out.inline_tags = _as_list(data.get("tags"))

    # ----- structured derivations -----
    out.nearby_places = _parse_nearby_places(data.get("nearby_places"))
    out.track_trail = _parse_track_trail(data.get("track_trail_details"))
    out.locations = _parse_locations(data.get("location"))

    raw_dog = data.get("dog_friendly")
    out.dog_friendly_raw = _as_str(raw_dog)
    out.dog_friendly_kind = _classify_dog_friendly(raw_dog)

    return out


# =====================================================================
# Type-coercion helpers
# =====================================================================


def _as_str(val: Any) -> str:
    """Coerce any value to a string. Lists become newline-joined; None → ''."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return "\n".join(_as_str(v) for v in val if v is not None)
    if isinstance(val, dict):
        # Stringify dicts conservatively; rarely useful but never crash
        try:
            return json.dumps(val, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(val)
    return str(val)


def _as_list(val: Any) -> list[str]:
    """Coerce any value to list[str]. Strings become [s]; None/empty become [];
    lists pass through with non-string items stringified.
    """
    if val is None:
        return []
    if isinstance(val, list):
        out: list[str] = []
        for item in val:
            if item is None:
                continue
            if isinstance(item, str):
                if item.strip():
                    out.append(item)
            elif isinstance(item, (int, float, bool)):
                out.append(str(item))
            elif isinstance(item, dict):
                # If a list[dict] sneaks in (e.g., nearby_places-like), stringify the most useful key
                name = item.get("name") or item.get("title") or item.get("text")
                out.append(name if isinstance(name, str) else json.dumps(item, ensure_ascii=False))
            else:
                out.append(str(item))
        return out
    if isinstance(val, str):
        s = val.strip()
        return [s] if s else []
    if isinstance(val, dict):
        # A dict where a list was expected — extract values if they look list-like
        return []
    if isinstance(val, (int, float, bool)):
        return [str(val)]
    return []


def _parse_coordinates(val: Any) -> Optional[dict]:
    """Return `{lat, lng}` if both are numeric; else None."""
    if not isinstance(val, dict):
        return None
    lat = val.get("lat")
    lng = val.get("lng")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return {"lat": float(lat), "lng": float(lng)}
    return None


# =====================================================================
# Field-specific parsers
# =====================================================================


def _parse_nearby_places(val: Any) -> list[NearbyPlace]:
    """Handle the four observed shapes:
    - list[dict] with {name, type, context, distance_text, confidence}
    - list[str] like "Ōrewa (town)"
    - single dict (rare)
    - null / empty list
    """
    if not val:
        return []
    if isinstance(val, dict):
        return [_dict_to_nearby_place(val)]
    if isinstance(val, list):
        out: list[NearbyPlace] = []
        for item in val:
            if isinstance(item, dict):
                out.append(_dict_to_nearby_place(item))
            elif isinstance(item, str):
                out.append(_string_to_nearby_place(item))
            # silently skip other shapes
        return out
    return []


def _dict_to_nearby_place(d: dict) -> NearbyPlace:
    name = d.get("name") or d.get("title") or ""
    return NearbyPlace(
        name=str(name),
        type=_optstr(d.get("type")),
        context=_optstr(d.get("context")),
        distance_text=_optstr(d.get("distance_text")),
        confidence=_optfloat(d.get("confidence")),
    )


_PARENS_TYPE = re.compile(r"^(?P<name>.+?)\s*\((?P<type>[^)]+)\)\s*$")


def _string_to_nearby_place(s: str) -> NearbyPlace:
    """Parse strings like "Ōrewa (town)" or "Auckland (city, 40 km south)"."""
    s = s.strip()
    m = _PARENS_TYPE.match(s)
    if not m:
        return NearbyPlace(name=s)
    name = m.group("name").strip()
    inner = m.group("type").strip()
    # If "type, distance" — split on first comma
    if "," in inner:
        type_part, _, distance_part = inner.partition(",")
        return NearbyPlace(
            name=name,
            type=type_part.strip() or None,
            distance_text=distance_part.strip() or None,
        )
    return NearbyPlace(name=name, type=inner or None)


def _parse_track_trail(val: Any) -> Optional[TrackTrail]:
    """Handle dict (897 docs) / str (101) / null (70) / list[str] (26) /
    list[dict] (6) / empty (8) variants. Returns None for null/empty.

    For string variants, captures the prose as `description`.
    For list[str], joins entries.
    For list[dict], returns the first entry (multi-track docs are rare).
    """
    if val is None or val == "" or val == [] or val == {}:
        return None
    if isinstance(val, str):
        return TrackTrail(description=val.strip(), raw=val)
    if isinstance(val, list):
        if not val:
            return None
        # list of strings → join as description
        if all(isinstance(x, str) for x in val):
            return TrackTrail(description="\n".join(x.strip() for x in val if x), raw=val)
        # list of dicts → take first; surface remainder count via raw
        first_dict = next((x for x in val if isinstance(x, dict)), None)
        if first_dict:
            tt = _dict_to_track_trail(first_dict)
            tt.raw = val
            return tt
        return None
    if isinstance(val, dict):
        return _dict_to_track_trail(val)
    return None


def _dict_to_track_trail(d: dict) -> TrackTrail:
    return TrackTrail(
        name=_optstr(d.get("name") or d.get("track_name")),
        primary_type=_optstr(d.get("primary_type") or d.get("type")),
        difficulty=_optstr(d.get("difficulty")),
        duration_text=_optstr(d.get("duration_text") or d.get("duration")),
        description=_optstr(d.get("description")),
        exposed=_optbool(d.get("exposed")),
        steps_present=_optbool(d.get("steps_present")),
        surface=_optstr(d.get("surface")),
        classification_confidence=_optfloat(d.get("classification_confidence")),
        article_focus=_optstr(d.get("article_focus")),
        raw=d,
    )


def _parse_locations(val: Any) -> list[LocationHint]:
    """Handle dict (1083 docs) → single hint, list[dict] (25 docs) → multiple hints."""
    if not val:
        return []
    if isinstance(val, dict):
        return [_dict_to_location_hint(val)]
    if isinstance(val, list):
        return [_dict_to_location_hint(item) for item in val if isinstance(item, dict)]
    return []


def _dict_to_location_hint(d: dict) -> LocationHint:
    return LocationHint(
        region=_optstr(d.get("region")),
        subregion=_optstr(d.get("subregion")),
        subregion2=_optstr(d.get("subregion2")),
        suburb_place=_optstr(d.get("suburb_place")),
        raw=d,
    )


# --- dog_friendly text classifier -------------------------------------

_PATTERNS_NOT_ALLOWED = [
    r"\bnot allowed\b",
    r"\bno dogs\b",
    r"\bdogs prohibited\b",
    r"\bdogs are not permitted\b",
    r"\bdog[s]?[\s-]+free zone\b",
    r"\bpest[\s-]+free\b.*\bdogs?\b",   # pest-free island typically excludes dogs
]

_PATTERNS_ON_LEASH = [
    r"\bon[\s-]+leash\b",
    r"\bon[\s-]+lead\b",
    r"\bmust be (under control|leashed|on a lead|on lead)\b",
    r"\bunder control\b",
]

_PATTERNS_SEASONAL = [
    r"\bseasonal\b",
    r"\bbetween\s+\d{1,2}\s*(am|pm)?\s+and\s+\d{1,2}",   # "between 10am and 5pm"
    r"\bfrom\s+(december|january|february|march|april|may|june|july|august|september|october|november)\b",
    r"\bsummer (only|months)\b",
]

_PATTERNS_ALLOWED = [
    r"\bdogs allowed\b",
    r"\bdog[\s-]+friendly\b",
    r"\boff[\s-]+leash\b",
    r"\bdogs welcome\b",
]


def _classify_dog_friendly(val: Any) -> str:
    """Return one of: allowed | on_leash_only | seasonal | not_allowed | unknown.

    Heuristic order: not_allowed first (most restrictive), then seasonal,
    then on_leash, then allowed. Catches common phrasings; ambiguous cases
    return "unknown".
    """
    if val is None or val == "":
        return "unknown"

    if isinstance(val, dict):
        # Rare shape (1 doc). Try common keys.
        text = " ".join(
            _as_str(v) for v in val.values() if isinstance(v, (str, list))
        )
    else:
        text = _as_str(val)

    text_lower = text.lower()
    if not text_lower.strip():
        return "unknown"

    if any(re.search(p, text_lower) for p in _PATTERNS_NOT_ALLOWED):
        return "not_allowed"
    if any(re.search(p, text_lower) for p in _PATTERNS_SEASONAL):
        return "seasonal"
    if any(re.search(p, text_lower) for p in _PATTERNS_ON_LEASH):
        return "on_leash_only"
    if any(re.search(p, text_lower) for p in _PATTERNS_ALLOWED):
        return "allowed"
    return "unknown"


# --- duration_band parser ---------------------------------------------

_NUMBER_WORDS = {
    "half": 0.5, "one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# Captures "<number> hour[s]" or "<word> hour[s]" or "<number> minute[s]"
_HOURS_PATTERN = re.compile(
    r"\b(?:(\d+(?:\.\d+)?)|(half|one|a|an|two|three|four|five|six|seven|eight|nine|ten))\s*"
    r"(?:[–—\-]\s*(\d+(?:\.\d+)?)\s*)?"      # optional upper range like "2-4"
    r"(hours?|hrs?|h)\b",
    re.IGNORECASE,
)

_MINS_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*"
    r"(?:[–—\-]\s*(\d+(?:\.\d+)?)\s*)?"
    r"(minutes?|mins?|m)\b",
    re.IGNORECASE,
)


def _parse_duration_band(text: str) -> Optional[str]:
    """Bucket a duration phrase into:
        sub_hour       (< 60 min)
        1_to_2_hours   (60 ≤ min < 180)
        half_day       (180 ≤ min < 360)
        full_day       (360 ≤ min < 720)
        multi_day      (≥ 720 min, or contains "multi-day"/"days")
    Returns None when no recognisable duration is present.
    """
    if not text:
        return None
    t = text.lower()

    # Multi-day shortcuts
    if re.search(r"\bmulti[\s-]?day\b", t) or re.search(r"\b\d+\s*day(s)?\b", t):
        return "multi_day"
    if "all day" in t:
        return "full_day"
    if re.search(r"\bovernight\b", t):
        return "multi_day"

    minutes = _largest_minutes_in_text(t)
    if minutes is None:
        return None

    if minutes < 60:
        return "sub_hour"
    if minutes < 180:
        return "1_to_2_hours"
    if minutes < 360:
        return "half_day"
    if minutes < 720:
        return "full_day"
    return "multi_day"


def _largest_minutes_in_text(text: str) -> Optional[float]:
    """Find all hour/minute tokens; return the largest (uses range upper bound when present)."""
    candidates: list[float] = []

    # Hours: groups (digit, word, upper_bound, unit)
    for match in _HOURS_PATTERN.finditer(text):
        num_str, word, upper = match.group(1), match.group(2), match.group(3)
        n: Optional[float] = None
        if num_str:
            try:
                n = float(num_str)
            except ValueError:
                n = None
        elif word and word.lower() in _NUMBER_WORDS:
            n = float(_NUMBER_WORDS[word.lower()])
        if n is None:
            continue
        # Prefer the range upper bound when present (e.g. "2-4 hours" → 4)
        if upper:
            try:
                n = max(n, float(upper))
            except ValueError:
                pass
        candidates.append(n * 60.0)

    # Minutes: groups (digit, upper_bound, unit)
    for match in _MINS_PATTERN.finditer(text):
        try:
            n = float(match.group(1))
        except (TypeError, ValueError):
            continue
        upper = match.group(2)
        if upper:
            try:
                n = max(n, float(upper))
            except ValueError:
                pass
        candidates.append(n)

    return max(candidates) if candidates else None


# =====================================================================
# Tiny optional-coercion helpers
# =====================================================================


def _optstr(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        return s if s else None
    return str(val)


def _optfloat(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _optbool(val: Any) -> Optional[bool]:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("true", "yes", "y"):
            return True
        if v in ("false", "no", "n"):
            return False
    return None
