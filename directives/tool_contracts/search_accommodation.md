# Tool contract — `search_accommodation`

> **What this is:** Operational reference for the `search_accommodation` tool. Read this before modifying the tool, debugging a tool call, or extending its capabilities. Companion to [`../accommodation_audit_2026-04-27.md`](../accommodation_audit_2026-04-27.md) (frozen snapshot of the underlying Sanity data).
> **Captured:** 2026-04-27 evening, when the tool first shipped.

---

## What it does

Queries Sanity's `_type == "accommodation"` documents for places to stay, applies in-memory scoring (review weight + book-now boost + Gold Medal boost − distance penalty), returns ranked results with photos, contact details, and a `book_link` to `tripideas.nz/<slug>`.

**No external Bookit API call.** All data comes from Sanity, which has the Bookit-synced fields cached. This tool is the v1 way to surface accommodation in chat without building a Bookit adapter (Sprint 5 work).

## When to call it

| User says... | Tool to use |
|---|---|
| *"Where to stay in Queenstown?"* | `search_accommodation` ✓ |
| *"Find me a holiday park near Picton"* | `search_accommodation` ✓ |
| *"Gold Medal places in Canterbury"* | `search_accommodation` ✓ |
| *"Cheap backpackers in Auckland"* | `search_accommodation` ✓ |
| *"Walks near Wellington"* | `search_places` (NOT this one) |
| *"Plan a 3-day trip"* | `build_trip_itinerary` |

The system prompt at `backend/system_prompt.py` enforces this separation. Never mix accommodation and place searches — they query different Sanity doc types.

## Input schema (JSON)

All fields are optional. The chat orchestrator passes whatever subset matches the user's intent.

| Field | Type | Notes |
|---|---|---|
| `region` | string | e.g. "Otago", "Canterbury". Resolved internally to a coordinate centroid via [`execution/registry/regions.py`](../../execution/registry/regions.py) `REGION_CENTROIDS`, then applied as a `near` filter with `region_radius_km` (default 80km). |
| `subRegion` | string | Resolved via [`execution/registry/settlements.py`](../../execution/registry/settlements.py) — page-coordinate means OR direct page match. |
| `town` | string | Substring match against the `town` field on the doc (Sanity `match` operator). 195/220 docs have `town` populated. |
| `near` | `{lat, lng, radius_km}` | Direct lat/lng anchor. Overrides `region` / `subRegion` resolution if provided. |
| `region_radius_km` | number | Radius applied when region/subRegion is resolved to a centroid. Default 80. |
| `accommodation_types` | `list[enum]` | Any-match filter. Enum: `Budget/Backpackers`, `Cabins/Cottages/Units/Houses`, `Caravan Parks & Camping`, `Chalets/Villas/Cottages`, `Lodge`, `Motel`, `Studio/Apartments`. |
| `min_review_rating` | float (1-5) | Excludes properties below this `reviewAverageRating`. |
| `min_review_count` | int | Excludes lightly-reviewed properties. Use with `min_review_rating`. |
| `star_rating_min` | int (1-5) | Excludes properties below this `starRating`. **Also excludes the ~55% of docs with no star rating**, since `starRating == 0` for unrated. |
| `bookable_only` | bool | If true, filters to docs where `bookNowFlag == true`. |
| `hot_deals_only` | bool | Filters to `isHotDealActive == true`. |
| `gold_medal_only` | bool | Filters to `isGoldMedalToday == true`. |
| `limit` | int (1-30) | Default 10. |

## Output shape

