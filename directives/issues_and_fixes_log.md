# Issues and fixes — running log

> **What this is:** Chronological log of issues encountered, the fix or workaround applied, and any caveats future agents should know about. Append-only — do not delete entries when issues are resolved; mark them resolved in place. The point is to keep a paper trail so future sessions don't re-discover the same surprises.

---

## 2026-04-27 — Initial build

### Sanity GROQ: `defined(aiMetadata)` returns false for populated string fields

**Symptom:** Counting populated docs returned 3 instead of the actual ~1300.
**Cause:** Unknown Sanity quirk. Reproducible across all `perspective` values (`raw`, `published`, `drafts`).
**Fix:** Use `length(aiMetadata) > 0` instead of `defined(aiMetadata)` whenever filtering for populated string-encoded fields.
**Status:** Worked around. Captured in [`corpus_audit_2026-04-27.md`](corpus_audit_2026-04-27.md) under "GROQ gotchas".

---

### `aiMetadata` JSON truncation — 206/1315 docs unparseable

**Symptom:** Roughly 16% of pages with populated `aiMetadata` fail `json.loads()`. All failures cluster in the 3500–4499 char range.
**Cause:** Upstream metadata-generator pipeline likely had a `max_tokens` cap around 1000 tokens (~4000 chars JSON), causing mid-string truncation.
**Fix (parser-level):** [`execution/aimetadata/parser.py`](../execution/aimetadata/parser.py) catches `JSONDecodeError` and returns `parse_error=True` so callers can surface "thin data" or skip gracefully.
**Pending:** User (Douglas) is investigating. The list of 206 broken doc IDs is in [`.tmp/truncated_aimetadata_docs.csv`](../.tmp/truncated_aimetadata_docs.csv).
**Status:** Worked around. v1 ships against the 1110 clean docs.

---

### `aiMetadata` value-type chaos within stable keys

**Symptom:** Same field key like `amenities` is `string` in one doc, `list[str]` in another, `null` in a third. Same for 11 of the 19 fields.
**Cause:** Upstream LLM non-determinism. The keys are stable but the model freely chose value types.
**Fix:** [`execution/aimetadata/parser.py`](../execution/aimetadata/parser.py) provides robust accessors (`as_list`, `as_str`, `as_dict`) that normalize whatever shape arrives. Tools downstream see consistent types.
**Status:** Resolved.

---

### Tag taxonomy duplicates and prompt-vs-live drift

**Symptom:** Some tags exist in both forms across the live taxonomy: `Historic Sites` AND `Historical Sites`, `Heritage Trails` AND `Historical Trails`, `Scenic Drive` AND `Scenic Drives`, `Te Araroa` AND `Te Araroa Trail`. Plus the Sanity tag list has tags not in either prompt (`Glaciers`, `Surfing`, `Waterfalls`, `Parks`, `City Walks`, `Top 5`).
**Cause:** Editorial drift. The two automation prompts (primary + secondary) were starting points; the Sanity tag collection is what's actually been used.
**Fix:** [`execution/normalize/tag_mapping.py`](../execution/normalize/tag_mapping.py) treats the obvious dup pairs as synonyms (both map to the same theme/subtype). Includes all 102 live tags.
**Pending:** Confirm with Douglas whether the dups are intentional or should be merged in Sanity.
**Status:** Worked around at the mapping layer.

---

### Geographic hallucinations in aiMetadata

