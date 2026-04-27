"""Tag → planning_attributes mapping for Tripideas Sanity tags.

Each of the 102 live Sanity tag names is mapped onto contributions for the
`planning_attributes` schema:

- `place_subtype_hints`: candidates for the single `place_subtype` value
- `themes`: contributions to the `themes` array
- `suitability`: boolean flags on the suitability sub-object
- `intensity_hint`: candidate for `physical_intensity` (highest among hits wins)
- `accessibility`: contributions to accessibility sub-object
- `seasonality_hint`: candidate for `seasonality`
- `is_*` flags: classify tags that aren't feature tags (location tags like
  "Auckland", meta tags like "Top 5", activity tags like "Cycling",
  accommodation tags like "Backcountry Huts")

The mapping is the **starting hypothesis** — Sprint 0/1 may revise it after
seeing how it performs against the golden docs and live corpus. Treat each
mapping as overridable by the LLM normalization prompt's per-doc inferences.

Run as a script to validate against the live Sanity tag taxonomy:

    python execution/normalize/tag_mapping.py
"""

from __future__ import annotations

import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from sanity_client import SanityClient  # noqa: E402


@dataclass(frozen=True)
class TagMapping:
    place_subtype_hints: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    suitability: tuple[tuple[str, bool], ...] = ()       # immutable form of dict
    intensity_hint: Optional[str] = None                  # none|easy|moderate|demanding
    accessibility: tuple[tuple[str, object], ...] = ()    # immutable form of dict
    seasonality_hint: Optional[str] = None                # all_year|summer_best|winter_best|weather_sensitive|tide_sensitive
    time_of_day_hint: Optional[str] = None                # morning|day|evening|night
    is_meta_tag: bool = False
    is_location_tag: bool = False
    is_activity_tag: bool = False
    is_accommodation_tag: bool = False
    notes: Optional[str] = None


def _m(
    *,
    subtype: tuple[str, ...] = (),
    themes: tuple[str, ...] = (),
    suitability: dict[str, bool] | None = None,
    intensity: Optional[str] = None,
    accessibility: dict[str, object] | None = None,
    seasonality: Optional[str] = None,
    time_of_day: Optional[str] = None,
    is_meta: bool = False,
    is_location: bool = False,
    is_activity: bool = False,
    is_accommodation: bool = False,
    notes: Optional[str] = None,
) -> TagMapping:
    """Builder for TagMapping. dict args are normalized to immutable tuples."""
    return TagMapping(
        place_subtype_hints=subtype,
        themes=themes,
        suitability=tuple(sorted((suitability or {}).items())),
        intensity_hint=intensity,
        accessibility=tuple(sorted((accessibility or {}).items(), key=lambda x: x[0])),
        seasonality_hint=seasonality,
        time_of_day_hint=time_of_day,
        is_meta_tag=is_meta,
        is_location_tag=is_location,
        is_activity_tag=is_activity,
        is_accommodation_tag=is_accommodation,
        notes=notes,
    )


# === The mapping table ============================================================
#
# Organized by the primary-prompt category for easier review and Douglas-side
# validation. Ordering within each category is alphabetical.

