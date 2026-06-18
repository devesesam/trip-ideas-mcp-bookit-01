# Re: Location Association Framework — findings & a proposed build order

Thanks Douglas — this is a strong piece of thinking and the diagnosis is right. Straight-line
distance genuinely is the weak link: our itinerary engine currently estimates travel as
`haversine × 1.4 ÷ 60 km/h`, which is blind to harbours, mountains and road corridors — exactly
the failure modes you list.

Before designing schema or hand-tagging ~1,500 places, I ran a read-only audit over the live
corpus to test one question: **how much of what the framework needs do we already have?** The
answer reshapes the build order. Numbers below are from that audit (1,558 place pages).

## What we already have (and aren't using)

Every place article's final-paragraph "nearby" references are **already extracted** into structured
metadata (`aiMetadata.nearby_places`) on each page. The editorial gold you want to preserve is
sitting in the database right now — it's just **never used** when the chatbot builds an itinerary
(it only shows up on the single-place detail view). The engine ignores it and falls back to
geometry.

What the audit found in that existing data:

- **Coverage is high.** 94% of pages already carry ≥1 editorial nearby link; **67% carry ≥3** —
  enough to fill a "minimum 4" card today, with no new editorial work.
- **The references resolve.** 76% of them point to another real page in the corpus (matched within
  the same region, so no cross-country name collisions). Another ~17% are "dangling" — they name a
  town, a region, or a non-page attraction rather than one of our pages. Those dangling names are
  themselves a signal (see Destination Areas below).
- **Coherent groups fall out automatically.** Running community detection on the editorial graph
  produces **26 clean clusters covering 99.7%** of the linked places — and it correctly separates,
  e.g., the Omaha/Matakana north cluster from the Waitākere/Arataki west cluster (a naive
  "everything within 30 km" approach wrongly merges all of metro Auckland into one 300-place blob).
- **The editorial signal beats geometry in exactly the ways you predicted.** 308 editorial links
  span >50 km — places deliberately linked to their gateway (e.g. *Aoraki/Mt Cook → Christchurch,
  "4.5 hours"*) that straight-line distance treats as unrelated. Conversely, 3,244 pairs sit <5 km
  apart with **no** editorial link — the across-water / across-valley / "close but you'd never
  combine them" cases (e.g. *Rakiura ↔ Ulva Island*, across water) where pure distance would wrongly
  suggest a pairing.

## What this means for the framework

Your instincts are right; I'd only change the **order of operations**. The doc frames this as
"build a new metadata layer and tag the corpus." But the highest-leverage first move isn't
tagging — it's **using the editorial graph we already have**. That delivers your stated goal
("preserve editorial quality while automating") with assets in hand, and it lets us validate the
Nearby Group concept with real numbers before committing editors to 1,500 places of work.

Two refinements worth calling out:

1. **Your two layers have very different costs.** *Destination Areas* (~dozens of broad areas like
   Matakana Coast) are cheap and high-value, and partly derivable already — the dangling references
   and the community clusters both point at them. *Nearby Groups* (fine corridors, multi-membership)
   are where the real cost lives. They shouldn't be treated as one project.

2. **"Drive time as the primary signal" needs a routing source.** The editorial metadata almost
   never records it (a usable distance/time appears on <10% of links, a confidence score on <1%).
   So travel time has to come from a routing API budget or a precomputed drive-time matrix within
   groups — not from the editorial text. Worth deciding early rather than assuming.

## Proposed phased approach (bootstrap first)

- **Phase 1 — Use what we have (low cost, biggest immediate win).** Build the place→place
  association graph from the existing `nearby_places` data and feed it into candidate generation as
  the primary signal, with geometry as fallback. This fixes the "places separated by water/mountains"
  problem for the ~67% of places that already have rich editorial links — without any new metadata.

- **Phase 2 — Destination Areas (cheap, high value).** Stand up the broad-area layer, seeding it
  from the community clusters + the most-named dangling references (gateway towns/regions). This is
  the layer that also pays off for search, navigation and collections.

- **Phase 3 — Nearby Groups, by review not by hand.** Don't tag 1,500 places from scratch.
  Auto-derive candidate groups via community detection (≈26–100 groups depending on granularity) and
  have editors **review and refine** those groups plus the ~106 genuinely orphaned places that have
  no resolvable editorial links. This is precisely the "review only the exceptions" process you
  proposed in the Validation section — and the data shows the exception set is small.

- **Phase 4 — Travel time.** Once groups exist, layer in real drive/walk time (routing API or
  precomputed matrix) as the ranking signal you describe.

## Open decisions for you

1. Granularity of Nearby Groups — tight corridors (Omaha–Tāwharanui scale) or broader (≈26
   region-ish clusters)? The data supports either; it's an editorial call.
2. Routing budget — are we willing to fund a drive-time source, or precompute a within-group matrix?
3. The ~17% dangling references — promote the recurring ones (towns/regions) into Destination Areas,
   or leave them as text?

Happy to walk through the full audit (the per-edge data is all there) or prototype Phase 1 against a
couple of regions so you can see the recommendations change.

---
*Backing data: read-only audit of `aiMetadata.nearby_places` across 1,558 pages; no content was
modified and no AI/API costs incurred. Full report: `.tmp/nearby_graph_spike.md`.*