**Symptom:** Te Hakapureirei Beach (North Otago) has `dog_friendly: "No dogs allowed at all times on Matapōuri Reserve including Te Hakapureirei Beach area"` — but Matapōuri Reserve is in Northland, ~500km away.
**Cause:** Upstream LLM conflated two unrelated NZ places named with similar Māori words.
**Fix:** Documented as a known data-quality issue. A `hallucination_check.py` audit was deferred to Sprint 1+ but not yet built.
**Pending:** Run a corpus-wide geographic-consistency check (cross-reference place names mentioned in `dog_friendly`/`historical_significance`/`nearby_places` against the doc's `coordinates` to flag mismatches > 200km).
**Status:** Open. Doesn't block v1.

---

### Modal token format gotcha

**Symptom:** User shared just the token ID (`ak-...`) — Modal CLI requires the full pair (ID + secret).
**Cause:** Modal token API design — IDs and secrets are paired credentials.
**Fix:** Use `modal token new` (browser OAuth flow) which writes both to `~/.modal.toml` cleanly. Never share secrets via chat.
**Status:** Resolved. Captured in memory for future sessions.

---

### Modal CLI on Windows — charmap encoding crash

**Symptom:** First `modal deploy` attempt failed with `'charmap' codec can't encode characters in position 3-42`. Modal's progress-bar Unicode characters can't be printed in cp1252.
**Cause:** Default Windows console encoding is cp1252; Modal's CLI prints Unicode (✓, →, etc).
**Fix:** Prefix Modal commands with `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`:
```bash
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 modal deploy backend/modal_app.py
```
**Status:** Resolved. Add to README + memory for future sessions.

---

### MessageBubble bug — empty pre-stream rendering

**Symptom:** User typed in chat, hit send, then saw nothing for 5–7 seconds before the response appeared all at once.
**Cause:** Empty assistant `MessageBubble` was added immediately so SSE events have a target. But `messages[last].role !== "user"` so the parent-level `ThinkingIndicator` never fired. And the empty bubble had no visible content (no text, no tool calls yet).
**Fix:** Added `isAwaitingFirstEvent` check inside `MessageBubble`: when assistant is streaming + no content + no tool calls, render `PulsingDots` inline. Removed the parent-level `ThinkingIndicator`.
**Files:** [`frontend/src/ChatPanel.tsx`](../frontend/src/ChatPanel.tsx)
**Status:** Resolved 2026-04-27 evening.

---

### Netlify config — wrong `publish` path

**Symptom:** N/A — caught before deploy.
**Cause:** `netlify.toml` had `base = "frontend/"` AND `publish = "frontend/dist/"`. With `base` set, paths resolve relative to it — so the original `publish` would have looked for `frontend/frontend/dist/`.
**Fix:** Changed `publish` to `"dist/"` (relative to `base = "frontend/"`).
**Files:** [`../netlify.toml`](../netlify.toml)
**Status:** Resolved.

---

### Accommodation: no numeric pricing in Sanity

**Symptom:** Tried to filter by `max_price_per_night` against `bestPriceAvailable` — got 0 results everywhere.
**Cause:** `bestPriceAvailable` is a `bool` flag, not a price number. Probably "show the 'best price available' badge?". All 10 sampled docs had `False`.
**Fix:** Dropped `max_price_per_night` from `search_accommodation`'s input schema. Surface `book_link` to `tripideas.nz/<slug>` instead so users see live pricing on Tripideas's existing flow. Real pricing requires Bookit API (Sprint 5).
**Files:** [`execution/tools/search_accommodation.py`](../execution/tools/search_accommodation.py)
**Status:** Documented in [`tool_contracts/search_accommodation.md`](tool_contracts/search_accommodation.md) and [`accommodation_audit_2026-04-27.md`](accommodation_audit_2026-04-27.md).

---

### Accommodation: no region/subRegion taxonomy

**Symptom:** No way to do `subRegion->region->name == "Otago"`-style filter on accommodation (works for pages).
**Cause:** Accommodation docs only have `town` (string, 195/220 populated) and `coordinates` (219/220). They don't reference our region/subRegion graph.
**Fix:** Added `REGION_CENTROIDS` to [`execution/registry/regions.py`](../execution/registry/regions.py) (hardcoded coords for each NZ region, picked at the most touristically-central point). `search_accommodation` resolves a `region` argument to a centroid and applies an 80km radius filter.
**Status:** Resolved. Approximate but works for v1.

---

### Accommodation pool is heavily caravan-park-skewed

**Symptom:** "Find me a Lodge in Otago" → 0 results. "Find me a Motel in Picton" → 0 results.
**Cause:** Real data — 207 of 220 accommodation docs (94%) are `accommodationType1 == "Caravan Parks & Camping"`. Only 1 Lodge in NZ (Tuatapere, Southland), 3 Motels, 6 Backpackers.
**Fix:** Updated `backend/system_prompt.py` (v0.3.0) to instruct the chat: *"if a specific type filter returns 0 results, consider re-running without the type filter and surfacing what's actually there with a brief honest note."* Verified in live testing — the chat acknowledged "the Tripideas-listed properties in the Queenstown area are currently holiday parks" rather than just saying "no results found".
**Status:** Worked around at the prompt level. Long-term fix is for Douglas to onboard more property types to Bookit.

---

## 2026-05-05 — Sprint 4.7: Google Maps integration

### Greedy day-fill scoring shouldn't call Google Maps

**Symptom (caught in design before shipping):** First draft put `google_maps.directions()` inside `_drive_minutes` — the function the greedy day-fill calls when scoring every candidate against every chosen stop. For a balanced day with ~5 picks against a candidate pool of 30, that's ~150 Google calls per day plan. At ~$0.005/call that's ~$0.75 per day plan, ~$3 per 4-day trip — chat cost dwarfed by routing.
**Cause:** Confusing two needs: a "close enough" relative ranking signal (cheap, deterministic, never user-visible) vs an accurate user-facing drive estimate + visual polyline.
**Fix:** Reverted `_drive_minutes` to haversine × 1.4 / 60 km/h. Google Maps is invoked exactly **once per day** in `_build_route_geojson` (origin/destination = base, all places as waypoints) for the visual + accurate total. Same model in `build_trip_itinerary`: once per inter-day transition. So a 4-day trip = 4 day-Google-calls + 3 inter-day calls = 7 total, ~$0.035.
**Files:** [`execution/tools/build_day_itinerary.py`](../execution/tools/build_day_itinerary.py) (`_drive_minutes`, `_build_route_geojson`), [`execution/tools/build_trip_itinerary.py`](../execution/tools/build_trip_itinerary.py) (`_compute_transition`, `_build_trip_geojson`), [`execution/services/google_maps.py`](../execution/services/google_maps.py).
**Status:** Resolved before deploy. Cost model documented inline near `_drive_minutes`.

---

### `google-maps-secret` was never actually created in Modal

**Symptom:** First `modal deploy` after Sprint 4.7 wiring failed with `Secret 'google-maps-secret' not found in environment 'main'`. A previous session's summary claimed the secret existed — `modal secret list` showed otherwise.
**Cause:** Trust drift. Conversation summaries are not source of truth; only `modal secret list` is.
**Fix:** Created the secret via `modal secret create google-maps-secret GOOGLE_MAPS_API_KEY=…` from the value already in `.env`.
**Lesson encoded into:** [`directives/deployment.md`](deployment.md) — explicit secrets table + "always verify with `modal secret list`" guidance.
**Status:** Resolved.

---

### Modal warm container served stale code after redeploy

**Symptom:** Pushed a code change (bumped `SYSTEM_PROMPT_VERSION` from 0.3.0 to 0.4.0, added `google_maps_configured` to the health response). `modal deploy` succeeded multiple times. The live `/` endpoint kept returning the old `prompt_version` and missing the new field. Repeated deploys (3.2s, "Created mounts") didn't fix it. Cleared `__pycache__` — no change.
**Cause:** With `min_containers=0` and a warm container still alive, `modal deploy` doesn't always force-evict it; new requests get routed to the old container which has the old code in memory. (Modal usually does evict, but this time it didn't — possibly because containers fall under a "warm pool" briefly post-deploy.)
**Fix:** `modal app stop <app_id>` (find via `modal app list`), then `modal deploy`. The next request cold-starts a fresh container with the new code. Confirmed: `prompt_version` flipped to 0.4.0 immediately after the stop+redeploy.
**Lesson encoded into:** [`directives/deployment.md`](deployment.md) — under "Common gotchas", with the diagnostic recipe.
**Status:** Resolved. Going forward: bump `SYSTEM_PROMPT_VERSION` (or some visible field) on every meaningful change so `curl /` immediately tells you whether the redeploy took effect.

