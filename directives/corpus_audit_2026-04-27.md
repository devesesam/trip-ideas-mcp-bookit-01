# Corpus Audit — 2026-04-27

> **What this is:** A snapshot of the live Tripideas Sanity corpus state at audit time, captured from running [../execution/audit/aimetadata_quality.py](../execution/audit/aimetadata_quality.py) and [../execution/inspect_corpus.py](../execution/inspect_corpus.py) against `production` dataset.
> **Why it exists:** Several plan assumptions in the original brief and `hey-this-is-a-wobbly-squirrel.md` plan turned out to be wrong (or imprecise) when measured against the live corpus. This document is the source of truth for what's actually in Sanity as of this date, and the gotchas future agents need to know to avoid repeating dead-end queries.
> **When to update:** After any major Sanity corpus change (full normalization backfill, regenerated metadata, new content types) — write a new dated audit alongside this one rather than overwriting; the historical record matters for diffing.

---

## TL;DR

- **Sanity corpus is bigger than the original "1000+" estimate**: 1495 pages, 2194 routes (GPS tracks), 220 accommodation, 170 posts, plus reference docs (17 regions, 65 subRegions, 102 tags).
- **Field name is `aiMetadata`, not `metadata`.** The rich place metadata we'd been discussing lives here.
- **`aiMetadata` is stored as a JSON-encoded string** on `page` docs (NOT a structured Sanity object) — must be `json.loads()` on read.
- **Coverage is 1315/1495 (87.96%) populated** for pages. **Zero coverage on `route`, `accommodation`; 1/170 on `post`.**
- **Parse-error rate is 15.6% (205 of 1315 populated docs)**. Every failure is in length range 3500–4499 chars. Below 3500: 100% clean. This is **truncation**, almost certainly an upstream output-token cap on the metadata generator.
- **Field-key set is highly stable** (19 keys present on 99.8% of parseable docs).
- **Value types within fields are NOT stable**: 11 of 20 fields have multiple value types across the corpus (string / array / dict / null mixed). Defensive handling required at every read site, OR fed verbatim to an LLM that can interpret across shapes.
- **GROQ gotcha**: `defined(aiMetadata)` returns FALSE for these populated string fields. Use `length(aiMetadata) > 0` to count or filter on populated docs.

---

## Document type breakdown (live counts)

```
route                    2194    (GPS tracks; no aiMetadata; no tags)
page                     1495    (place articles — primary content for v1)
accommodation             220    (Bookit-integrated lodging; rich top-level fields, no aiMetadata)
post                      170    (blog posts; partial tag coverage)
redirect                  148
tag                       102    (taxonomy: controlled vocabulary as Sanity docs)
subRegion                  65    (sub-region reference data)
media.tag                  35
region                     17    (region reference data)
customPage                 13
author                      3
about, home, islands, resources    1 each
```

### Implications

