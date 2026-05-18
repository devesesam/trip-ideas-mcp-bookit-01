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
- Includes `has_aimetadata` flag so the caller knows whether to follow up
  with `get_place_summary` (which needs aiMetadata) or just link the page

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

from sanity_client import SanityClient  # noqa: E402


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
    """How this result matched the query: "exact" | "prefix" | "substring" """


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

    enriched.sort(key=lambda x: (x[0], x[1].title.lower()))
    results = [r for _, r in enriched[: inp.limit]]

    return FindPlaceByNameOutput(
        ok=True,
        query_echo=_echo(inp),
        count=len(enriched),
        results=results,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


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
    ]:
        print(f"\n--- {query} ---")
        out = find_place_by_name(query, client=client)
        if not out.ok:
            print(f"  ERROR: {out.error_code} — {out.message}")
            continue
        print(f"  count={out.count}, latency={out.latency_ms}ms")
        for r in out.results[:6]:
            ai = "✓" if r.has_aimetadata else "·"
            print(f"  [{r.match_rank:9s}] {ai} {r.title:35s} ({r.region or '?'} / {r.subRegion or '?'})")