---

### Modal workspace ambiguity (`devesesam` vs `rvnu`)

**Symptom:** `modal deploy` from a fresh shell hit `Secret 'tripideas-secrets' not found in environment 'main'`. Cause: `modal profile current` was set to `rvnu`, a different workspace on the same machine. The secrets live in `devesesam`.
**Fix:** `modal profile activate devesesam` before any `modal` command for this project.
**Lesson encoded into:** [`directives/deployment.md`](deployment.md) (workspace = `devesesam`, deploy command listed verbatim) plus a memory entry so this doesn't get re-discovered every session.
**Status:** Resolved. Always run `modal profile current` before deploying — must read `devesesam`.

---

## 2026-05-18 — Sprint 4.9: Search fixes from Douglas's test conversation

### GROQ tag-intersection was silently a no-op

**Symptom:** Every theme-filtered search returned the full region. e.g. `region=Auckland, themes=[coastal]` returned all 284 Auckland pages, not just the coastal ones. Confirmed against the live data: `count(tags[]->name[@ in ["Museums"]]) > 0` returned 347 for the same region where the correct answer is 0. The clause was effectively matching every doc with any tag.
**Cause:** Sanity GROQ syntax quirk — the bare form `count(tags[]->name[@ in $arr]) > 0` does not bind `@` to elements of the dereferenced `tags[]->name` array correctly. The fix is parens around the array projection: `count((tags[]->name)[@ in $arr]) > 0`.
**Impact:** Significantly larger than it looked. Every "themed" search across the entire tool's lifetime was actually returning region-only results, scored by haversine + interests_text only. Themes, place_subtypes, and the new `tags` filter all depend on this pattern.
**Fix:** Inline note in [`execution/tools/search_places.py`](../execution/tools/search_places.py) `_fetch_candidates`. Confirmed via smoke test: `region=Auckland, themes=[coastal]` now returns 194 (was 284); `region=Northland, place_subtypes=[museum]` returns 6 (was 95).
**Status:** Resolved + documented inline for future agents.

