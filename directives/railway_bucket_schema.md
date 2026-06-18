# Railway Bucket Schema — Phase 1 discovery report

**Source of truth for what's in the Tripideas Railway DB and how user "buckets" are modelled.** Read this before designing or implementing the bucket integration.

Probed **2026-06-18** against the staging environment using a project-scoped read token. Production not probed (token scope correctly limited to staging — the production schema is presumed identical since both run from the same Prisma migrations).

---

## Connection

| Field | Value |
|---|---|
| **Project** | `Trip Ideas` (id `a8521249-69da-494d-a33a-ba84cd8f4ae0`) |
| **Environments** | `staging`, `production` |
| **Services** | `web`, `Postgres`, `api` |
| **DB engine** | PostgreSQL 16.8 (managed by Prisma migrations) |
| **External host (staging)** | `shortline.proxy.rlwy.net:35355/railway` |
| **Internal host** | `postgres.railway.internal:5432/railway` |
| **Auth header** | `Project-Access-Token: <token>` for the GraphQL API (NOT `Bearer`) |
| **Schema** | single `public` schema |

The `api` service sitting between `web` and `Postgres` is significant — Tripideas.nz already has a backend layer that owns auth + business logic for buckets. The chat integration should prefer calling that `api` (Path B'), not bypassing it with direct DB reads (Path B).

---

## Tables (10 total in `public`)

### Place-saving surface

| Table | Purpose | Rows (staging) |
|---|---|---|
| **`Favourite`** | Flat per-user "I like this place" list — single row per `(user, place)`. | 179 |
| **`FavCollection`** | User-created "playlist of places" with a name (e.g. *"Best Idea"*, *"the Next trip"*). | 8 |
| **`FavCollectionItem`** | Join row: which `Favourite` belongs to which `FavCollection`. Many-to-many via favourites. | 29 |
| **`FavCollectionShare`** | Share a `FavCollection` with another user. | 2 |
| **`CollectionItemComment`** | Per-item comments inside a shared collection (e.g. *"Yep, keen on this one."*). | 3 |
| **`CollectionComment`** | Per-collection comments (collection-level discussion). | 2 |

### Itinerary surface (currently unused)

| Table | Purpose | Rows |
|---|---|---|
| `Itinerary` | Named ordered place plan, with `entryOrder` (array). | 0 |
| `ItineraryEntry` | A place in an itinerary, with an optional `note`. | 0 |

These exist but are unused as of 2026-06-18 — the feature is built into the data model but no users have created itineraries yet. This is the natural place to **write back** chat-built plans in a future sprint (out of scope for the read-only integration v1).

### Auth + system

| Table | Purpose | Rows |
|---|---|---|
| `User` | Tripideas user — `id`, `email`, `name`, `authId` (upstream auth provider ID, looks like Clerk/WorkOS ULIDs). | 72 |
| `_prisma_migrations` | Prisma's migration log. | 9 |

---

## What "bucket" actually means

Douglas's quote was *"Users can have content already selected in the Tripideas trip tool"*. Two candidate interpretations in the schema:

1. **`FavCollection`** — a named, ordered, shareable, commentable group of places. This is the trip-tool shape: the user gave it a name like *"the Next trip"* or *"Best Idea"*, deliberately curated which places to include, and can collaborate with other users on it.
2. **`Favourite`** — a flat per-user list of every place they've ever ★'d. Bigger and less intentional.

**Recommendation: the bucket = a `FavCollection`.** That matches the "selected for this trip" semantics; `Favourite` is a wishlist, not a trip plan. A `FavCollection` resolves to a specific list of `placeId`s via the `Favourite` join.

Concrete example — Douglas's own collection *"Best Idea"* (`fc_01kb1b26ksexwveksv8se2m9g2`):

| placeId | Sanity title |
|---|---|
| `00268b0a-3b30-4d44-80a5-c7d1ec7d7b33` | Te Hakapureirei Beach |
| `0f7c5bae-20f2-4d3c-b65e-f52a94ec7776` | Doctors Point |
| `666e762c-ee17-4902-9552-9e37c90ed4c0` | Monte Cecilia Park and Pah Homestead |
| `3605cd7c-ca7b-4160-863e-356a8a0a6d42` | Ahu Ahu Track |
| `5f41b968-5dbb-48bb-b883-44a7f3e47738` | Ahuriri River |
| `ec98c9e7-9a66-45fc-bffd-f997c1b1aa82` | Ahuriri Valley |

All 6 resolve cleanly through our existing [`render_places_on_map`](../execution/tools/render_places_on_map.py) — no missing IDs.

---

## Four discovery questions, answered

**1. What identifies a user?** `User.id` (ULID like `user_01jp7d486xfzx8fskw3wnrrgqk`). `authId` is the upstream-auth-provider ID and is the right thing to identify a user FROM the frontend auth context (e.g. Clerk session token → `authId` → `User.id` → their `FavCollection`s). The frontend almost certainly already knows the `authId` from the active session; the chat embed needs that to scope queries.

**2. What's the bucket schema?** Two-level: `FavCollection` is the bucket envelope (name, owner, comments, sharing), and `FavCollectionItem` joins it to `Favourite` rows which hold the actual `placeId`. To get a user's bucket as a flat list of Sanity IDs:

```sql
SELECT f."placeId"
FROM "FavCollection" c
JOIN "FavCollectionItem" i ON i."collectionId" = c.id
JOIN "Favourite" f ON f.id = i."favouriteId"
WHERE c.id = $1
ORDER BY f."createdAt" ASC;
```

A user can have multiple `FavCollection`s; the chat needs to know **which collection** to plan around. Either (a) the Tripideas page where the user opens the chat already has a single active collection scoped in URL/state and passes that collection ID, or (b) we ask the user "which trip should I work with?" if more than one exists.

**3. Are the place IDs `sanity._id` values?** **YES — verified.** `Favourite.placeId` is exactly the Sanity document `_id` (UUID v4 format). Zero translation layer needed; we can pass these straight to `build_trip_itinerary(include_doc_ids=[...])`, `render_places_on_map(sanity_doc_ids=[...])`, and `get_place_summary(sanity_doc_id=...)`.

**4. API access vs Postgres-direct?** Both work, but **the Tripideas `api` service is the better integration target** for any backend-fetch path. Direct Postgres reads would skip whatever auth + business logic that service enforces (e.g. share permissions on collections). For Phase 2, prefer:

- **Path A** (recommended): Tripideas.nz frontend pushes the active collection's `placeId` list into the chat embed via `data-bucket-ids` attribute or `postMessage`. No new server-side dependency.
- **Path B'**: If Path A isn't workable, query the Tripideas `api` service (not Postgres) for `GET /collections/:id/places` — needs Douglas's dev to confirm/build that endpoint.
- **Path B** (avoid): direct Railway Postgres reads. Lets us hold creds we shouldn't need and bypasses the api layer.

---

## Open Phase-2 questions to confirm with Douglas / Nick (his dev)

- Does the Tripideas frontend already have the active `FavCollection`'s `placeId` list loaded in JS state when the user opens the chat? (Almost certainly yes — they're rendered in the trip-tool UI.) If so, Path A is trivial.
- What identifies the user to the chat embed? An auth token, a `User.id`, an `authId`? We'd ideally never see the auth token — just the `User.id` or `FavCollection.id` is enough.
- Multi-collection case: how should the chat behave when a user has >1 bucket? Most-recently-edited? Show a picker?
- What's the production DB hostname (we only have staging access today)? Will need a separate production token for read-only access if we ever go Path B/B'.

