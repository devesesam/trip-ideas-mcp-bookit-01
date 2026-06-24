# Tag consolidations — 2026-06-24

This doc captures editorial consolidation decisions made on our side ahead of
the full corpus re-tag. Each consolidation can be reversed if Douglas asks
for the original tags to stay distinct — the procedure is in the
**Reversal** section of each entry.

The consolidations affect:
- `execution/tags/tag_definitions.py` — the LLM-facing definitions used by
  the re-tag pipeline. The consolidated tags' definitions live under the
  surviving umbrella tag's entry; the other entries are removed with an
  inline comment pointing here.
- `execution/normalize/tag_mapping.py` — left unchanged. The other tag
  entries stay mapped so the chatbot still understands them on any pages
  that currently carry them (until the re-tag pass actually removes them
  from those pages).
- **Sanity itself is untouched** — Douglas's tag documents still exist.
  Only the LLM's re-tagging behaviour changes.

---

## Consolidation 1 — "less-visited / quiet" cluster → `Hidden Gems`

**Decision (2026-06-24):** Sam confirmed four conceptually overlapping tags
should be consolidated into a single umbrella tag, `Hidden Gems`. Douglas
has not been formally asked yet — the catch-up email mentions this and
invites him to reverse if he disagrees.

**Tags collapsed into `Hidden Gems`:**

- `Off The Beaten Track`
- `Quiet Spots`
- `Remote Locations`

**Why consolidated:** in practice these all signal something close to "an
under-promoted place" and pages routinely fit more than one. A single
umbrella gives the chatbot a cleaner filter lever and reduces LLM ambiguity
during re-tagging.

**Where it sits in code:**

- `execution/tags/tag_definitions.py` — the `Hidden Gems` entry now carries
  the umbrella definition + the unioned keyword set from all four. The
  three other entries are replaced with one-line inline comments pointing
  here.
- `execution/normalize/tag_mapping.py` — all four entries still exist with
  their original mappings (no changes). After the re-tag pass actually
  removes the legacy tags from Sanity pages, those three mappings can also
  be deleted.

### Reversal procedure

If Douglas wants the four tags kept separate:

1. **`tag_definitions.py`** — restore the three removed entries (definitions
   below) and remove the consolidation note from the `Hidden Gems` entry,
   reverting its definition + keywords + negatives to the pre-consolidation
   form (also below).
2. **`tag_mapping.py`** — no changes needed (we never modified the four
   entries).
3. **Re-run the parity audit** (`python execution/audit/tag_mapping_parity.py`)
   to confirm the file structure validates.

### Original definitions for restore (verbatim from `tag_definitions.py`
before 2026-06-24)

#### `Hidden Gems` (original)

```python
    {
        "name": "Hidden Gems",
        "definition": (
            "Lesser-known places explicitly framed as off-the-radar in the "
            "article — 'few visitors', 'overlooked', 'locals' secret', 'don't "
            "see on Instagram'. Self-deprecating 'underrated' or 'should be "
            "more popular' framing qualifies. Genuinely popular places don't, "
            "even if 'hidden' appears in the prose."
        ),
        "positive_keywords": [
            r"\bhidden gem\b",
            r"\bhidden\b",
            r"\boff the beaten\b",
            r"\blesser[- ]?known\b",
            r"\boverlooked\b",
            r"\bundiscovered\b",
            r"\bsecret spot\b",
            r"\blocal[s']? secret\b",
            r"\bnot many people\b",
            r"\bunderrated\b",
        ],
        "negative_signals": [
            "famous",
            "popular",
            "well known",
            "iconic",
        ],
    },
```

#### `Off The Beaten Track` (original — removed 2026-06-24)

```python
    {
        "name": "Off The Beaten Track",
        "definition": (
            "Out-of-the-way places with low visitor numbers and limited "
            "facilities — distant ends of gravel roads, walk-in-only locations "
            "without major signage. Overlaps with 'Hidden Gems' (which is "
            "framing-focused) and 'Remote Locations' (which emphasises sheer "
            "distance). This tag is for places that are quietly known but not "
            "promoted."
        ),
        "positive_keywords": [
            r"\boff the beaten track\b",
            r"\boff the beaten path\b",
            r"\bless visited\b",
            r"\bfewer people\b",
            r"\bremote feel\b",
            r"\bget away from\b",
            r"\bquieter alternative\b",
            r"\bend of the road\b",
        ],
        "negative_signals": [],
    },
```