---

### `place_subtypes` was a score boost, not a hard filter

**Symptom:** `search_places(region="Auckland", place_subtypes=["museum"])` returned 284 (full region) instead of the actual handful of museums.
**Cause:** Two bugs compounded. (a) The GROQ no-op above. (b) `themes` and `place_subtypes` were merged into a single OR-set at the GROQ layer ([search_places.py:329-337](../execution/tools/search_places.py)) — so a page tagged `Coastal Walks` (a theme tag) but with no museum tag still survived a museum-only query. The Python post-filter at line 252 was a score boost, not a drop.
**Fix:** Split into separate AND-of-OR groups. A page must have at least one tag from each non-empty group. Files: `execution/tools/search_places.py`.
**Status:** Resolved.

---

### `interests_text` couldn't find pages by their own title

**Symptom:** `search_places(interests_text="Hamiltons Gap")` returned 0 even though the page exists. Likewise for "Kaiaua" and other known place names.
**Cause:** The search blob was built from aiMetadata description + attractions + local_tips + activities — but **not** the page's own title. Place-name-only queries (where the name appears in no other page's body) couldn't match.
**Fix:** Added `doc["title"]`, `ai.title`, and `ai.keywords` to the blob. Case-insensitive substring stays. Note: 180+ pages have no aiMetadata yet (the GROQ pre-filter drops them); for *those* pages use the new `find_place_by_name` tool instead.
**Status:** Resolved.

---

### Freedom Camping (and other editorial tags) unreachable

