# Accommodation corpus audit — 2026-04-27

> **What this is:** Frozen snapshot of the live Tripideas Sanity `_type == "accommodation"` corpus state at audit time. Captured from running [`execution/tools/search_accommodation.py`](../execution/tools/search_accommodation.py) and direct GROQ probes.
> **Why it exists:** Companion to the page-corpus audit ([`corpus_audit_2026-04-27.md`](corpus_audit_2026-04-27.md)). Whereas pages have `aiMetadata` and a region/subRegion taxonomy, accommodation has neither — it has structured Bookit-synced fields and a freeform `town` string. Future agents need this context before changing how `search_accommodation` queries the data.
> **When to update:** When Douglas changes the Bookit feed, adds new accommodation types, or when the type distribution shifts substantially (e.g. if hotels/B&Bs start being added). Write a new dated audit alongside this one rather than overwriting.

---

## TL;DR

- 220 accommodation docs total. **94% are "Caravan Parks & Camping" (207).** Only handfuls of other types: Backpackers (6), Motels (3), Lodges (1), etc.
- All 220 carry the Bookit-synced fields used for ranking: review average/count, gold-medal flag, hot-deal flag, book-now flag, photos, type, contact, slug.
- **No numeric pricing** in Sanity. `bestPriceAvailable` is a boolean (probably "show best-price badge?"), not a price number. Real pricing requires the Bookit API (Sprint 5).
- **No region/subRegion ref.** Accommodation only has `town` (195/220 populated) and `coordinates` (219/220). Region filtering happens via coord proximity in `search_accommodation`.
- Photos are best sourced from `bookitMainImageUrl` + `bookitGalleryUrls` (direct CDN URLs from `images.bookeasy.com.au`), not the Sanity image refs.

---

## Type distribution (the data is heavily skewed)

```
Caravan Parks & Camping       207
Budget/Backpackers              6
Motel                           3
Studio/Apartments               1
Chalets/Villas/Cottages         1
Lodge                           1   (Last Light Lodge, Tuatapere — Southland)
Cabins/Cottages/Units/Houses    1
                              ───
                              220
```

**Implication for the chat:** if the user asks for *"a motel in {anywhere except Auckland or Picton}"*, the tool will return 0 results with the type filter applied. The system prompt at `backend/system_prompt.py` v0.3.0+ instructs the chat to:
1. Retry without the type filter
2. Surface what's actually there
3. Add an honest one-liner: *"the Tripideas-listed properties in {town} are mostly holiday parks; here are the top-rated ones"*

This caveat will only soften when Douglas adds more property types to the Bookit feed.

---

## Field coverage (220 docs)

### Always populated (220/220)

```
isActive            isBookitManaged       bookNowFlag        isGoldMedal      isGoldMedalToday
isHotDealActive     bookitOperatorId      reviewAverageRating reviewCount      bestPriceAvailable
mainImage           gallery               accommodationType1  address          email
bookitMainImageUrl  bookitGalleryUrls
```

### Mostly populated

| Field | Coverage | Notes |
|---|---|---|
| `coordinates` | 219/220 (99.5%) | Standard Sanity geopoint `{_type: "geopoint", lat, lng}` |
| `facilities` | 218/220 | List of strings ("Accessible Facilities", "BBQ", "Wi-Fi", etc.) |
| `telephone` | 218/220 | |
| `cancellationPolicy` | 202/220 | Free-form prose |
| `website` | 199/220 | |
| `town` | 195/220 | String. May contain compound names like "Queenstown Arrowtown" or "Christchurch City South". 25 docs lack this. |
| `arrivalTime` / `departureTime` | 122-123/220 | Strings like `"14:00"` / `"12:00"` |
| `starRating` | 91/220 (~41%) | Integer 0-5. **0 means unrated, not 0-stars.** |
| `hours` | 93/220 | Free-form prose |
| `pointOfDifference` | 87/220 | One-line marketing pitch |
| `accommodationType2` | 73/220 | Sub-type (B&B/Guesthouse, Farmstay, Hotels & Resorts, etc.) |
| `directions` | 72/220 | Free-form |

### Always null / empty

