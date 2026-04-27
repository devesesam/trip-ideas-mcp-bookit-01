# Tripideas.nz MCP – Developer Brief

> **Source:** Parsed from `Tripideas.docx`
> **Purpose:** Agent-readable directive for building the Tripideas MCP server

---

## Objective

Build the first practical version of the Tripideas.nz MCP so it can help users move from vague travel intent to useful trip ideas, then to realistic itineraries, and later to bookable options.

**Immediate priorities:**
- Add hidden metadata to existing content
- Expose that content cleanly through MCP tools
- Integrate Bookit as a later inventory layer
- Make itinerary generation the core user-facing value

This brief supports a staged, low-risk developer build.

---

## Product Goal

The MCP should handle prompts like:
- *"Give me a 3-day Northland getaway idea"*
- *"Plan a relaxed South Island itinerary for 7 days"*
- *"What can we do near Queenstown with kids?"*
- *"Swap day two for something cheaper and easier"*

**Strongest at:**
- Trip idea generation
- Itinerary drafting
- Itinerary refinement
- (Later) availability and booking handoff

> Version one does not need to solve everything.

---

## Guiding Principles

### 1. Start narrow
Do not build one giant `plan_trip` tool that tries to do everything. Start with small tools that each do one job well.

### 2. Structure beats prose
Tool outputs should be structured JSON-like data, not long paragraphs. The model can turn structured results into good user-facing language.

### 3. Content first, booking second
Use Tripideas own content and metadata as the first planning engine. Bookit should expand options later, not define the architecture from day one.

### 4. Editorial and inventory must stay separate
Tripideas content should remain clearly distinct from live inventory data. That makes ranking, trust, and fallback handling much easier.

### 5. Every tool must have a clear contract
Each tool must define:
- A clear name
- A plain-English description
- A strict input schema
- A stable output shape
- Predictable errors

---

## Recommended Architecture

### Core Components

| Layer | What it is |
|---|---|
| CMS / content source | Existing Tripideas content, enriched with hidden metadata |
| Metadata layer | Normalised tags and attributes, exposed in a consistent schema |
| MCP server | Tool registration, execution, validation, and logging |
| Itinerary logic layer | Ranking, filtering, day planning, refinement rules |
| Bookit integration layer | Separate adapter/service — read-only first, booking handoff later |

### Suggested Stack
- Python MCP server (FastMCP or equivalent MCP SDK)
- Existing API / database / CMS underneath
- Separate service modules for metadata queries and Bookit calls

---

## Phase Plan

### Phase 1 – Metadata Foundation

**Goal:** Make all existing content machine-usable for planning.

**Recommended core metadata fields:**

```yaml
content_id: string
title: string
content_type: [destination, activity, accommodation, food_drink, transport, itinerary]

location:
  country: string
  island: string
  region: string
  district_town: string
  lat: float
  lng: float

themes:        [adventure, food, culture, family, luxury, outdoors, wellness, wildlife]
suitability:   [solo, couples, families, groups]
duration_band: [1-2 hours, half-day, full-day, multi-day]
budget_band:   [low, medium, high]
seasonality:   [all year, summer best, winter best, weather sensitive]
physical_intensity: [easy, moderate, demanding]

accessibility_flags:
  opening_hours_known: boolean

booking_status: [informational, enquiry, bookable]
supplier_reference: string
status: [active, draft, seasonal]
```

**Developer deliverables:**
- Versioned metadata schema
- Migration / retrofitting plan for existing content
- Validation rules for required fields
- A normalised taxonomy for interests and categories
- A queryable store or endpoint for metadata-backed search

**Done when:**
- At least one meaningful content segment is fully tagged
- Metadata can be queried consistently
- Itinerary tools can rely on it without custom per-entry hacks

---

### Phase 2 – First MCP Tools on Top of Content

**Goal:** Make the MCP useful before any booking integration.