- **`page` is the primary content type for v1** — that's what the planning_attributes work targets.
- **`accommodation`** is already populated with Bookit data (`bookitOperatorId`, `bookNowFlag`, `coordinates`, `reviewAverageRating`, `starRating`, `hours`, etc.) — Sprint 4 (Bookit) is partially pre-built, not from-scratch.
- **`route`** is GPS tracks. We tested every plausible field name (`routes`, `tracks`, `walks`, `relatedRoutes`, `linkedRoutes`, etc.) on `page` — **zero pages reference routes via any of these field names**. Routes are either linked some other way (slug match? geographic match? a field name we didn't try) or are a separate data product not used in planning. Treat as out-of-scope until clarified.
- **`tag`** is a 102-doc taxonomy stored as Sanity docs. The `tags` field on a page is an array of REFERENCES to these docs. Dereference with `tags[]->name` (NOT `tags[]->title` — tag docs use `name`).

---

## `aiMetadata` deep audit (page corpus)

### Coverage

```
                     populated   coverage
page                 1315/1495    87.96%
post                    1/170     0.59%
route                   0/2194    0%
accommodation           0/220     0%
```

The 1 post with aiMetadata is likely a stray; verify before relying on it.

### Storage shape

`aiMetadata` is stored as a **JSON-encoded string** on the page document — NOT a Sanity object. Length range observed: 1500–4499 characters. Always parse with `json.loads()` after reading.

### Parse-error rate: 15.6% (205 of 1315)

```
Length range    Total docs   Failures    Failure rate
1500–1999            8            0         0%
2000–2499           88            0         0%
2500–2999          317            0         0%
3000–3499          414            0         0%
3500–3999          362          108        29.8%
4000–4499          126           97        77.0%
```

**100% of failures are in the 3500–4499 char range. Below 3500 = always parseable.**

### Truncation evidence (from sample failure tails)

```
Rakiura Stewart Island       (3920 chars):  ..."People comfortable with backcountry hut and campsite stays", "  ← cut mid-array, no closing ]
Wellington Botanic Gardens   (4153 chars):  ..."Ōtari Native Botanic Gardens", "Mount Victoria", "Bolton Street Cemetery"  ← cut mid-array, no closing
Aoraki Mount Cook            (3728 chars):  ..."primary_type": "h  ← cut mid-string value
Kauri Coast                  (4148 chars):  ..."exposed": false, "steps_present  ← cut mid-key
Te Ara Tahuna Pathway        (3885 chars):  ..."primary_type": "walk",  ← trailing comma, expecting next property
Dove-Myer Robinson Park      (3891 chars):  ..."type": "suburb" }, { "name": "Judges Bay" ... { "name": "Downtown  ← cut mid-string value
```

This is a clear upstream output-token cap. The metadata-generation pipeline appears to have been run with a low `max_tokens` setting (somewhere around 1000 tokens, which roughly maps to ~4000 chars of JSON). The fix is in the upstream script (raise `max_tokens` and/or enforce JSON mode), not the Sanity schema.

### Field key set (99.8% stable on 1110 parseable docs)

Every parseable doc has these 19 keys:

```
title, description, keywords, location, coordinates, attractions, transportation,
activities, historical_significance, amenities, accessibility, dog_friendly, tags,
best_time_to_visit, local_tips, nearby_places, ideal_for, water_safety_notes,
track_trail_details
```

One outlier doc carries an extra `additional_track` key. Ignore as outlier.

### Value-type instability per field

Stable fields (one type across all 1108 docs):

| Field | Type |
|---|---|
| `title` | str |
| `description` | str |
| `keywords` | list[str] |
| `attractions` | list[str] |
| `activities` | list[str] |
| `tags` | list[str] |
| `coordinates` | dict (with `_type`, `lat`, `lng`) |

Mixed-type fields (require defensive handling or LLM-mediated interpretation):

| Field | Type distribution (count of 1108) |
|---|---|
| `track_trail_details` | dict 897 / str 101 / null 70 / list[str] 26 / list[dict] 6 / empty 8 |
| `nearby_places` | list[dict] 588 / list[str] 497 / empty 18 / dict 5 |
| `accessibility` | list[str] 619 / str 483 / empty 5 / dict 1 |
| `historical_significance` | str 751 / null 168 / list[str] 103 / empty 86 |
| `local_tips` | list[str] 744 / str 364 |
| `best_time_to_visit` | str 867 / list[str] 236 / empty 4 / null 1 |
| `amenities` | list[str] 940 / str 164 / empty 4 |
| `water_safety_notes` | str 1050 / list[str] 28 / null 26 / empty 4 |
| `ideal_for` | list[str] 1060 / str 42 / empty 3 / null 3 |
| `transportation` | list[str] 1076 / str 32 |
| `dog_friendly` | str 1107 / dict 1 |
| `location` | dict 1083 / **list[dict] 25** |

### Notable subset: `location` as list[dict] (25 docs)

25 pages have `location` as a *list of dicts* rather than a single dict. These are likely **region overview pages or multi-location guides** — different content shape from single-place articles. Worth a follow-up audit: pull them and see if they form a distinct content_kind (e.g., `region_guide`).

### Most variable filter-relevant field: `track_trail_details`

This is the field we expected to lift `physical_intensity` and `duration_band` from. It's the most chaotic in the corpus:

```
dict          897    (the structured form with track_name, primary_type, difficulty, duration_text, etc.)
str           101    (free-form sentence like "No official DOC track at...")
null           70    (field present but explicitly null)
list[str]      26    (rare — some kind of list of notes)
list[dict]      6    (multi-track docs)
empty           8
```

**Implication**: extracting `physical_intensity` reliably requires either (a) treating `track_trail_details` as one of several signals (not the only one), with fallback to LLM inference from `description` + `activities` + tags; OR (b) re-generating the metadata with a tighter prompt that always produces a dict (and explicit empty fields rather than null/string fallbacks).

---

## Reference data structure

### Region / subRegion (clean, usable as-is)

`region` doc (17 total): `{ name, slug, maori, vector }`. Examples: `Golden Bay` (maori: `Mohua`), `East Cape` (maori: `Tūranganui-a-Kiwa`), `Otago`, `Southland`, `Auckland`, etc.

`subRegion` doc (65 total): `{ name, slug, region: <ref> }`. Examples: `Hauraki Gulf Islands` (→ Auckland), `Central Westland`, `South Otago`, `Dunedin`.

Page docs reference `subRegion` → `region` cleanly. GROQ:
```groq
*[_type == "page"]{
  title,
  "region": subRegion->region->name,
  "subRegion": subRegion->name
}
```

**Implication**: don't build a parallel settlement registry. The Sanity hierarchy IS the registry. Build a lookup from subRegion-name → coordinates (mean of the lat/lng of pages in that subRegion) for `base_location` geocoding.

### Tag taxonomy (102 live docs)

Pulled the full live list. The taxonomy is the union of the two prompt vocabularies plus extras and known duplicates.

**Tags in live taxonomy not in either prompt:**
- `Glaciers`, `Surfing`, `Waterfalls`, `Parks`, `City Walks`, `Top 5`

**Live duplicates / spelling drift to flag with Douglas:**
- `Historic Sites` AND `Historical Sites`
- `Heritage Trails` AND `Historical Trails`
- `Scenic Drive` AND `Scenic Drives`
- `Te Araroa` AND `Te Araroa Trail`

**Tag mapping rule**: dereference via `tags[]->name`, then case-insensitive + diacritic-insensitive match against the canonical mapping in [../execution/normalize/tag_mapping.py](../execution/normalize/tag_mapping.py) (when written). Treat duplicates above as synonyms unless Douglas confirms semantic difference.

**Note**: `Auckland` appears as a tag — taxonomy mixes feature/attribute tags with location tags. Tag mapping must distinguish these so `Auckland-tag → location reference` rather than `→ theme`.

### Page top-level shape (Te Hakapureirei Beach as canonical example)

```
_id, _type, _createdAt, _updatedAt, _rev, _system,
title           (str) — "Te Hakapureirei Beach"
slug            (dict, slug)
body            (list, PortableText blocks)
mainImage       (dict, image asset reference)
coordinates     (dict, geopoint with lat/lng)  ← root-level, separate from aiMetadata.coordinates
seo             (dict: { description, keywords })
tags            (list of REFERENCES to `tag` docs)
subRegion       (REFERENCE to `subRegion` doc)
author          (REFERENCE to `author` doc)
aiMetadata      (str — JSON-encoded; needs json.loads to use)
```

Two coordinate sources: `page.coordinates` (root, structured Sanity geopoint) and `aiMetadata.coordinates` (parsed from JSON). They should match; use root for ground-truth, treat aiMetadata.coordinates as advisory.

---

## GROQ gotchas (lessons from this audit)

### 1. `defined(field)` does NOT return true for populated string fields here

```groq
count(*[_type == "page" && defined(aiMetadata)])         → 3       (wrong / surprising)
count(*[_type == "page" && length(aiMetadata) > 0])      → 1315    (correct)
```

Confirmed identical behaviour across `perspective=published`, `perspective=raw`, `perspective=drafts`. Cause not understood — possibly a Sanity Studio quirk with how the field was migrated or how strings vs. structured types interact with `defined()`.

**Rule**: when querying for the presence of `aiMetadata` (or any string-encoded JSON field), use `length(field) > 0`. Reserve `defined()` for object/reference fields.

### 2. Tag dereferencing uses `name`, not `title`

The `tag` doc type has a `name` field, not `title`. So:
```groq
tags[]->name        ← correct
tags[]->title       ← always returns null
```

### 3. `object::keys()` is not available in this GROQ version

To inspect what keys are present in an object field, fetch the object and inspect client-side (Python, JS, etc.) rather than projecting keys in GROQ.

### 4. `list[empty]` discrimination

`field: []` and `field: null` are distinct shapes — handle both. The audit found 4–86 docs with empty arrays per field, on top of separate counts for null. Defensive parsing should treat both as "absent".

---

## Implications for the build plan

Updating [../../../../.claude/plans/hey-this-is-a-wobbly-squirrel.md](../../../../.claude/plans/hey-this-is-a-wobbly-squirrel.md) accordingly:

1. **Field name correction**: every reference to `metadata` field should be `aiMetadata`. The `planning_attributes` we add becomes a sibling to `aiMetadata` (or a new sub-field — TBD with Douglas).
2. **Plan still works on the 1110 parseable docs.** v1 normalization can proceed without waiting on the truncated 205.
3. **Sprint 1 must include "fix or skip" decision for the 205 truncated docs** before the full backfill. Either Douglas re-runs the upstream metadata script with a higher token cap, or we mark them as `confidence.overall < 0.3` and leave them out of `search_places` results.
4. **Settlement registry plan changes**: don't build a separate registry. Use Sanity's `subRegion` → `region` graph plus a coordinate-mean lookup from pages within each subRegion.
5. **Tag mapping must consume the live 102-doc taxonomy, not the prompt vocabularies.** The prompts were a starting point; the Sanity tag list is authoritative.
6. **Accommodation has Bookit data already — Sprint 4 is mostly exposing it, not from-scratch integration.**
7. **Routes-pages relationship is unresolved.** Treat as out-of-scope for v1 unless Douglas describes how they connect.

---

## Open follow-ups (in rough priority order)

1. **205 truncated aiMetadata docs**: produce a CSV of doc IDs + titles for Douglas to re-run through the metadata generator with a higher token cap. Path: would live at `.tmp/truncated_aimetadata_docs.csv`.
2. **Confirm truncation cause**: is it the Sanity field, the upstream script, or the LLM token cap? Need access to the metadata-generation pipeline to confirm.
3. **The 25 `location: list[dict]` pages**: pull them and confirm whether they're region overviews / multi-place guides (a different `content_kind`).
4. **Routes-pages connection**: does Douglas know how routes link to articles? Worth one direct question.
5. **Tag taxonomy duplicates**: confirm with Douglas whether `Historic Sites`/`Historical Sites`, `Heritage Trails`/`Historical Trails`, `Scenic Drive`/`Scenic Drives`, `Te Araroa`/`Te Araroa Trail` are semantic duplicates or distinct.

---

## Reproducing this audit

The audit scripts live at:
- [../execution/inspect_corpus.py](../execution/inspect_corpus.py) — top-level discovery (doc types, counts, sample shapes)
- [../execution/inspect_aimetadata.py](../execution/inspect_aimetadata.py) — quick aiMetadata coverage check
- [../execution/audit/aimetadata_quality.py](../execution/audit/aimetadata_quality.py) — full corpus parse-error and value-type audit (~30 seconds against ~1300 docs)

Run from project root with `.env` configured:
```bash
python execution/audit/aimetadata_quality.py
```
