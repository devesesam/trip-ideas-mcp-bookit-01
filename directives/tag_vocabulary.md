# Tag Vocabulary — Tripideas.nz

> **Source:** Tag prompts shared by user 2026-04-27 from existing Sanity Studio tagging automation.
> **Purpose:** Authoritative tag list for `planning_attributes` normalization. Every tag we map in [execution/normalize/tag_mapping.py](../execution/normalize/tag_mapping.py) must come from this vocabulary.

---

## Where these tags live in Sanity

> **Verification needed (Sprint 0 Task 6):** Confirm against a live query — earlier samples we reviewed showed only one `tags` field per doc. The two prompts may both write to the same field, or to different fields.

User indicates:
- **Primary tags** (categorized, max 6 per article) → root-level `tags` field on Sanity doc
- **Secondary tags** (flat, ~85 entries, attribute-rich) → `metadata.tags` inside the existing `metadata` object

---

## Primary prompt (verbatim)

> Used by the existing automation to populate root-level `tags`. Tightly categorized with per-category caps.

```
You are an expert, intelligent Sanity Editor assistant. You will be provided
with an article from my website about Travel Guides. Your job is to create a
list of Tags that can be added in to Sanity Studio as hidden metadata that
makes it easier for AI searches to find this article webpage. You must only
assign tags from this list below. When tagging articles, be selective.
Max Tags: 6 total

Required:
  1 or 2 from Track Type/Walk Type
  1 or 2 from Natural Feature or Region
Optional: 1–2 more from History, Activities, Ecology, etc.

Category: Track Type/Walk Type (Primary tag group, always 1 or 2 per article if relevant)
  Alpine Routes, Boardwalks, Cliff Walks, Coastal Walks, Forest Walks, Great Walks,
  Heritage Trails, Hikes, Lakeside Walk, Multi-Day Walks, Night Walks, Scenic Drive,
  Scenic Loops, Short Walks, Te Araroa Trail, Tramps, Urban Walks, Walks

Category: Natural Feature/Landscape Type (Max 2 per article)
  Beaches, Coastal Cliffs, Dark Sky Places, Forests, Fossil Sites, Geological Sites,
  Glacial Lakes, Islands, Lakes, Mountains, Natural Arches, Rainforest, Rivers,
  Sea Caves, Tidal Lagoons, Volcanic Landscapes, Wetlands

Category: Protected Places & Reserves (Optional, 1 max)
  Marine Reserves, National Parks, Regional Parks, Scenic Reserves

Category: Historical & Cultural (Optional, 1–2 max)
  Architecture, Art Galleries, Cultural History, Gold Mining History,
  Heritage Precincts, Historic Sites, Local Legends & Myths, Māori History,
  Memorials, Mining History, Museums, NZ History (if another historic reference
  is used, do not apply 'NZ History'), Public Art and Sculpture

Category: Wildlife & Ecology (Optional, 1 max)
  Bird Sanctuaries, Botanic Gardens, Conservation Projects, Ecological Restoration,
  Exotic Forests, Kauri Forests, Podocarp Forests, Restoration Sites,
  Wildlife Encounters

Category: Activities & User Appeal (optional, max 2)
  Cycle Trails, Cycling, Family Friendly, Fishing, Hidden Gems, High Country,
  Lookouts, Off The Beaten Track, Photography Spots, Quiet Spots, Remote Locations,
  Sunrise Spots, Sunset Spots, Swimming Spots

Category: Accommodation/Overnight (Optional, max 1)
  Backcountry Huts, DOC Campsites, Campgrounds

Output ONLY JSON. No explanation, no backticks.
```

---

## Secondary prompt (verbatim)

> Used by the existing automation to populate `metadata.tags`. Flat list with attribute-style and access-style tags the primary list lacks.