TAG_MAPPINGS: dict[str, TagMapping] = {
    # ----- Track Type / Walk Type -------------------------------------------------
    "Alpine Routes":      _m(subtype=("track",), themes=("alpine", "adventure"), intensity="demanding"),
    "Boardwalks":         _m(subtype=("walk",), intensity="easy",
                             accessibility={"steps_present": False, "wheelchair_accessible": "partial"},
                             notes="Boardwalks usually mean stepfree access, but verify per doc."),
    "City Walks":         _m(subtype=("walk",), themes=("urban",), intensity="easy"),
    "Cliff Walks":        _m(subtype=("walk",), themes=("coastal", "scenic"), intensity="moderate",
                             accessibility={"weather_exposed": True}),
    "Coastal Walks":      _m(subtype=("walk",), themes=("coastal",), intensity="easy"),
    "Forest Walks":       _m(subtype=("walk",), themes=("forest", "nature"), intensity="easy"),
    "Great Walks":        _m(subtype=("track",), themes=("adventure", "nature"), intensity="demanding",
                             notes="DOC Great Walks — multi-day premier tramping routes."),
    "Heritage Trails":    _m(subtype=("walk",), themes=("heritage", "cultural"), intensity="easy"),
    "Hikes":              _m(subtype=("walk",), themes=("adventure",), intensity="moderate"),
    "Historical Trails":  _m(subtype=("walk",), themes=("heritage", "cultural"), intensity="easy",
                             notes="Synonym of Heritage Trails (per corpus_audit_2026-04-27 duplicates)."),
    "Lakeside Walk":      _m(subtype=("walk",), themes=("water", "scenic"), intensity="easy"),
    "Multi-Day Walks":    _m(subtype=("track",), themes=("adventure",), intensity="demanding"),
    "Night Walks":        _m(subtype=("walk",), time_of_day="night",
                             notes="Often glow-worm walks or bioluminescence."),
    "Scenic Drive":       _m(subtype=("scenic_drive",), themes=("scenic",), intensity="none"),
    "Scenic Drives":      _m(subtype=("scenic_drive",), themes=("scenic",), intensity="none",
                             notes="Synonym of Scenic Drive (per corpus_audit_2026-04-27 duplicates)."),
    "Scenic Loops":       _m(subtype=("walk",), themes=("scenic",), intensity="easy"),
    "Short Walks":        _m(subtype=("walk",), intensity="easy", suitability={"families": True}),
    "Te Araroa":          _m(subtype=("track",), themes=("adventure",), intensity="demanding",
                             notes="Synonym of Te Araroa Trail (per corpus_audit_2026-04-27 duplicates)."),
    "Te Araroa Trail":    _m(subtype=("track",), themes=("adventure",), intensity="demanding"),
    "Tramps":             _m(subtype=("track",), themes=("adventure",), intensity="demanding",
                             notes="NZ-specific: longer / more rugged than a hike, often multi-day."),
    "Urban Walks":        _m(subtype=("walk",), themes=("urban",), intensity="easy"),
    "Walks":              _m(subtype=("walk",), intensity="easy"),

    # ----- Natural Feature / Landscape Type ---------------------------------------
    "Beaches":            _m(subtype=("beach",), themes=("coastal",), suitability={"families": True}),
    "Beech Forests":      _m(subtype=("forest",), themes=("forest", "nature"),
                             notes="Native NZ beech (nothofagus) — mainly South Island."),
    "Coastal Cliffs":     _m(subtype=("cliff",), themes=("coastal", "scenic"),
                             accessibility={"weather_exposed": True}),
    "Dark Sky Places":    _m(themes=("scenic",), time_of_day="night",
                             notes="DOC/IDA designated dark-sky reserves (Mackenzie, Aoraki, etc.)"),
    "Exotic Forests":     _m(subtype=("forest",), themes=("forest",),
                             notes="Non-native plantation (pine, etc.) — distinct from native forest."),
    "Forests":            _m(subtype=("forest",), themes=("forest", "nature")),
    "Fossil Sites":       _m(themes=("geological", "heritage")),
    "Geological Sites":   _m(themes=("geological",)),
    "Glacial Lakes":      _m(subtype=("lake",), themes=("water", "alpine", "scenic")),
    "Glaciers":           _m(subtype=("glacier",), themes=("alpine", "water", "scenic"),
                             intensity="moderate", seasonality="weather_sensitive"),
    "Islands":            _m(subtype=("island",)),
    "Kauri Forests":      _m(subtype=("forest",), themes=("forest", "nature", "wildlife"),
                             accessibility={"biosecurity_required": True},
                             notes="Kauri dieback risk → biosecurity station washing required."),
    "Lakes":              _m(subtype=("lake",), themes=("water",)),
    "Mountains":          _m(subtype=("mountain",), themes=("alpine", "outdoors", "scenic")),
    "Natural Arches":     _m(themes=("geological", "scenic")),
    "Podocarp Forests":   _m(subtype=("forest",), themes=("forest", "nature"),
                             notes="Native NZ podocarps (rimu, totara, kahikatea) — wet lowland forest."),
    "Rainforest":         _m(subtype=("forest",), themes=("forest", "nature")),
    "Rivers":             _m(subtype=("river",), themes=("water",)),
    "Sea Caves":          _m(subtype=("sea_cave",), themes=("coastal", "geological"),
                             seasonality="tide_sensitive"),
    "Tidal Lagoons":      _m(subtype=("lagoon",), themes=("coastal", "water"),
                             seasonality="tide_sensitive"),
    "Volcanic Landscapes":_m(themes=("geological",)),
    "Waterfalls":         _m(subtype=("waterfall",), themes=("water", "scenic")),
    "Wetlands":           _m(subtype=("wetland",), themes=("water", "nature", "wildlife")),

    # ----- Protected Places & Reserves --------------------------------------------
    "Marine Reserves":    _m(subtype=("marine_reserve",), themes=("protected_area", "coastal", "wildlife")),
    "National Parks":     _m(subtype=("national_park",), themes=("protected_area", "nature")),
    "Parks":              _m(subtype=("park",), themes=("protected_area",),
                             notes="Generic; lower-priority subtype. Prefer National/Regional/Scenic when available."),
    "Regional Parks":     _m(subtype=("regional_park",), themes=("protected_area", "nature")),
    "Scenic Reserves":    _m(subtype=("scenic_reserve",), themes=("protected_area", "scenic")),

    # ----- Historical & Cultural --------------------------------------------------
    "Architecture":       _m(themes=("cultural", "heritage", "urban")),
    "Art Galleries":      _m(subtype=("art_gallery",), themes=("cultural", "urban")),
    "Cultural History":   _m(themes=("cultural", "heritage")),
    "Gold Mining History":_m(themes=("heritage",),
                             notes="NZ gold-rush era sites — Otago/West Coast."),
    "Heritage Precincts": _m(subtype=("heritage_precinct",), themes=("heritage", "cultural", "urban")),
    "Historic Sites":     _m(subtype=("historic_site",), themes=("heritage",)),
    "Historical Sites":   _m(subtype=("historic_site",), themes=("heritage",),
                             notes="Synonym of Historic Sites (per corpus_audit_2026-04-27 duplicates)."),
    "Local Legends & Myths": _m(themes=("cultural",)),
    "Maori History":      _m(themes=("cultural", "heritage"),
                             notes="Live tag uses 'Maori' (no macron). 'Māori' may also appear in source text."),
    "Memorials":          _m(subtype=("memorial",), themes=("heritage", "cultural")),
    "Mining History":     _m(themes=("heritage",)),
    "Museums":            _m(subtype=("museum",), themes=("cultural", "heritage", "urban")),
    "NZ History":         _m(themes=("heritage",),
                             notes="Per primary prompt: do not apply if a more specific historic tag is used."),
    "Public Art and Sculpture": _m(themes=("cultural", "urban")),

    # ----- Wildlife & Ecology -----------------------------------------------------
    "Bird Sanctuaries":   _m(subtype=("bird_sanctuary",), themes=("wildlife", "nature")),
    "Botanic Gardens":    _m(subtype=("botanic_garden",), themes=("nature", "urban", "family"),
                             suitability={"families": True}),
    "Conservation Projects": _m(themes=("wildlife", "nature")),
    "Ecological Restoration": _m(themes=("wildlife", "nature")),
    "Restoration Sites":  _m(themes=("wildlife", "nature")),
    "Wildlife Encounters":_m(themes=("wildlife",)),

    # ----- Activities & User Appeal -----------------------------------------------
    "Cycle Trails":       _m(subtype=("cycle_trail",), themes=("adventure",), intensity="moderate"),
    "Cycling":            _m(themes=("adventure",), is_activity=True),
    "Family Friendly":    _m(themes=("family",), suitability={"families": True}),
    "Fishing":            _m(themes=("adventure",), is_activity=True),
    "Hidden Gems":        _m(themes=("remote",)),
    "High Country":       _m(themes=("alpine", "remote", "scenic")),
    "Lookouts":           _m(subtype=("lookout",), themes=("scenic",)),
    "Off The Beaten Track": _m(themes=("remote",)),
    "Photography Spots":  _m(themes=("scenic",)),
    "Picnic Areas":       _m(subtype=("picnic_spot",), themes=("family", "relaxation"),
                             suitability={"families": True},
                             accessibility={"facilities_level": "basic"}),
    "Quiet Spots":        _m(themes=("remote", "relaxation")),
    "Remote Locations":   _m(themes=("remote",)),
    "Sunrise Spots":      _m(themes=("scenic",), time_of_day="morning"),
    "Sunset Spots":       _m(themes=("scenic",), time_of_day="evening"),
    "Surfing":            _m(themes=("coastal", "adventure"), is_activity=True, intensity="demanding"),
    "Swimming Spots":     _m(themes=("coastal", "water", "family"), suitability={"families": True}),

    # ----- Accommodation / Overnight (out of v1 place scope) ----------------------
    "Backcountry Huts":   _m(is_accommodation=True,
                             notes="DOC backcountry huts — accommodation content_kind."),
    "Camping":            _m(is_accommodation=True),
    "Campsites":          _m(is_accommodation=True),
    "DOC Campsites":      _m(is_accommodation=True),  # not in live taxonomy but present in primary prompt
    "Campgrounds":        _m(is_accommodation=True),  # not in live taxonomy but present in primary prompt
    "Freedom Camping":    _m(is_accommodation=True,
                             notes="Self-contained vehicle camping under the Freedom Camping Act."),

    # ----- Secondary-only attribute tags ------------------------------------------
    "4WD Access":         _m(accessibility={"requires_4wd": True}, intensity="moderate"),
    "4WD Routes":         _m(subtype=("scenic_drive",), accessibility={"requires_4wd": True},
                             intensity="moderate", themes=("adventure",)),
    "Biosecurity Access": _m(accessibility={"biosecurity_required": True}, seasonality="weather_sensitive",
                             notes="Often kauri-dieback or pest-free island access requirements."),
    "Boat Access":        _m(accessibility={"requires_boat": True}, themes=("remote",)),
    "No Facilities":      _m(accessibility={"facilities_level": "none"}),
    "Rough Terrain":      _m(intensity="demanding"),
    "Seasonal Access":    _m(seasonality="weather_sensitive"),
    "Steep Tracks":       _m(intensity="demanding", accessibility={"steps_present": True}),
    "Swing Bridges":      _m(notes="Suspension footbridges — common on DOC tracks. Not a primary filter dimension."),
    "Unmarked Track":     _m(intensity="demanding", accessibility={"unmarked": True}),

    # ----- Location / meta tags ---------------------------------------------------
    "Auckland":           _m(is_location=True,
                             notes="Tag taxonomy mixes locations with features. Location tags should set "
                                   "location_normalized.region rather than themes."),
    "Top 5":              _m(is_meta=True,
                             notes="Editorial classification, not a feature tag."),
}