```python
{
  "ok": true,
  "query_echo": {...},          # echoes the resolved input (incl. resolved near filter)
  "count": 17,                  # total post-filter, before slice to limit
  "results": [
    {
      "sanity_doc_id": "accommodation-bookit-100811",
      "title": "Hampshire Holiday Parks - Queenstown Lakeview",
      "town": "Queenstown",
      "address": "287A Okuti Valley Road, Little River Canterbury 7591 New Zealand",
      "coords": {"_type": "geopoint", "lat": -45.03, "lng": 168.66},
      "accommodation_type": "Caravan Parks & Camping",
      "accommodation_subtype": "B&B/Guesthouse",  # may be null
      "star_rating": 4,             # 0 = unrated
      "review_average": 4.2,        # 0 = unreviewed
      "review_count": 39,
      "main_image_url": "https://images.bookeasy.com.au/website/images/bookit/...",
      "gallery_image_urls": ["https://...", "https://..."],   # up to 4
      "book_now_available": true,   # isActive AND bookNowFlag
      "is_gold_medal": true,        # isGoldMedalToday (changes daily)
      "is_hot_deal": false,
      "point_of_difference": "Nature based campsite",
      "cancellation_policy": "If Cancelled greater than 3 days...",
      "arrival_time": "14:00",
      "departure_time": "12:00",
      "facilities": ["Accessible Facilities", "..."],
      "contact": {"email": "...", "phone": "...", "website": "..."},
      "slug": "hampshire-holiday-parks-queenstown-lakeview-89136",
      "book_link": "https://tripideas.nz/hampshire-holiday-parks-queenstown-lakeview-89136",
      "distance_km": 0.4,           # populated only when near/region filter applied
      "score": 4.9,
      "match_reasons": ["within 0.4km of target", "4.2/5 from 39 guests", "4-star rated", "Gold Medal property"]
    },
    ...
  ],
  "facets": {
    "by_type": {"Caravan Parks & Camping": 17},
    "by_town": {"Christchurch City South": 4, "Kaikoura": 2, ...},
    "bookable_count": 12,
    "gold_medal_count": 17,
    "hot_deal_count": 0
  },
  "normalization_notes": [
    "region 'Canterbury' resolved to centroid (-43.530, 172.640)",
    "GROQ pre-filter returned 17 candidate accommodation docs"
  ],
  "latency_ms": 437
}
```

## Critical data caveats

These shape both what the tool can do and what the chat should say. They came from the live data audit in `directives/accommodation_audit_2026-04-27.md`.

### 1. The pool is heavily skewed to caravan parks (94%)

Across all 220 accommodation docs in Sanity:

| Type | Count |
|---|---|
| Caravan Parks & Camping | **207** |
| Budget/Backpackers | 6 |
| Motel | 3 |
| Studio/Apartments | 1 |
| Chalets/Villas/Cottages | 1 |
| Lodge | 1 (Last Light Lodge in Tuatapere, Southland) |
| Cabins/Cottages/Units/Houses | 1 |

If the user asks for *"a motel in Picton"* and the type filter returns 0, **the chat should retry without the type filter** and surface a brief honest note ("the Tripideas-listed properties in Picton are all holiday parks; here are the top-rated ones"). The system prompt instructs this explicitly.

### 2. There is no live numeric pricing in Sanity

`bestPriceAvailable` is a **boolean flag** (probably "is best-price-available shown on the website?"), not a price number. The tool deliberately does not expose it as a price input/output.

For real numeric pricing per date range, an actual Bookit API call is needed (Sprint 5). For v1, surface `book_link` to `tripideas.nz/<slug>` so the user can see live pricing on Tripideas's existing booking flow.

### 3. Accommodation has NO region/subRegion ref in Sanity

Pages reference `subRegion` → `region`. Accommodation does not. The only geographic fields are `town` (string, 195/220 populated) and `coordinates` (219/220).

For region-based queries, the tool resolves the region name to a centroid coord via `regions.region_centroid()` and applies a 80km radius. Same for subRegion via `settlements.resolve()`. This is approximate — Otago centroid is Queenstown, so "accommodation in Otago" really means "within 80km of Queenstown."

### 4. Photo URLs come from Bookit, not Sanity image refs

