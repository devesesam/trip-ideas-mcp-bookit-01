"""Audit: NZ_REGIONS_REFERENCE in the system prompt vs Sanity's actual regions.

The system prompt hand-curates a list of NZ regions and aliases that the
chatbot uses to translate user utterances into the correct `region` /
`subRegion` tool inputs. Sanity is the source of truth for what regions and
subRegions actually exist. When the two drift, the chatbot can call tools
with names that don't exist and trips errors at runtime — like the
"Nelson Tasman" bug we hit in v0.13.2 (Sanity uses just "Tasman").

This script reports drift, in four buckets:

  ❌ DRIFT BUGS      regions/subRegions named in the prompt but absent from
                     Sanity. These are CHATBOT FAILURES — fix the prompt.
  ⚠️  BAD ALIASES    aliases pointing to a non-existent region/subRegion.
                     Same impact; same fix.
  ✅  MATCHES        clean — what's advertised exists.
  💡  SUGGESTIONS    regions/subRegions in Sanity not surfaced as aliases
                     anywhere. Purely informational — not a failure, but
                     potential missed conversational hooks.

Exits non-zero when DRIFT BUGS or BAD ALIASES are found, so this could be
wired into CI later if we want.

Run:
    python execution/audit/prompt_taxonomy_parity.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

# Need backend/ on sys.path too — the prompt module lives there
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_BACKEND_PATH = _PROJECT_ROOT / "backend"
if str(_BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(_BACKEND_PATH))

from registry import regions as regions_registry  # noqa: E402
from system_prompt import NZ_REGIONS_REFERENCE  # noqa: E402


# =====================================================================
# Parsers — extract what the prompt advertises
# =====================================================================


def _strip_paren(s: str) -> str:
    """'East Cape (Tūranganui-a-Kiwa)' → 'East Cape'."""
    return re.sub(r"\s*\([^)]*\)", "", s).strip()


def parse_advertised_regions(prompt: str) -> dict[str, list[str]]:
    """Return {'North Island': [...], 'South Island': [...]} from the prompt.

    Looks for blocks like:
        North Island regions:
          Northland, Auckland, Coromandel, ...
    """
    out: dict[str, list[str]] = {}
    for island in ("North Island", "South Island"):
        m = re.search(
            rf"{re.escape(island)}\s+regions:\s*\n((?:\s+.+\n?)+?)(?:\n|\Z)",
            prompt,
            re.MULTILINE,
        )
        if not m:
            out[island] = []
            continue
        block = m.group(1)
        # Flatten multi-line region lists into a single comma-separated string
        flat = " ".join(line.strip() for line in block.splitlines()).strip()
        names = [_strip_paren(s) for s in flat.split(",")]
        names = [n for n in names if n]
        out[island] = names
    return out


# Alias line: `"Foo" / "Bar"  → region=X, subRegion=Y`  or  `"Foo" → region=X`
_ALIAS_RE = re.compile(r'^\s*("[^"]+(?:"\s*/\s*"[^"]+)*")\s*→\s*(.+?)\s*$',
                       re.MULTILINE)


def parse_advertised_aliases(prompt: str) -> list[dict]:
    """Extract every `"X" → region=Y[, subRegion=Z]` line.

    Strips trailing parenthetical comments from the parsed values so inline
    annotations like "region=Hawke Bay  (Sanity uses no apostrophe + no 's')"
    parse to "Hawke Bay" rather than the full string.

    Returns a list of {keys: [...], region: str|None, subRegion: str|None}.
    """
    aliases: list[dict] = []
    for m in _ALIAS_RE.finditer(prompt):
        raw_keys, rhs = m.group(1), m.group(2)
        keys = [k.strip().strip('"') for k in raw_keys.split("/")]
        region_m = re.search(r"region=([^,]+?)(?:,|$)", rhs)
        sub_m = re.search(r"subRegion=([^,]+?)(?:,|$)", rhs)
        aliases.append({
            "keys": keys,
            "region": _strip_paren(region_m.group(1)).strip() if region_m else None,
            "subRegion": _strip_paren(sub_m.group(1)).strip() if sub_m else None,
        })
    return aliases


# =====================================================================
# Audit
# =====================================================================


def run_audit() -> int:
    print("=" * 78)
    print("  Prompt ↔ Sanity taxonomy parity audit")
    print("=" * 78)

    advertised = parse_advertised_regions(NZ_REGIONS_REFERENCE)
    aliases = parse_advertised_aliases(NZ_REGIONS_REFERENCE)

    reg = regions_registry._registry()
    sanity_region_names = {r.name for r in reg.regions}
    sanity_subregion_names_by_region: dict[str, set[str]] = {}
    for sr in reg.subRegions:
        sanity_subregion_names_by_region.setdefault(sr.region_name, set()).add(sr.name)

    advertised_flat = [n for names in advertised.values() for n in names]

    drift_bugs: list[str] = []
    bad_aliases: list[str] = []
    matches: list[str] = []
    suggestions: list[str] = []

    # --- 1. Regions advertised in prompt that don't exist in Sanity ---
    for name in advertised_flat:
        if name in sanity_region_names:
            matches.append(f"region {name!r}")
        else:
            drift_bugs.append(
                f"region {name!r} advertised in prompt but NOT in Sanity. "
                f"Closest: {_closest_match(name, sanity_region_names)}"
            )

    # --- 2. Aliases pointing to non-existent regions/subRegions ---
    for a in aliases:
        keys_str = " / ".join(repr(k) for k in a["keys"])
        if a["region"] and a["region"] not in sanity_region_names:
            bad_aliases.append(
                f"{keys_str} → region={a['region']!r} — region does not exist in Sanity. "
                f"Closest: {_closest_match(a['region'], sanity_region_names)}"
            )
            continue
        if a["region"] and a["subRegion"]:
            valid_subs = sanity_subregion_names_by_region.get(a["region"], set())
            if a["subRegion"] not in valid_subs:
                bad_aliases.append(
                    f"{keys_str} → subRegion={a['subRegion']!r} — not a subRegion of "
                    f"{a['region']!r} in Sanity. Available: {sorted(valid_subs)}"
                )
                continue
        matches.append(f"alias {keys_str} → region={a['region']!r} subRegion={a['subRegion']!r}")

    # --- 3. Regions in Sanity not surfaced anywhere in the prompt ---
    aliased_regions = {a["region"] for a in aliases if a["region"]}
    advertised_set = set(advertised_flat) | aliased_regions
    for sanity_name in sorted(sanity_region_names):
        if sanity_name not in advertised_set:
            suggestions.append(
                f"region {sanity_name!r} exists in Sanity but is not in "
                f"NZ_REGIONS_REFERENCE region list or any alias"
            )

    # --- Report ---
    if drift_bugs:
        print(f"\n❌ DRIFT BUGS ({len(drift_bugs)})")
        for b in drift_bugs:
            print(f"   {b}")

    if bad_aliases:
        print(f"\n⚠️  BAD ALIASES ({len(bad_aliases)})")
        for b in bad_aliases:
            print(f"   {b}")

    if suggestions:
        print(f"\n💡 SUGGESTIONS ({len(suggestions)})  — informational, not failures")
        for s in suggestions:
            print(f"   {s}")

    print(f"\n✅ MATCHES ({len(matches)})")
    print(f"   ({len(matches)} prompt entries verified against Sanity)")

    # --- Summary ---
    print()
    print("=" * 78)
    if drift_bugs or bad_aliases:
        print(f"  RESULT: {len(drift_bugs)} drift bug(s) + {len(bad_aliases)} bad alias(es). "
              f"Fix NZ_REGIONS_REFERENCE in backend/system_prompt.py.")
        print("=" * 78)
        return 1
    print(f"  RESULT: clean. {len(suggestions)} informational suggestion(s).")
    print("=" * 78)
    return 0


def _closest_match(needle: str, haystack: set[str]) -> str:
    """Quick spell-check helper: return the closest-looking Sanity name."""
    try:
        from rapidfuzz import process
        m = process.extractOne(needle, list(haystack))
        return f"{m[0]!r} (score {m[1]:.0f})" if m else "(none)"
    except ImportError:
        return "(rapidfuzz not installed)"


if __name__ == "__main__":
    # Windows consoles default to cp1252; force UTF-8 so ↔ / ❌ / ✅ render
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    sys.exit(run_audit())