#### `Quiet Spots` (original — removed 2026-06-24)

```python
    {
        "name": "Quiet Spots",
        "definition": (
            "Peaceful, low-traffic places suited to slow visits — secluded "
            "bays, restful gardens, sheltered picnic spots, places explicitly "
            "framed as tranquil. Overlaps with 'Off The Beaten Track' but is "
            "more about atmosphere than distance."
        ),
        "positive_keywords": [
            r"\bquiet\b",
            r"\bpeaceful\b",
            r"\bsecluded\b",
            r"\btranquil\b",
            r"\brestful\b",
            r"\bcalm\b",
            r"\bgentle\b",
            r"\bunwind\b",
            r"\bget away\b",
        ],
        "negative_signals": [
            "busy",
            "popular",
            "crowded",
            "tourist hot spot",
        ],
    },
```

#### `Remote Locations` (original — removed 2026-06-24)

```python
    {
        "name": "Remote Locations",
        "definition": (
            "Genuinely remote places — substantial travel to reach, limited "
            "or no cell signal, no resident services nearby. East Cape, "
            "Catlins ends, Fiordland approaches, Hokitika south, Stewart "
            "Island. Different from 'Off The Beaten Track' (which is about "
            "low visibility) and 'Hidden Gems' (framing)."
        ),
        "positive_keywords": [
            r"\bremote\b",
            r"\bisolated\b",
            r"\bfar from\b",
            r"\bdistant\b",
            r"\bmiles from\b",
            r"\bno (?:cell )?signal\b",
            r"\bend of the road\b",
            r"\blast outpost\b",
            r"\bwilderness\b",
        ],
        "negative_signals": [
            "close to town",
            "popular",
        ],
    },
```

### Re-tagging implication if reversed AFTER the corpus re-tag

If Douglas reverses this after the re-tag pass has already applied (i.e.
pages tagged with the old three tags have been migrated to `Hidden Gems`),
the reversal also requires a re-tag of those pages back to their original
tags. Without that:

- Pages that had `Off The Beaten Track` only would lose the specific tag
  signal and only carry `Hidden Gems`.
- Same for `Quiet Spots`, `Remote Locations`.
- A second re-tag run with the restored four definitions would re-distribute
  the umbrella back into specifics, but the LLM has to re-judge each page
  from scratch.

So the cost of reversal grows over time. If Douglas is going to weigh in,
it's much cheaper to do so before the corpus re-tag.

---

## Consolidation 2 — "restoration / conservation" cluster

**Decision (2026-06-24):** Initially planned to consolidate
`Restoration Sites` + `Ecological Restoration` + `Conservation Projects`
into a single umbrella tag. **Sam reversed this on closer inspection** —
they're genuinely distinct concepts (active visitor engagement vs landscape-
level rebuild vs other restoration activity). All three tags are kept
separate in `tag_definitions.py`.

No code changes were applied for this cluster. This entry exists in this
doc as a marker so future readers (or future-us) know the decision was
considered and rejected.

---

## What the audit reports after these consolidations

The `tag_mapping_parity.py` audit was unchanged by these decisions:

- The four `Hidden Gems` cluster tags ALL still exist in Sanity, and all
  four still have entries in `tag_mapping.py`. So they appear under "CLEAN
  MAPPINGS" — the audit doesn't know that `tag_definitions.py` no longer
  carries the other three.
- The three `Restoration Sites` cluster tags are also all still present.

The only "stale" entries flagged by the audit remain the three new tags
pending Douglas's Sanity creation: `4WD Recommended`, `Seasonal Access for
Roads`, `Seasonal Access for Trails`.

---

## Decision audit trail

- 2026-06-18 (Sam): "Very interesting on those four overlapping hidden gem
  tags. I think these should be combined into one, but will flag this to
  Douglas. Again, those three [restoration] are very similar, I will flag
  to Douglas."
- 2026-06-24 (Sam, today): "Let's just consolidate those. Use 'Hidden Gems'
  for the first one and use 'Restoration Sites' for the second one. Then,
  we should make a note of this so that we can reassign/retag the articles
  with these two tags if Douglas says otherwise later."
- 2026-06-24 (Sam, ~10 minutes later, mid-execution): "Sorry to backtrack.
  I realised that Conservation Project is kind of different to Restoration
  Sites. And even Ecological Restoration. We should keep these three
  separate."

Net result: Hidden Gems cluster consolidated (4 → 1). Restoration cluster
kept separate (3 → 3, no change).
