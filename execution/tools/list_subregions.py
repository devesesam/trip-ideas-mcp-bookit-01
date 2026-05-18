"""`list_subregions` — return the live sub-region taxonomy for a region.

Solves the "what's the actual sub-region tag string?" problem surfaced in
Douglas's test transcript: the LLM guessed `Downtown Auckland` when the real
tag is `Central Auckland`, then had to be corrected. The taxonomy lives in
Sanity and grows over time; hardcoding it in the system prompt rots.

This tool returns the live list with place counts so the LLM can:
  1. Pick the exact correct sub-region string for `search_places`
  2. Know which sub-regions have meaningful content vs. are still thin
  3. Disambiguate user phrasings ("central Auckland" → `Central Auckland`)

Also used at backend startup to compose a taxonomy snapshot for the system
prompt — see `backend/orchestrator.py` / `backend/system_prompt.py`.
"""

from __future__ import annotations

import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from sanity_client import SanityClient  # noqa: E402


@dataclass
class SubRegionEntry:
    name: str
    place_count: int


@dataclass
class ListSubRegionsOutput:
    ok: bool
    region: str
    subRegions: list[SubRegionEntry] = field(default_factory=list)
    total_places: int = 0
    latency_ms: int = 0
    error_code: Optional[str] = None
    message: Optional[str] = None


def list_subregions(
    region: str,
    client: Optional[SanityClient] = None,
) -> ListSubRegionsOutput:
    started = time.monotonic()
    client = client or SanityClient()

    if not region or not region.strip():
        return ListSubRegionsOutput(
            ok=False, region=region or "",
            latency_ms=int((time.monotonic() - started) * 1000),
            error_code="EMPTY_REGION", message="`region` must be a non-empty string.",
        )

    groq = (
        '*[_type == "subRegion" && region->name == $region]{'
        'name, '
        '"place_count": count(*[_type == "page" && subRegion._ref == ^._id])'
        '} | order(place_count desc, name asc)'
    )

    try:
        rows = client.query(groq, {"region": region}) or []
    except Exception as e:  # noqa: BLE001 — defensive
        return ListSubRegionsOutput(
            ok=False, region=region,
            latency_ms=int((time.monotonic() - started) * 1000),
            error_code="SANITY_ERROR", message=str(e),
        )

    entries = [
        SubRegionEntry(name=r.get("name") or "(unnamed)",
                       place_count=int(r.get("place_count") or 0))
        for r in rows
    ]
    total = sum(e.place_count for e in entries)

    return ListSubRegionsOutput(
        ok=True,
        region=region,
        subRegions=entries,
        total_places=total,
        latency_ms=int((time.monotonic() - started) * 1000),
    )


# =====================================================================
# Convenience: full-NZ taxonomy snapshot for system-prompt injection
# =====================================================================


def build_taxonomy_snapshot(client: Optional[SanityClient] = None) -> str:
    """Single GROQ call that returns the full region → subRegion → count map
    formatted as a compact text block. Used at backend startup so the LLM
    sees the live taxonomy on every request without needing a tool call.

    Output shape (~1-2 KB depending on content growth):

        Auckland (284): Central Auckland (32), North Auckland (28), ...
        Northland (95): Bay of Islands (24), Kauri Coast (18), ...
        ...
    """
    client = client or SanityClient()
    groq = (
        '*[_type == "subRegion"]{'
        'name, '
        '"region": region->name, '
        '"place_count": count(*[_type == "page" && subRegion._ref == ^._id])'
        '}'
    )
    try:
        rows = client.query(groq) or []
    except Exception:
        return ""

    # Group by region, sort sub-regions by place_count desc
    by_region: dict[str, list[tuple[str, int]]] = {}
    for r in rows:
        reg = r.get("region")
        if not reg:
            continue
        by_region.setdefault(reg, []).append(
            (r.get("name") or "(unnamed)", int(r.get("place_count") or 0))
        )

    lines: list[str] = []
    for reg in sorted(by_region):
        subs = sorted(by_region[reg], key=lambda x: (-x[1], x[0]))
        total = sum(c for _, c in subs)
        formatted = ", ".join(f"{name} ({count})" for name, count in subs)
        lines.append(f"{reg} ({total}): {formatted}")
    return "\n".join(lines)


__all__ = [
    "list_subregions",
    "build_taxonomy_snapshot",
    "ListSubRegionsOutput",
    "SubRegionEntry",
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
    for region in ["Auckland", "Otago", "Wellington", "Coromandel"]:
        out = list_subregions(region, client=client)
        if not out.ok:
            print(f"\n{region}: ERROR {out.error_code}: {out.message}")
            continue
        print(f"\n{region} — total {out.total_places} places across {len(out.subRegions)} sub-regions ({out.latency_ms}ms)")
        for e in out.subRegions:
            print(f"  {e.place_count:4d}  {e.name}")

    print("\n" + "=" * 72)
    print("Full taxonomy snapshot (for system-prompt injection):")
    print("=" * 72)
    snapshot = build_taxonomy_snapshot(client=client)
    print(snapshot)
    print(f"\n[snapshot is {len(snapshot)} chars]")