# === Lookup helpers ===============================================================

def _normalize(s: str) -> str:
    """Normalize for case- and diacritic-insensitive comparison."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.strip().casefold()


_NORMALIZED_INDEX: dict[str, str] = {_normalize(k): k for k in TAG_MAPPINGS}


def for_tag(name: str) -> Optional[TagMapping]:
    """Look up a tag by name (case- and diacritic-insensitive). Returns None if unmapped."""
    canonical = _NORMALIZED_INDEX.get(_normalize(name))
    return TAG_MAPPINGS.get(canonical) if canonical else None


def all_mapped_tags() -> list[str]:
    return sorted(TAG_MAPPINGS.keys())


# === Validation against live Sanity ===============================================

def diff_against_live(client: Optional[SanityClient] = None) -> tuple[set[str], set[str]]:
    """Compare TAG_MAPPINGS keys against live Sanity tag names.

    Returns (live_unmapped, defined_not_in_live):
    - live_unmapped: tags in Sanity that have no entry in TAG_MAPPINGS
    - defined_not_in_live: keys in TAG_MAPPINGS that don't exist in live Sanity
    """
    client = client or SanityClient()
    live_tags = client.query("*[_type == 'tag']{name}") or []
    live_names = {t["name"] for t in live_tags if t.get("name")}
    live_normalized = {_normalize(n): n for n in live_names}
    defined_normalized = set(_NORMALIZED_INDEX.keys())

    unmapped_in_live = {
        live_normalized[n] for n in live_normalized.keys() - defined_normalized
    }
    defined_not_in_live = {
        _NORMALIZED_INDEX[n] for n in defined_normalized - live_normalized.keys()
    }
    return unmapped_in_live, defined_not_in_live


# === CLI =========================================================================

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    print(f"TAG_MAPPINGS contains {len(TAG_MAPPINGS)} entries.\n")

    print("Validating against live Sanity tag taxonomy...\n")
    unmapped_in_live, defined_not_in_live = diff_against_live()

    if unmapped_in_live:
        print(f"⚠ {len(unmapped_in_live)} live tag(s) have NO mapping yet:")
        for n in sorted(unmapped_in_live):
            print(f"    - {n!r}")
    else:
        print("✓ Every live Sanity tag has a mapping.")

    print()
    if defined_not_in_live:
        print(f"ℹ {len(defined_not_in_live)} mapping(s) defined for tags NOT in live taxonomy "
              f"(may be from primary-prompt vocabulary, kept for completeness):")
        for n in sorted(defined_not_in_live):
            entry = TAG_MAPPINGS[n]
            note = f" — {entry.notes}" if entry.notes else ""
            print(f"    - {n!r}{note}")

    # Quick coverage stats
    print()
    print("Coverage summary across mappings:")
    has_subtype = sum(1 for m in TAG_MAPPINGS.values() if m.place_subtype_hints)
    has_themes = sum(1 for m in TAG_MAPPINGS.values() if m.themes)
    has_intensity = sum(1 for m in TAG_MAPPINGS.values() if m.intensity_hint)
    has_seasonality = sum(1 for m in TAG_MAPPINGS.values() if m.seasonality_hint)
    has_accessibility = sum(1 for m in TAG_MAPPINGS.values() if m.accessibility)
    classifiers = {
        "is_meta_tag": sum(1 for m in TAG_MAPPINGS.values() if m.is_meta_tag),
        "is_location_tag": sum(1 for m in TAG_MAPPINGS.values() if m.is_location_tag),
        "is_activity_tag": sum(1 for m in TAG_MAPPINGS.values() if m.is_activity_tag),
        "is_accommodation_tag": sum(1 for m in TAG_MAPPINGS.values() if m.is_accommodation_tag),
    }
    print(f"  with place_subtype hint:  {has_subtype}")
    print(f"  with themes:              {has_themes}")
    print(f"  with intensity hint:      {has_intensity}")
    print(f"  with seasonality hint:    {has_seasonality}")
    print(f"  with accessibility flags: {has_accessibility}")
    for k, v in classifiers.items():
        print(f"  {k}: {v}")