---

## Read-only enforcement

- The Railway API token in `.env` is **project-scoped to staging only** — production access correctly denied during probing.
- Both probe scripts ([`railway_schema_probe.py`](../execution/audit/railway_schema_probe.py), [`railway_collection_join_probe.py`](../execution/audit/railway_collection_join_probe.py)) call `conn.set_session(readonly=True, autocommit=True)` — any accidental `INSERT/UPDATE/DELETE` will raise `psycopg2.errors.ReadOnlySqlTransaction` rather than mutate.
- The API discovery script ([`railway_api_discover.py`](../execution/audit/railway_api_discover.py)) only issues GraphQL `query` operations — no `mutation` helpers are defined.
- **Never use this token to write.** This is Douglas's client DB.

---

## Files involved

- [`execution/audit/railway_api_discover.py`](../execution/audit/railway_api_discover.py) — Railway GraphQL → find DATABASE_URL
- [`execution/audit/railway_schema_probe.py`](../execution/audit/railway_schema_probe.py) — Postgres → list tables + sample candidates
- [`execution/audit/railway_collection_join_probe.py`](../execution/audit/railway_collection_join_probe.py) — Postgres → full FavCollection → Favourite join, end-to-end
- [`.env`](../.env) — `RAILWAY_API_TOKEN`, `RAILWAY_PROJECT_ID`, `RAILWAY_DATABASE_URL` (gitignored)
- Plan: `C:\Users\damse\.claude\plans\can-we-plan-out-compiled-bunny.md`