```
You are an expert, intelligent Sanity Editor assistant. You will be provided
with an article from my website about Travel Guides. Your job is to create a
list of Tags that can be added in to Sanity Studio as hidden metadata that
makes it easier for AI searches to find this article webpage. You must only
assign tags from this list, you can use as many or as few as you think is
appropriate/relevant.

Walks, Hikes, Tramps, Great Walks, Short Walks, Multi-Day Walks, Urban Walks,
Forest Walks, Coastal Walks, Boardwalks, Scenic Loops, Alpine Routes, Scenic Drive,
Beaches, Lakes, Rivers, Mountains, Islands, Wetlands, Rainforest, Forests,
Volcanic Landscapes, Glacial Lakes, Sea Caves, Natural Arches, Geological Sites,
Fossil Sites, Coastal Cliffs, Tidal Lagoons, National Parks, Regional Parks,
Scenic Reserves, Marine Reserves, Dark Sky Places, Historic Sites, Mining History,
Gold Mining History, Cultural History, Maori History, Heritage Precincts, Museums,
Art Galleries, Architecture, Memorials, Historical Trails, NZ History,
Public Art and Sculpture, Te Araroa Trail, Bird Sanctuaries, Wildlife Encounters,
Conservation Projects, Restoration Sites, Ecological Restoration, Fishing,
Botanic Gardens, Kauri Forests, Podocarp Forests, Exotic Forests, 4WD Routes,
4WD Access, Unmarked Track, Boat Access, Camping, Freedom Camping, Campsites,
Family Friendly, Picnic Areas, Swimming Spots, Lookouts, Photography Spots,
High Country, Quiet Spots, Remote Locations, No Facilities, Seasonal Access,
Biosecurity Access, Swing Bridges, Steep Tracks, Rough Terrain, Cycling,
Cycle Trails, Sunrise Spots, Sunset Spots, Night Walks, Heritage Trails,
Local Legends & Myths, Hidden Gems, Off The Beaten Track, Cliff Walks,
Lakeside Walk, Backcountry Huts, Beech Forests

Output ONLY JSON. No explanation, no backticks.
```

---

## Inconsistencies between the two vocabularies

These need attention during tag mapping:

| Issue | Primary | Secondary | Notes |
|---|---|---|---|
| Macron in Māori | `Māori History` | `Maori History` | Same concept; mapping must be case-AND-diacritic insensitive |
| Heritage trails | `Heritage Trails` | both `Heritage Trails` AND `Historical Trails` | Treat as synonyms unless Douglas distinguishes |
| Camping/accommodation granularity | `Backcountry Huts`, `DOC Campsites`, `Campgrounds` | `Backcountry Huts`, `Camping`, `Freedom Camping`, `Campsites` (no DOC qualifier) | Different categorisation; reconcile in mapping |

---

## Tags exclusive to each vocabulary

**Primary only:**
- `DOC Campsites`
- `Campgrounds`
- `Māori History` (macron form — `Maori History` without macron exists in secondary)

**Secondary only — these are the high-value attributes the primary list misses:**
- Access/terrain: `4WD Routes`, `4WD Access`, `Unmarked Track`, `Boat Access`, `Swing Bridges`, `Steep Tracks`, `Rough Terrain`
- Facilities: `No Facilities`, `Picnic Areas`
- Seasonality/safety: `Seasonal Access`, `Biosecurity Access`
- Camping (non-DOC): `Camping`, `Freedom Camping`, `Campsites`
- Forests: `Beech Forests`
- Other: `Historical Trails`

---

## Mapping outline → `planning_attributes`

Detailed mapping lives in [../execution/normalize/tag_mapping.py](../execution/normalize/tag_mapping.py). Outline:

### → `place_subtype` (single value, primary classification)

- Track Type/Walk Type tags: `Walks` → `walk`; `Tramps`/`Hikes` → `track`; `Boardwalks` → `boardwalk`; `Cliff Walks` → `cliff_walk`; `Coastal Walks` → `coastal_walk`; `Forest Walks` → `forest_walk`; `Lakeside Walk` → `lakeside_walk`; `Heritage Trails`/`Historical Trails` → `heritage_trail`; `Te Araroa Trail` → `te_araroa_section`; `Scenic Drive` → `scenic_drive`; etc.
- Natural Feature: `Beaches` → `beach`; `Lakes`/`Glacial Lakes` → `lake`; `Rivers` → `river`; `Mountains` → `mountain`; `Islands` → `island`; `Sea Caves` → `sea_cave`; `Natural Arches` → `natural_arch`; `Wetlands` → `wetland`; etc.
- Protected Places: `National Parks` → `national_park`; `Regional Parks` → `regional_park`; `Scenic Reserves` → `scenic_reserve`; `Marine Reserves` → `marine_reserve`
- Historical: `Historic Sites` → `historic_site`; `Museums` → `museum`; `Art Galleries` → `art_gallery`; `Memorials` → `memorial`; `Heritage Precincts` → `heritage_precinct`
- Wildlife: `Bird Sanctuaries` → `bird_sanctuary`; `Botanic Gardens` → `botanic_garden`
- Misc: `Lookouts` → `lookout`; `Picnic Areas` → `picnic_spot`