Both `mainImage` (Sanity image ref) and `bookitMainImageUrl` (direct CDN URL) exist. The tool uses `bookitMainImageUrl` and `bookitGalleryUrls` (arrays of `//images.bookeasy.com.au/...` URLs, prefixed to `https://` by `_https()`). These are immediately usable in `<img src="...">`; the Sanity refs would require Sanity's image URL builder.

### 5. `isGoldMedalToday` is a daily-changing flag

Don't confuse with `isGoldMedal` (the static historical flag). The "today" version is what surfaces in chat. If a user comes back tomorrow expecting the same Gold Medal list, it might differ.

### 6. `starRating == 0` means unrated, not "0 stars"

~55% of docs have no official star rating. Filtering `star_rating_min >= 1` excludes ALL of them. Document this if expanding the schema.

## Scoring algorithm (in-memory, deterministic)

Defined in [`execution/tools/search_accommodation.py`](../../execution/tools/search_accommodation.py):

```
score = 1.0 (base)
       + max(0, 1 - distance_km/radius_km) * 1.0   if near filter applied
       + 0.5                                        if accommodation_type matches filter
       + min(2.0, review_avg * log10(count+1) * 0.5)  weighted review boost
       + star_rating * 0.1                          (0 if unrated)
       + 0.4                                        if bookNowFlag
       + 0.5                                        if isGoldMedalToday
       + 0.3                                        if isHotDealActive
```

Sort descending, slice to `limit`. Match-reasons are accumulated as the score is computed, so they reflect the actual contributions.

## How to extend

### Adding a new filter

1. Add field to `SearchAccommodationInput` dataclass in `execution/tools/search_accommodation.py`
2. Add corresponding GROQ clause inside the build-up loop in `search_accommodation()`
3. Add scoring contribution if relevant
4. Update the Anthropic schema in `backend/tool_definitions.py` `SEARCH_ACCOMMODATION_SCHEMA`
5. Update the input unpacker `_make_search_accommodation_input` in `tool_definitions.py`
6. Update this contract doc

### Calling from build_day_itinerary / build_trip_itinerary

Currently neither itinerary builder calls `search_accommodation` automatically. To weave lodging into multi-day plans, future Sprint 5 work would:
- After day plan is composed, optionally call `search_accommodation(near=<day-end-coords>, limit=3)`
- Add a `lodging_gap` slot type alongside `place`/`travel_gap`/`meal_gap`
- Surface 1-3 options per day at the day's last anchor settlement

This was deferred — currently the chat orchestrator can do this manually via tool composition.

## Sample tool calls (verified live, 2026-04-27)

| User utterance | Resolved args | Result count |
|---|---|---|
| *"Where can I stay in Queenstown?"* | `{town: "Queenstown", min_review_rating: 4.0, min_review_count: 5, limit: 3}` | 3 (all caravan parks, all Gold Medal) |
| *"Gold Medal places in Canterbury"* | `{region: "Canterbury", gold_medal_only: true, limit: 10}` | 17 (mostly Christchurch + Kaikoura) |
| *"Find me a Lodge in Otago"* | `{region: "Otago", accommodation_types: ["Lodge"]}` | 0 — only 1 Lodge in NZ, in Southland. Chat should retry without type filter. |

## Future improvements (post-v1)

- **Sprint 5 — real Bookit API integration:** live availability for specific dates, dynamic pricing, programmatic booking flow. The tool's input schema can be extended with `check_in_date` / `check_out_date` / `guests` fields that route through the real Bookit API.
- **Soft type fallback:** if `accommodation_types` filter returns 0, the tool itself could automatically retry without it and flag the relaxation in `normalization_notes`. Currently the chat handles this at the orchestrator level.
- **Better region centroids:** the current `REGION_CENTROIDS` dict picks "most touristically central" coords (e.g. Queenstown for Otago). For better coverage, compute centroids from actual page distributions in each region.