- `operatorTypes`: array of one element `[None]` — useless, ignore
- Most docs have empty `tags` array (it's the page-style `tags` ref, not used for accommodation)

---

## Geographic distribution

Top towns by accommodation count:

| Town | Count |
|---|---|
| Christchurch (multiple suffixes — "Tower Junction Christchurch", "Christchurch City South", etc.) | ~10+ |
| Auckland | 6 |
| Queenstown / Queenstown Arrowtown | 5 |
| Hanmer Springs | 4 |
| Hokitika | 4 |
| Waihi Beach | 4 |
| Picton | 4 |
| Rotorua | 4 |
| Turangi | 3 |

Plus a long tail of single-property towns. **25 docs have no `town` field set** — they fall back to `address` for context.

The geographic spread covers all main NZ tourist hotspots. **No coverage of obscure/remote spots** (which makes sense — only Bookit-onboarded operators are listed).

---

## Image URL conventions

Two parallel sources:

| Field | Format | Use it? |
|---|---|---|
| `mainImage` | Sanity image ref `{_type: "image", asset: {_ref: "image-...", _type: "reference"}}` | ❌ Requires Sanity image URL builder. Avoid. |
| `gallery` | Array of Sanity image refs | ❌ Same |
| `bookitMainImageUrl` | Direct URL `//images.bookeasy.com.au/website/images/bookit/rf{id}-logo-{uuid}.jpg` | ✓ Use this. Prefix `https:` to the protocol-relative URL. |
| `bookitGalleryUrls` | Array of direct URLs | ✓ Use this. Prefix `https:` each one. |

`search_accommodation` uses `_https()` helper to convert `//...` → `https://...` automatically. The first 4 gallery URLs are returned per result.

---

## Pricing (or rather, the lack of it)

**`bestPriceAvailable` is a boolean.** All 10 docs sampled in the audit had `False`. Examples:

```
bool   False  Little River Campground
bool   False  Lake Rotoiti Holiday Park
bool   False  Gateway Motel Holiday Park
...
```

The field is probably a flag for "should we show the 'best price available' badge on the property page?" — not the price itself.

**`rawBookitData`** is a 7-8KB JSON-encoded string with the full Bookit dump. It MIGHT contain numeric pricing fields nested inside (the audit didn't go deep on this). Future investigation could parse `rawBookitData` for a `MinimumPrice` or similar key. For v1, we don't.

For now, the chat surfaces accommodation without pricing claims, and the `book_link` (`tripideas.nz/<slug>`) takes the user to whatever pricing UX Douglas already has on the live site.

---

## Booking-state flags (what each one means)

| Flag | Meaning | Use in scoring |
|---|---|---|
| `isActive` | Doc is published / not soft-deleted | Hard filter: `isActive == true` always |
| `isBookitManaged` | Synced from Bookit (vs. manually-entered) | Always true for these 220 docs |
| `bookNowFlag` | Property accepts bookings via Tripideas right now | +0.4 score boost; `bookable_only` filter |
| `isGoldMedal` | Static historical flag (Bookit "Gold Medal" status) | Not used in scoring |
| `isGoldMedalToday` | Daily-rotating featured flag | +0.5 score boost; `gold_medal_only` filter |
| `isHotDealActive` | Active deal/discount today | +0.3 score boost; `hot_deals_only` filter |

`isGoldMedalToday` changing daily means the same query on different days may surface different results. This is by design — the Bookit feed shifts the featured set.

---

## Quirks discovered during the audit

1. **`coordinates.lat`/`lng` is not always queryable in GROQ filter clauses.** `coordinates.lat >= $val` works in our bounding-box pre-filter, but if Sanity changes the geopoint structure this could break. Test if it stops working.

2. **`town` matching uses Sanity's `match` operator (full-text, word-level).** `town match "Picton"` matches `town == "Picton"` AND `town == "Picton Marlborough"` etc. For exact match, use `town == $val`.

3. **`reviewAverageRating == 0` means "no reviews yet"**, NOT "rated 0/5". Same for `reviewCount == 0`. Combined check: `reviewCount > 0 && reviewAverageRating > 0`.

4. **Some `town` fields contain prefixes that obscure search.** Example: "Tower Junction Christchurch" appears as a town. The `match` operator handles this if the user just says "Christchurch", but exact-match would miss it.

5. **`accommodationType1` enum is closed at 7 values.** Sanity Studio enforces this client-side via the schema (which we don't see directly but inferred from `array::unique` showing exactly 7). Any new types Douglas adds need to be added to `_ACCOMMODATION_TYPES` in [`backend/tool_definitions.py`](../backend/tool_definitions.py) and to the schema in [`directives/tool_contracts/search_accommodation.md`](tool_contracts/search_accommodation.md).

---

## How to refresh this audit

Re-run the same probes used in the original audit:

```bash
python -c "
import sys
sys.path.insert(0, 'execution')
from sanity_client import SanityClient
from collections import Counter
c = SanityClient()

# Type distribution
all_types = c.query('*[_type == \"accommodation\" && defined(accommodationType1)].accommodationType1') or []
print(Counter(all_types).most_common())

# Field coverage
for f in ['coordinates', 'town', 'starRating', 'arrivalTime', 'pointOfDifference']:
    n = c.query(f'count(*[_type == \"accommodation\" && defined({f})])')
    print(f'{f}: {n} / 220')
"
```

When the corpus changes substantially (e.g., new types, big jump in non-caravan-park docs), write `accommodation_audit_<date>.md` and update [`tool_contracts/search_accommodation.md`](tool_contracts/search_accommodation.md) data-caveats section to match.