#### Tool 1: `search_trip_ideas`
**Purpose:** Find relevant trip concepts based on destination, duration, interests, season, and budget.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "region": { "type": "string" },
    "town": { "type": "string" },
    "trip_length_days": { "type": "integer", "minimum": 1, "maximum": 30 },
    "interests": { "type": "array", "items": { "type": "string" } },
    "season": { "type": "string" },
    "budget_band": { "type": "string", "enum": ["low", "medium", "high"] },
    "travelling_with": { "type": "string", "enum": ["solo", "couple", "family", "group"] }
  },
  "required": ["region"]
}
```

**Output shape:**
```json
{
  "ok": true,
  "query": { "region": "Northland", "trip_length_days": 3 },
  "results": [
    {
      "idea_id": "idea_123",
      "title": "3-day coastal Northland escape",
      "summary": "Beaches, short walks, and relaxed food stops.",
      "days": 3,
      "themes": ["coastal", "relaxed", "food"],
      "match_reasons": ["matches region", "fits 3-day duration"],
      "content_refs": ["content_1", "content_9"]
    }
  ]
}
```

**Errors:** `invalid_region`, `no_matching_content`, `unsupported_budget_value`

---

#### Tool 2: `get_place_summary`
**Purpose:** Return structured destination or location context.

**Inputs:** `place_id` or `place_name`

**Returns:** summary, region, best for, ideal duration, key themes, nearby places, seasonal notes

---

#### Tool 3: `build_day_itinerary`
**Purpose:** Assemble one realistic day from available content.

**Input schema:**
```json
{
  "type": "object",
  "properties": {
    "base_location": { "type": "string" },
    "interests": { "type": "array", "items": { "type": "string" } },
    "pace": { "type": "string", "enum": ["relaxed", "balanced", "full"] },
    "budget_band": { "type": "string", "enum": ["low", "medium", "high"] },
    "travelling_with": { "type": "string", "enum": ["solo", "couple", "family", "group"] }
  },
  "required": ["base_location", "pace"]
}
```

**Output shape:**
```json
{
  "ok": true,
  "day_plan": [
    {
      "time": "09:00",
      "activity_id": "act_22",
      "title": "Coastal walk",
      "duration_minutes": 90,
      "location": "Mangawhai Heads"
    },
    {
      "time": "12:00",
      "activity_id": "food_17",
      "title": "Lunch stop",
      "duration_minutes": 60,
      "location": "Mangawhai Village"
    }
  ],
  "assumptions": [
    "Self-drive assumed",
    "Weather suitable for outdoor activities"
  ]
}
```

---

#### Tool 4: `refine_itinerary`
**Purpose:** Adjust an existing itinerary without rebuilding everything.

**Inputs:** existing itinerary object, `change_request` (string), optional `constraints`

**Returns:** updated itinerary, list of changes made, unresolved constraints (if any)

---

**Developer deliverables (Phase 2):**
- MCP server bootstrapped
- Tools registered and callable
- Schema validation in place
- Structured result payloads
- Logs for all tool calls

**Done when:** A model can call these tools and get useful, consistent responses. Returned structures are stable enough for prompt orchestration.

---

### Phase 3 – Itinerary Realism Layer

**Goal:** Stop itineraries from becoming vague or impossible.

**Core rules to implement:**
- Avoid placing activities too far apart in the same day
- Respect duration bands
- Avoid overfilling a day
- Allow relaxed / moderate / packed pacing modes
- Handle weather-sensitive or seasonal activities
- Support family / accessibility constraints where metadata allows

**Recommended helper functions:**
- `estimate_drive_time`
- `filter_by_budget`
- `filter_by_accessibility`
- `filter_by_season`
- `check_basic_feasibility`

> These can be external MCP tools or internal service functions, depending on how much model control is desired.

**Done when:** Sample itineraries feel plausible to a human editor. Obvious geographic or timing mistakes are sharply reduced.

---

### Phase 4 – Bookit Integration

**Goal:** Add bookable inventory without breaking the content-first planning model.

**Design rule:** Treat Bookit as a separate inventory source that can enrich or validate plans. Do not tightly couple raw Bookit objects to editorial content models unless the mapping is very clear.

**Integration tasks:**
- Map Bookit products to Tripideas categories
- Map Bookit locations to your location hierarchy
- Map pricing, variants, and availability shape
- Define sync strategy
- Define de-duplication logic
- Define fallback behavior when a recommended product is unavailable

**First Bookit-facing tools:**

| Tool | Purpose |
|---|---|
| `search_bookable_experiences` | Find bookable products matching place/date/category filters |
| `check_availability` | Return availability for a selected experience |
| `get_price_estimate` | Return indicative pricing for a chosen plan or product set |

**Delay until later:** direct booking creation, payment-critical actions, anything destructive or transaction-heavy.

**Done when:**
- The model can enrich itineraries with live options
- Unavailable experiences fail gracefully
- Editorial content still works when Bookit data is absent

---

## Sprint Breakdown

### Sprint 1 – Bootstrap and One Useful Tool
**Build:** MCP server, metadata query service, `search_trip_ideas`

**Tasks:**
- Define schema
- Register tool
- Connect to metadata-backed search
- Return ranked structured results
- Log requests and responses
- Create 5 realistic test prompts

**Success test:** Can answer *"Give me a 3-day trip idea in Northland for a couple"* with structured results.

---

### Sprint 2 – Itinerary Generation
**Build:** `build_day_itinerary`, internal ranking and pacing logic, basic feasibility rules

**Tasks:**
- Turn matching content into ordered day blocks
- Enforce simple time/duration logic
- Add assumptions to output
- Test on 10 sample destinations

**Success test:** Generated day plans feel plausible and not overloaded.

---

### Sprint 3 – Itinerary Refinement
**Build:** `refine_itinerary`

**Tasks:**
- Accept previous itinerary object as input
- Replace or remove activities
- Optimize around one requested change
- Preserve as much of the plan as possible

**Success test:** User can say *"make this cheaper"* or *"less driving"* without losing the whole plan.

---

### Sprint 4 – Bookit Read-Only Integration
**Build:** Bookit adapter, `search_bookable_experiences`, `check_availability`

**Tasks:**
- Map Bookit fields to internal model
- Handle empty or stale availability gracefully
- Keep editorial and inventory sources distinguishable

**Success test:** Itinerary can be enriched with bookable options when they exist.

---

## What NOT to Build Yet

Avoid these in version one:
- Full end-to-end booking transactions inside the MCP
- Giant all-purpose tools with vague schemas
- Free-text outputs instead of structured payloads
- Complex personalisation memory before core planning works
- Over-engineered real-time sync unless clearly required

---

## Error Handling Standard

Each tool should return a predictable shape. Use this pattern:

```json
{
  "ok": false,
  "error_code": "NO_MATCHES",
  "message": "No matching trip ideas were found for the selected region and filters.",
  "details": {
    "region": "Northland"
  }
}
```

> Much better than throwing raw exceptions into the model loop.

---

## Logging and Observability

At minimum, log per tool call:
- Tool name
- Input payload
- Normalised query
- Result count
- Latency
- Error code (if failed)

This will matter quickly once live prompt testing begins.

---

## Testing Approach

Test each tool with **real user-style prompts**, not just developer fixtures.

**Example prompts:**
- *"I want a 4-day break in Nelson with good food and easy walks"*
- *"Plan a family day near Taupō without anything too expensive"*
- *"Make this itinerary more relaxed and remove long drives"*
- *"What bookable experiences fit this Queenstown day plan?"*

Goal: check not just correctness, but whether the tool is actually useful inside a conversational flow.

---

## Immediate Next Actions (Developer)

1. Finalise metadata schema
2. Choose MCP server framework (FastMCP recommended)
3. Implement `search_trip_ideas`
4. Define stable output contracts
5. Test against real Tripideas content
6. Then move to `build_day_itinerary`

---

## Summary

> The right first build is not *"an AI travel planner."*

It is:
- A **metadata-backed content engine**
- Exposed through a **few clean MCP tools**
- Capable of **generating and refining realistic trip ideas**
- With **Bookit added as a separate live inventory layer**

If built in that order, the MCP should become useful quickly and stay maintainable as scope grows.