When multiple subtype-eligible tags hit, prefer the primary-prompt category order: Track Type > Natural Feature > Protected Places > Historical & Cultural.

### → `themes` (multi-valued)

- `coastal`: `Beaches`, `Coastal Walks`, `Coastal Cliffs`, `Sea Caves`, `Tidal Lagoons`, `Cliff Walks`
- `forest`: `Forests`, `Forest Walks`, `Rainforest`, `Beech Forests`, `Kauri Forests`, `Podocarp Forests`, `Exotic Forests`
- `alpine`: `Alpine Routes`, `Mountains`, `High Country`
- `water`: `Lakes`, `Rivers`, `Glacial Lakes`, `Lakeside Walk`, `Swimming Spots`, `Wetlands`
- `geological`: `Volcanic Landscapes`, `Geological Sites`, `Fossil Sites`, `Natural Arches`
- `protected_area`: `National Parks`, `Regional Parks`, `Scenic Reserves`, `Marine Reserves`
- `heritage`: `Historic Sites`, `Heritage Precincts`, `Heritage Trails`, `Historical Trails`, `Mining History`, `Gold Mining History`, `NZ History`
- `cultural`: `Cultural History`, `Māori History`, `Maori History`, `Memorials`, `Public Art and Sculpture`, `Architecture`, `Local Legends & Myths`, `Museums`, `Art Galleries`
- `wildlife`: `Bird Sanctuaries`, `Wildlife Encounters`, `Conservation Projects`, `Restoration Sites`, `Ecological Restoration`
- `family`: `Family Friendly`, `Picnic Areas`
- `scenic`: `Lookouts`, `Photography Spots`, `Sunrise Spots`, `Sunset Spots`, `Dark Sky Places`, `Scenic Drive`, `Scenic Loops`
- `remote`: `Hidden Gems`, `Off The Beaten Track`, `Quiet Spots`, `Remote Locations`
- `adventure`: `Tramps`, `Hikes` (when intensity is moderate+), `4WD Routes`, `4WD Access`
- `urban`: `Urban Walks`, `Botanic Gardens`, `Architecture` (when no other historic context)

### → `suitability`

- `Family Friendly` → `families: true`
- (other suitability values inferred from intensity + duration in the normalization prompt — not directly tag-driven)

### → `physical_intensity` (hints)

- `Steep Tracks`, `Rough Terrain`, `Unmarked Track` → `demanding` (or `moderate` if duration is short)
- `Tramps`, `Multi-Day Walks`, `Alpine Routes` → `demanding`
- `Hikes`, `Cliff Walks` → `moderate`
- `Walks`, `Short Walks`, `Boardwalks`, `Urban Walks`, `Lakeside Walk` → `easy`
- `Scenic Drive` → `none` (driving)

### → `accessibility`

- `No Facilities` → `facilities_level: "none"`
- `Picnic Areas` → `facilities_level: "basic"`
- `4WD Access`, `4WD Routes`, `Boat Access`, `Unmarked Track` → `accessibility.requires_special_access: true` (a flag worth adding to the schema if not present)
- `Swing Bridges` → context note (not a primary filter dimension)

### → `seasonality`

- `Seasonal Access` → `weather_sensitive`
- `Biosecurity Access` → `weather_sensitive` + `inference_notes` entry
- `Night Walks`, `Sunrise Spots`, `Sunset Spots`, `Dark Sky Places` → not seasonality, but `time_of_day` (also worth adding)

### Deferred (out of v1 scope — accommodation content)

- `Backcountry Huts`, `DOC Campsites`, `Campgrounds`, `Camping`, `Freedom Camping`, `Campsites`

When metadata for accommodation articles is added later, these tags get a separate mapping for `content_kind: "accommodation"`.

---

## Open mapping questions for Douglas

1. Is `Heritage Trails` (primary) the same as `Historical Trails` (secondary)? Or distinct concepts?
2. Are `Hikes` and `Tramps` distinct (NZ-specific: tramps are usually multi-day, hikes day) or interchangeable in the editorial voice?
3. Should `Te Araroa Trail` be a `place_subtype` (a section of TA), or a `theme`/`feature_tag` (i.e., "this place is part of TA")? Currently treating it as the former.
4. `4WD Access` and `Boat Access` — are these warnings ("you need a 4WD") or attractions ("you can take your 4WD here")? Affects whether they go into `accessibility` or `themes=adventure`.
