"""`find_place_by_name` — locate Sanity page docs by their own title or slug.

Companion to `search_places` for the "I know the name but not the doc ID" gap.
search_places relies on `length(aiMetadata) > 10` as a GROQ pre-filter, which
silently drops the ~180 pages that have no aiMetadata yet (e.g. Hamiltons Gap,
Kaiaua at time of writing). This tool deliberately skips that filter so name
lookups work even on thin-data pages — the LLM can then surface the page link
or call `get_place_summary` for full detail.

Match strategy:
- Substring match against both `title` and `slug.current`, case-insensitive
- Optional `region` scope to disambiguate common names (e.g. "Mission Bay"
  is both an Auckland suburb and a Christchurch beach)
- Returns up to `limit` results ranked: exact-title > prefix > substring
- If substring match returns zero, falls back to fuzzy matching via
  `rapidfuzz.fuzz.token_set_ratio` against an in-memory index of all
  page titles/slugs. Score >= 80 returns as `match_rank="fuzzy"` with
  the corresponding `fuzzy_score`; otherwise returns the top 3 candidates
  with `match_rank="fuzzy_no_match"` so the chat layer can ask the user
  to confirm ("Did you mean Sandymount?").
- Includes `has_aimetadata` flag so the caller knows whether to follow up
  with `get_place_summary` (which needs aiMetadata) or just link the page

Performance notes:
- Exact substring path is unchanged: one Sanity round-trip, ~200 ms.
- Fuzzy fallback only runs when the substring tier returns zero. First
  miss per process pays one extra ~300 ms GROQ round-trip to populate
  `_PLACE_INDEX_CACHE` (~1500 docs); subsequent fuzzy lookups are pure
  in-memory and <10 ms. Cache invalidates only on process restart
  (acceptable for v1 — Sanity content changes infrequently).

Output stays small — title, ids, location refs, slug, the booleans —
because the typical follow-up is another tool call, not direct rendering.
"""

from __future__ import annotations

import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from rapidfuzz import fuzz  # noqa: E402

from sanity_client import SanityClient  # noqa: E402


# Module-level cache for the full place-name index. Lazy-populated on the
# first fuzzy fallback per process; reused for the process lifetime.
_PLACE_INDEX_CACHE: Optional[list[dict]] = None
_PLACE_INDEX_GROQ = (
    '*[_type == "page" && defined(title)]{'
    '_id, title, "slug": slug.current, '
    '"region": subRegion->region->name, '
    '"subRegion": subRegion->name, '
    '"has_aimetadata": length(aiMetadata) > 10'
    '}'
)
_FUZZY_HIT_THRESHOLD = 80   # token_set_ratio >= 80 → returned as match_rank="fuzzy"
_FUZZY_NEAR_MISS_TOP_N = 3  # how many candidates to surface when nothing scores >= threshold


@dataclass
class FindPlaceByNameInput:
    name: str                                    # REQUIRED — substring to match (case-insensitive)
    region: Optional[str] = None                 # optional region scope
    limit: int = 10


@dataclass
class FindPlaceByNameResult:
    sanity_doc_id: str
    title: str
    slug: Optional[str]
    region: Optional[str]
    subRegion: Optional[str]
    has_aimetadata: bool
    """True when get_place_summary will return rich detail; False means the
    page exists but aiMetadata hasn't been generated yet — link only."""
    match_rank: str
    """How this result matched the query:
    "exact" | "prefix" | "substring" | "fuzzy" | "fuzzy_no_match"

    The first three come from the GROQ substring tier. "fuzzy" means the
    substring tier returned nothing but rapidfuzz found a close match
    (token_set_ratio >= 80). "fuzzy_no_match" means even the fuzzy tier
    didn't clear the threshold — the result is the best candidate the
    fuzzy tier could find, returned so the chat layer can ask the user
    to confirm rather than silently dropping the place.
    """
    fuzzy_score: Optional[int] = None
    """rapidfuzz token_set_ratio (0-100) for the fuzzy tiers. None for the
    substring tiers (exact/prefix/substring) where scoring doesn't apply."""