**Symptom:** The LLM had no way to find "places in the Catlins that allow freedom camping" even though `Freedom Camping` is a real Sanity tag on relevant pages.
**Cause:** The tool only exposed `themes` and `place_subtypes` filters. The `Freedom Camping` tag has empty `themes` and empty `place_subtype_hints` in [`tag_mapping.py`](../execution/normalize/tag_mapping.py) (it's marked `is_accommodation_tag=True`) — so no derived filter surfaced it.
**Fix:** Added a direct `tags: list[str]` filter to `search_places` ([search_places.py](../execution/tools/search_places.py)). Operates as a hard GROQ intersection alongside themes/subtypes. Future structured editorial signals Douglas adds (`paid-entry`, `dog-friendly`, etc.) become searchable with no code change — just pass the tag name through.
**Status:** Resolved. Live-tested: `region=Otago, subRegion=Catlins, tags=["Freedom Camping"]` returns Owaka.

---

### Sub-region taxonomy invisible to the LLM

**Symptom:** Model guessed `Downtown Auckland` for Auckland's central city, but the real Sanity tag is `Central Auckland`. Douglas had to correct it manually.
**Cause:** The system prompt had a region cheat-sheet but no sub-region taxonomy. Hardcoding the list rots — Douglas adds sub-regions over time.
**Fix (two-layer):**
1. **New tool** `list_subregions(region)` at [execution/tools/list_subregions.py](../execution/tools/list_subregions.py) — returns live sub-region list with place counts. LLM calls when unsure or after Douglas adds new content.
2. **Deploy-time injection** — `orchestrator.py` calls `build_taxonomy_snapshot()` at startup and feeds the result into `compose_system_prompt()`. Snapshot is ~1.5 KB, refreshes on every redeploy.
**Status:** Resolved. The 0.5.0 system prompt is 10.8 KB (up from ~4 KB), with the full region → subRegion → count map embedded.

---

### Doc IDs unreachable for thin-data pages

**Symptom:** Pages without aiMetadata (e.g. Hamiltons Gap, Kaiaua — ~180 pages) couldn't be located by name via `search_places` because of the `length(aiMetadata) > 10` GROQ pre-filter. The LLM had no way to surface the doc_id for follow-up tools like `get_place_summary`.
**Fix:** New tool `find_place_by_name(name, region?)` at [execution/tools/find_place_by_name.py](../execution/tools/find_place_by_name.py). Bypasses the aiMetadata filter. Matches against `title` and `slug.current` with case-insensitive substring; ranks exact > prefix > substring. Each result has a `has_aimetadata` flag so the LLM knows whether to follow up with `get_place_summary` (needs aiMetadata) or just surface the page link.
**Status:** Resolved. Live-tested: Hamiltons Gap, Kaiaua both findable.

---

### LLM emitting placeholder `tripideas.nz/` URLs

**Symptom:** In the test transcript the LLM emitted `https://tripideas.nz/` placeholder links in the first Catlins overview *before any tool call*. Self-corrected when Douglas asked but the underlying behaviour is a fabrication risk.
**Cause:** The system prompt allowed link generation as soft guidance, not a hard rule.
**Fix:** Two hard rules added to [`backend/system_prompt.py`](../backend/system_prompt.py) `HARD_RULES` block at the top of the prompt:
1. Never emit a `tripideas.nz` URL unless the slug came from a tool result.
2. Always search before composing — no exceptions for "urban" or "niche" topics.
**Status:** Resolved. Bumped to `SYSTEM_PROMPT_VERSION = 0.5.0`. Watch the next test transcript to confirm behaviour change.

---

### Modal 120s + Anthropic 60s timeouts intermittent on heavy-burst turns

**Symptom:** Three failures in Douglas's transcript — one `Backend 500` and two `Load failed` — during the 17-parallel-`search_places` taxonomy probe.
**Cause:** Likely the Anthropic client timeout (60s) being hit when the model takes a long tool-use loop iteration on a heavy burst, or the Modal function timeout (120s) on the whole turn.
**Fix:** Bumped Modal `timeout=120` → `timeout=300` in [`backend/modal_app.py`](../backend/modal_app.py); bumped `ANTHROPIC_TIMEOUT_S=60.0` → `120.0` in [`backend/orchestrator.py`](../backend/orchestrator.py). Both are soft caps — typical turns are well under both.
**Status:** Resolved (preventive). Re-test the 17-parallel-search pattern on the next user run to confirm.

---

## 2026-05-18 — Sprint 5.0: Itinerary anchoring fixes (data-driven, no overrides)

### Sub-region centroid lands in the ocean / between clusters

**Symptom:** `build_day_itinerary` with `base_location="Hauraki Gulf Islands"` failed to fill — the base coords landed in the middle of the gulf. Same pattern would hit any dispersed sub-region (Catlins, Fiordland, Marlborough Sounds, Kāpiti Coast).
**Cause:** [`execution/registry/settlements.py`](../execution/registry/settlements.py) `resolve()` used `math::avg(coordinates.lat/lng)` across all pages in the sub-region. Mean is geographically valid but practically useless for dispersed sub-regions.
**Fix considered and rejected:** Hardcoded override map (`Hauraki Gulf Islands → Matiatia Bay`, etc.). Doesn't scale — every new dispersed sub-region Douglas adds would need a manual entry.
**Fix shipped:** **Densest-cluster anchor.** Fetch all pages in the sub-region (one GROQ), count haversine neighbours within 15 km for each, return the page with the most neighbours (tie-break on neighbours within 5 km). Picks the natural anchor town automatically for any sub-region — no maintenance. Falls back to mean only when there are < 3 pages.

Smoke results across 10 sub-regions: all resolve to sensible anchor points (Hauraki Gulf Islands → Great Barrier Tryphena cluster; Catlins → Papatowai area; Fiordland → Te Anau area; Wellington City / Central Auckland / Dunedin → their CBDs).

**Files:** `execution/registry/settlements.py` (`_resolve_subregion_anchor` helper).
**Status:** Resolved.

---

### Day-base picked far from user's stated location

**Symptom:** *"Coastal day around Wellington CBD"* → day anchored at Mākara Beach (12 km west, ~25 min drive). User expected city-adjacent coastal spots.
**Cause:** [`build_day_itinerary.py:572`](../execution/tools/build_day_itinerary.py) scored every slot identically: `score = c.score - (drive_min * 0.05)`. The drive penalty was too gentle to outweigh a high-scoring place far from base. Mākara's content score beat its drive penalty.
**Fix:** Triple the drive-time penalty for the *first* slot only (`0.15` vs `0.05`). Subsequent slots keep the existing weighting so road-trip days can range widely. Pure algorithmic — same scoring function, position-aware weight.

Smoke result: Wellington coastal day now opens with Wellington Harbour Walk (CBD itself), then Lyall Bay (5 km), then Oriental Bay or Tarakena Bay. Mākara may still appear later but never as the first stop.

**Files:** `execution/tools/build_day_itinerary.py` (`_pick_best_candidate` + caller).
**Status:** Resolved.

---

### `candidate_radius_km` always defaulted to 50 km (wrong for CBD / walkable scopes)

**Symptom:** Same Wellington case — even with the proximity bias fix, a 50 km radius surfaces too many candidates outside a "city CBD" mental model.
**Fix considered and rejected:** Hardcoded `if user says "CBD" then radius=15` mapping in the system prompt. Phrase-to-magic-number doesn't generalise — every city would need its own number tuned by trial.
**Fix shipped:** Prompt guidance documenting the **existing** `candidate_radius_km` parameter with scope bands (10–15 km for walkable/CBD, 25–30 km for town-and-surrounds, 50 km default, 80+ for road trips). The LLM picks based on user context each turn; the tool implements whatever's passed. No magic phrase mapping.
**Files:** [`backend/system_prompt.py`](../backend/system_prompt.py) HARD_RULES #9.
**Status:** Resolved. If the LLM picks badly often, tune the *guidance bands*, not the rules.

---

### Macron typos in model text output

**Symptom:** Model wrote "Māakara Beach" (double a) when the actual Sanity title is "Mākara Beach".
**Cause:** Pure model artifact — tool returns the exact title, model paraphrases during text generation. Not a server-side bug.
**Fix:** New HARD_RULE in [`backend/system_prompt.py`](../backend/system_prompt.py) #7 — "quote place titles verbatim from tool results", with explicit macron/apostrophe/capitalisation guidance.
**Status:** Resolved at the prompt layer. If failures persist, fall-back option (not implemented yet): return a `display_title` field alongside `title` and instruct the LLM to use it verbatim.

---

### LLM mentioned specific places without verifying them on Tripideas

**Symptom:** In a Waiheke day plan the model named specific wineries (Stonyridge, Batch Winery, Cable Bay) without calling `find_place_by_name` to check if they're on Tripideas.
**Cause:** Existing HARD_RULE #1 only forbids fabricated *URLs*. Naming a place without a URL was technically allowed.
**Fix:** New HARD_RULE in [`backend/system_prompt.py`](../backend/system_prompt.py) #8 — when naming specific attractions/restaurants/wineries in supplementary content, call `find_place_by_name` first. If on Tripideas, reference normally with the verified slug. If not, mention generically and make clear it's not Tripideas-listed.
**Status:** Resolved at the prompt layer. Behaviour will vary by model judgment; monitor next test transcripts.

---

## 2026-05-18 — Sprint 5.1: Douglas's feedback list + web_search integration

### Accommodation links 404'd (every URL pattern tried)

**Symptom:** Douglas reported that accommodation `book_link` URLs go to 404 on tripideas.nz. Other links (place pages) work.
**Investigation:** Probed seven URL patterns against a real accommodation slug (`little-river-campground-100811`): `/<slug>`, `/stay/<slug>`, `/accommodation/<slug>`, `/listings/<slug>`, `/book/<slug>`, `/places-to-stay/<slug>`, `/accommodation-listing/<slug>`, plus variants without the numeric Bookit operator-ID suffix. **Every variant returned 404.** Also checked `tripideas.nz/sitemap.xml`: it lists `place-sitemap`, `post-sitemap`, `region-sitemap`, `tag-sitemap` etc. but **no accommodation sitemap**. Conclusion: accommodation isn't published as standalone pages on the live site right now.
**Fix:** [`execution/tools/search_accommodation.py:305`](../execution/tools/search_accommodation.py) — `book_link=None` always (was constructing `f"https://tripideas.nz/{slug}"`). System prompt instructs the chat to surface `contact.website` (operator's own site) as the actionable link instead.
**Bonus discovery:** Same probe confirmed places live at the canonical `https://www.tripideas.nz/place/<slug>` — bare `/<slug>` works via legacy redirect but isn't authoritative. HARD_RULE #1 updated to require `/place/<slug>` prefix; legacy bare-slug emission deprecated.
**Status:** Resolved + canonical URL conventions documented.

---

### Itinerary timing conflated visit and drive durations

**Symptom:** Day plans rendered as `9:00–10:15 | Lyall Bay (~75 min)` followed by `10:30 | Worser Bay`. Users couldn't tell whether the 75 minutes included drive time, where drive time was spent, or how long the day really takes. Douglas flagged this in his email.
**Cause:** No canonical format in the prompt. Each chat turn produced varied rendering (sometimes prose, sometimes bullets, sometimes ad-hoc tables).
**Fix:** Defined a 4-column canonical itinerary table in [`backend/system_prompt.py`](../backend/system_prompt.py) `ITINERARY_FORMAT` block — Time / Stop / Duration / Drive next. **Duration is visit-time only**; drive time is its own column on the origin row. 8 explicit rules. Multi-day trips render one table per `## Day N` heading.
**Files:** `backend/system_prompt.py` (new `ITINERARY_FORMAT` block + reference in CONVERSATIONAL_STYLE).
**Status:** Resolved. Output consistency depends on model adherence — monitor and tune the example rows if drift appears.

---

### Curated external-reference defaults

**Symptom:** Model recommended AllTrails for trail maps (paid product) instead of free alternatives. Douglas asked us to default to planmywalk.nz.
**Fix:** Added an `EXTERNAL_REFERENCES` block to the system prompt listing Douglas's curated default external resources by topic — trails → planmywalk.nz, DOC campsites → doc.govt.nz, freedom camping → freedomcamping.org / CamperMate, Gulf ferries → fullers.co.nz, road conditions → journeys.nzta.govt.nz, weather → metservice.com / yr.no, tides → tides.niwa.co.nz. List is a curation surface — extend by editing the prompt block, not by hardcoding behaviour.
**Files:** `backend/system_prompt.py`.
**Status:** Resolved. Add new entries as Douglas's preferences evolve.

---

### Anthropic `web_search` tool integrated

**Why:** Pre-fix, the chatbot was citing external URLs (`hobbitontours.com`, etc.) from its training data — not live searches. Looked like working web search but wasn't. Decision: add Anthropic's built-in `web_search_20250305` server tool to genuinely fetch current information when Tripideas content is silent.
**How it works:** Server-side tool, executed by Anthropic in the same API call. No dispatch code in our orchestrator — we just declare the tool and handle two new content-block types (`server_tool_use`, `web_search_tool_result`) when rebuilding the assistant message for conversation continuity.
**Cost:** $0.01 per search, billed via the same Anthropic API key. `max_uses=3` per chat turn caps cost at $0.03/turn.
**Gating:** New HARD_RULE #11 — only call when (a) Tripideas tools already returned zero, AND (b) the answer needs live information (opening hours, schedules, prices, news). Don't use for general descriptions or padding.
**Files touched:** [`backend/tool_definitions.py`](../backend/tool_definitions.py) (new `WEB_SEARCH_SCHEMA`), [`backend/orchestrator.py`](../backend/orchestrator.py) (server_tool_use block handling + pause_turn stop_reason loop), [`backend/system_prompt.py`](../backend/system_prompt.py) (HARD_RULE #11 + tool listed as #9).
**Smoke results:** Fires on *"current ferry times to Waiheke"* with cited Fullers360 / Island Direct / Auckland Transport URLs. Does NOT fire on *"coastal walks in Northland"* (Tripideas data sufficient).
**Org-admin gotcha:** Web Search must be enabled in the Anthropic Console at `/settings/privacy` for the workspace's API key. Confirmed enabled for `devesesam` because our smoke test ran successfully — if it ever stops working, this is the first thing to check. Failures show up as `web_search_tool_result` blocks with error codes (`too_many_requests`, `invalid_input`, `max_uses_exceeded`, `query_too_long`, `unavailable`), NOT as exceptions.
**Status:** Resolved. Live at `prompt_version: 0.7.0`.

---

### settlements.resolve was returning body-mention coordinates (post-Sprint 5.0 follow-up)

**Symptom:** Live test result of "Coastal day around Wellington CBD" anchored at Mākara Beach. Investigation showed the LLM passed `base_location="Wellington CBD"`; `settlements.resolve()` returned Mākara's coordinates because Mākara's aiMetadata mentions "30 min from Wellington CBD" — the body-mention path was matching.
**Fix:** Rewrote the page_match logic at [`execution/registry/settlements.py`](../execution/registry/settlements.py) `resolve()` to rank exact-title > title-substring, and **refuse to fall back to body-mention matches**. Added a final region-centroid fallback so unrecognised names (e.g. "Wellington CBD" with no matching page title) resolve to the largest sub-region's anchor instead of failing.
**Files:** `execution/registry/settlements.py`.
**Status:** Resolved at `prompt_version: 0.5.2`.

---

### Macron-stripped place names didn't resolve

**Symptom:** "Plan a day at Pūrākaunui Falls" — model called `find_place_by_name` + `get_place_summary` correctly but then passed `base_location="Purakaunui Falls"` (without macrons) to `build_day_itinerary`, which fell through to the Queenstown Lakes region centroid because GROQ `match` is diacritic-sensitive.
**Fix:** Added Unicode NFKD-based `_strip_accents()` helper in [`execution/registry/settlements.py`](../execution/registry/settlements.py); page-title comparison now normalises both sides. "Purakaunui Falls" and "Pūrākaunui Falls" resolve to the same coords. Works for any Te Reo title across the corpus.
**Status:** Resolved at `prompt_version: 0.5.3`. Note: HARD_RULE #7 still asks the model to preserve macrons verbatim — this is belt-and-braces.

---

### Model skipped tools entirely for "off-topic" queries

**Symptom:** *"Where can I get good coffee in Wellington?"* → model said "my tools are focused on places to visit — try Google Maps" without calling any tool. Pre-judged that tools wouldn't help.
**Fix:** Tightened HARD_RULE #2 in [`backend/system_prompt.py`](../backend/system_prompt.py) — added explicit ❌/✓ examples showing the wrong path ("skip the tools because you think they won't help") and the right path ("call them, see the zero, then explain"). The empty tool result is the verification.
**Status:** Resolved at `prompt_version: 0.5.3`.

---

## How to use this log

When you encounter a new issue:
1. Append a new dated section at the end of this file
2. Write the symptom, cause, fix, files touched, and current status
3. If the issue is resolved later, update the Status line in place — don't delete the entry
4. If the issue resurfaces or partially regresses, add a follow-up note below

When you start a session and see something weird:
1. Search this file (Ctrl+F) for the symptom you're seeing
2. If it's documented, follow the fix
3. If not, debug from scratch — and add a new entry once you've worked it out