@dataclass
class FindPlaceByNameOutput:
    ok: bool
    query_echo: dict
    count: int
    results: list[FindPlaceByNameResult]
    latency_ms: int
    error_code: Optional[str] = None
    message: Optional[str] = None


def find_place_by_name(
    inp: FindPlaceByNameInput,
    client: Optional[SanityClient] = None,
) -> FindPlaceByNameOutput:
    started = time.monotonic()
    client = client or SanityClient()

    raw = (inp.name or "").strip()
    if not raw:
        return FindPlaceByNameOutput(
            ok=False, query_echo=_echo(inp), count=0, results=[],
            latency_ms=int((time.monotonic() - started) * 1000),
            error_code="EMPTY_NAME", message="`name` must be a non-empty string.",
        )

    # GROQ `match` supports `*term*` wildcards on string fields.
    wildcard = f"*{raw}*"
    clauses = ['_type == "page"', '(title match $term || slug.current match $term)']
    params: dict[str, Any] = {"term": wildcard}
    if inp.region:
        clauses.append("subRegion->region->name == $region")
        params["region"] = inp.region

    groq = (
        f"*[{' && '.join(clauses)}]{{"
        "_id, title, \"slug\": slug.current, "
        "\"region\": subRegion->region->name, "
        "\"subRegion\": subRegion->name, "
        "\"has_aimetadata\": length(aiMetadata) > 10"
        "} | order(title asc)"
    )

    try:
        docs = client.query(groq, params) or []
    except Exception as e:  # noqa: BLE001 — defensive, never crash chat
        return FindPlaceByNameOutput(
            ok=False, query_echo=_echo(inp), count=0, results=[],
            latency_ms=int((time.monotonic() - started) * 1000),
            error_code="SANITY_ERROR", message=str(e),
        )

    needle = raw.lower()
    enriched: list[tuple[int, FindPlaceByNameResult]] = []
    for d in docs:
        title = (d.get("title") or "").strip()
        slug = d.get("slug")
        title_lower = title.lower()
        slug_lower = (slug or "").lower()

        # Rank: 0=exact title, 1=prefix, 2=substring (lower = better)
        if title_lower == needle:
            rank, label = 0, "exact"
        elif title_lower.startswith(needle) or slug_lower.startswith(needle):
            rank, label = 1, "prefix"
        else:
            rank, label = 2, "substring"

        enriched.append((rank, FindPlaceByNameResult(
            sanity_doc_id=d["_id"],
            title=title or "(untitled)",
            slug=slug,
            region=d.get("region"),
            subRegion=d.get("subRegion"),
            has_aimetadata=bool(d.get("has_aimetadata")),
            match_rank=label,
        )))

    # Fuzzy fallback — only runs if the substring tier returned nothing.
    # Preserves the ~95% fast path: no extra Sanity call when an exact /
    # substring match exists. Fuzzy results are returned in score order
    # (highest first), bypassing the rank-then-alpha sort below.
    if not enriched:
        fuzzy_results = _fuzzy_lookup(raw, inp.region, inp.limit, client)
        return FindPlaceByNameOutput(
            ok=True,
            query_echo=_echo(inp),
            count=len(fuzzy_results),
            results=fuzzy_results,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    enriched.sort(key=lambda x: (x[0], x[1].title.lower()))
    results = [r for _, r in enriched[: inp.limit]]

    return FindPlaceByNameOutput(
        ok=True,
        query_echo=_echo(inp),
        count=len(enriched),
        results=results,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def _get_place_index(client: SanityClient) -> list[dict]:
    """Return the cached full-corpus place-name index, populating on first call.

    Cached at module level for the process lifetime. On Modal this means the
    index is refreshed every container cold start (~hourly), which is fine
    given Sanity content changes infrequently.
    """
    global _PLACE_INDEX_CACHE
    if _PLACE_INDEX_CACHE is None:
        _PLACE_INDEX_CACHE = client.query(_PLACE_INDEX_GROQ, {}) or []
    return _PLACE_INDEX_CACHE


def _fuzzy_lookup(
    raw: str,
    region: Optional[str],
    limit: int,
    client: SanityClient,
) -> list[FindPlaceByNameResult]:
    """Score the full place-name index against `raw` and return the best matches.

    Returns up to `limit` results above the hit threshold (match_rank="fuzzy"),
    OR — if nothing clears the threshold — the top N near-misses
    (match_rank="fuzzy_no_match") so the chat layer can ask the user to confirm.
    """
    index = _get_place_index(client)
    if region:
        index = [d for d in index if d.get("region") == region]

    scored: list[tuple[int, dict]] = []
    for d in index:
        title = (d.get("title") or "").strip()
        slug = d.get("slug") or ""
        score = max(
            fuzz.token_set_ratio(raw, title),
            fuzz.token_set_ratio(raw, slug),
        )
        if score > 0:
            scored.append((score, d))

    if not scored:
        return []

    scored.sort(key=lambda x: -x[0])
    hits = [s for s in scored if s[0] >= _FUZZY_HIT_THRESHOLD]
    label = "fuzzy" if hits else "fuzzy_no_match"
    chosen = hits if hits else scored[:_FUZZY_NEAR_MISS_TOP_N]

    return [
        FindPlaceByNameResult(
            sanity_doc_id=d["_id"],
            title=(d.get("title") or "(untitled)").strip(),
            slug=d.get("slug"),
            region=d.get("region"),
            subRegion=d.get("subRegion"),
            has_aimetadata=bool(d.get("has_aimetadata")),
            match_rank=label,
            fuzzy_score=int(score),
        )
        for score, d in chosen[:limit]
    ]


def _echo(inp: FindPlaceByNameInput) -> dict:
    return asdict(inp)


__all__ = [
    "find_place_by_name",
    "FindPlaceByNameInput",
    "FindPlaceByNameOutput",
    "FindPlaceByNameResult",
]


# =====================================================================
# CLI smoke test
# =====================================================================


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    client = SanityClient()
    for query in [
        FindPlaceByNameInput(name="Hamiltons Gap"),
        FindPlaceByNameInput(name="Kaiaua"),
        FindPlaceByNameInput(name="Hamilton Gardens"),
        FindPlaceByNameInput(name="Mission Bay"),                          # ambiguous — multiple regions
        FindPlaceByNameInput(name="Mission Bay", region="Auckland"),       # disambiguated
        FindPlaceByNameInput(name="penguin"),                              # substring
        # Fuzzy-fallback cases (from Douglas's Dunedin test conversation):
        FindPlaceByNameInput(name="Sandmount"),                            # → expect "Sandymount" via fuzzy
        FindPlaceByNameInput(name="Alans Beach"),                          # → expect "Allans Beach" via fuzzy
        FindPlaceByNameInput(name="Sandymount"),                           # regression: should stay match_rank=exact, no fuzzy
        FindPlaceByNameInput(name="Xyzqwerty"),                            # → expect fuzzy_no_match with low scores
        FindPlaceByNameInput(name="Sandmount", region="Wellington"),       # fuzzy + region filter (expect no Otago matches)
        FindPlaceByNameInput(name="Sandmount"),                            # second call → index cache hit, no extra GROQ
    ]:
        print(f"\n--- {query} ---")
        out = find_place_by_name(query, client=client)
        if not out.ok:
            print(f"  ERROR: {out.error_code} — {out.message}")
            continue
        print(f"  count={out.count}, latency={out.latency_ms}ms")
        for r in out.results[:6]:
            ai = "✓" if r.has_aimetadata else "·"
            score = f" score={r.fuzzy_score}" if r.fuzzy_score is not None else ""
            print(f"  [{r.match_rank:14s}] {ai} {r.title:35s} ({r.region or '?'} / {r.subRegion or '?'}){score}")
