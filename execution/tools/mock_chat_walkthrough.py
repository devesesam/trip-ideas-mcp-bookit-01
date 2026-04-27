"""Mock conversation walkthrough — exercise the tool contracts.

NOT the chat orchestrator (Sprint 3). This is a hand-scripted "what would
a user-and-LLM exchange look like end-to-end?" — useful for spotting
contract gaps and seeing whether tool outputs compose into something a
chat LLM could actually narrate.

Each turn shows:
  USER: ...                — the message the user might send
  → tool_call(...)         — what the orchestrator would call
  TOOL OUTPUT: ...         — the relevant fields from the tool's response
  CHAT (paraphrased): ...  — what a chat reply might sound like

Run from project root:
    python execution/tools/mock_chat_walkthrough.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from sanity_client import SanityClient  # noqa: E402
from tools.build_day_itinerary import (  # noqa: E402
    BuildDayInput, build_day_itinerary,
)
from tools.get_place_summary import get_place_summary  # noqa: E402
from tools.search_places import (  # noqa: E402
    NearFilter, SearchPlacesInput, search_places,
)


def banner(text: str) -> None:
    print(f"\n{'=' * 78}\n  {text}\n{'=' * 78}")


def divider() -> None:
    print("-" * 78)


def main() -> None:
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    client = SanityClient()

    # ============================================================
    # SCENARIO 1 — Vague start, narrow to a day plan
    # ============================================================
    banner("SCENARIO 1 — Coastal weekend in Northland for couples")

    print("\nUSER: I'm thinking about a coastal weekend in Northland with my partner.")
    divider()

    print("→ search_places(region='Northland', themes=['coastal'], limit=8)")
    sp = search_places(SearchPlacesInput(
        region="Northland", themes=["coastal"], limit=8,
    ), client=client)
    print(f"TOOL OUTPUT: count={sp.count}, latency={sp.latency_ms}ms, "
          f"top facet by_subRegion={dict(list(sp.facets['by_subRegion'].items())[:4])}")
    for r in sp.results[:5]:
        print(f"  · {r.title:38s} sub={r.subRegion!r:24s}  themes={r.themes_derived[:3]}")
    print()
    print("CHAT: I found 76 coastal places in Northland — strongest in the Far North,")
    print("      Kauri Coast, and Tutukaka Coast. A few that stood out: Doubtless Bay,")
    print("      Otito Track, Matauri Bay, Kai Iwi Lakes, Waitangi. Want me to plan a")
    print("      day around one of these as a base?")

    # ============================================================
    # SCENARIO 2 — Build a day from the conversation context
    # ============================================================
    banner("SCENARIO 2 — Day around Paihia (chosen by user)")

    print("\nUSER: Let's do a day around Paihia.")
    divider()
    print("→ build_day_itinerary(base_location='Paihia', region='Northland', "
          "themes=['coastal'], pace='balanced')")
    day = build_day_itinerary(BuildDayInput(
        base_location="Paihia",
        region="Northland",
        themes=["coastal"],
        pace="balanced",
        candidate_radius_km=40,
    ), client=client)
    if not day.ok:
        print(f"TOOL OUTPUT: ERROR {day.error_code}: {day.message}")
        chosen_doc_id = sp.results[0].sanity_doc_id if sp.results else None
    else:
        print(f"TOOL OUTPUT: pool={day.candidate_pool_size}, latency={day.latency_ms}ms")
        for s in day.day_plan.slots:
            if s.slot_type == "place" and s.place:
                print(f"  [{s.start_time}-{s.end_time}] PLACE   {s.place.title:38s} "
                      f"({s.place.location_settlement or '—'})")
            elif s.slot_type == "travel_gap" and s.travel:
                print(f"  [{s.start_time}-{s.end_time}] travel  {s.travel.from_settlement or '—'} → "
                      f"{s.travel.to_settlement or '—'} ({s.travel.estimated_km}km)")
            elif s.slot_type == "meal_gap" and s.meal:
                print(f"  [{s.start_time}-{s.end_time}] {s.meal.meal:7s} suggest: {s.meal.suggested_settlement or '—'}")
        if day.feasibility:
            print(f"  Feasibility: active={day.feasibility.total_active_minutes}min, "
                  f"longest_drive={day.feasibility.longest_drive_minutes}min")
        if day.unfilled_requests:
            print(f"  Unfilled: {day.unfilled_requests[0]}")
        chosen_doc_id = next(
            (s.place.sanity_doc_id for s in day.day_plan.slots
             if s.slot_type == "place" and s.place), None
        )
    print()
    print("CHAT: Here's a balanced day starting in Paihia. Three places, lunch in")
    print("      the middle. I don't have specific restaurant data yet — try a cafe in")
    print("      whichever settlement we're closest to at lunchtime.")

    # ============================================================
    # SCENARIO 3 — Drill into one place from the itinerary
    # ============================================================
    banner("SCENARIO 3 — Drill into one place")

    if not chosen_doc_id:
        print("(No place chosen from previous turn — skipping)")
    else:
        print("\nUSER: Tell me more about the first place.")
        divider()
        print(f"→ get_place_summary(sanity_doc_id={chosen_doc_id!r})")
        summary = get_place_summary(chosen_doc_id, client=client)
        print(f"TOOL OUTPUT: title={summary.title!r}, "
              f"latency={summary.latency_ms}ms")
        print(f"  themes={summary.themes}, intensity={summary.physical_intensity}, "
              f"duration={summary.duration_band}, dog={summary.dog_friendly_kind}")
        print(f"  Description: {summary.description[:180]}{'…' if len(summary.description) > 180 else ''}")
        print(f"  Attractions ({len(summary.attractions)}): {summary.attractions[:3]}")
        print(f"  Activities ({len(summary.activities)}): {summary.activities[:3]}")
        print(f"  Local tips: {summary.local_tips[:2]}")
        if summary.nearby_places:
            print(f"  Nearby ({len(summary.nearby_places)}): {[p['name'] for p in summary.nearby_places[:4]]}")
        if summary.track_trail:
            tt = summary.track_trail
            print(f"  Track: {tt.get('name')!r} — {tt.get('primary_type')} / {tt.get('difficulty')}")
        print()
        print(f"CHAT: {summary.title} — {summary.description[:120]}{'…' if len(summary.description) > 120 else ''}")
        print(f"      Best for: {', '.join(summary.themes[:3])}. Plan to spend a half-day or so.")

    # ============================================================
    # SCENARIO 4 — Multi-region road-trip shape (no build_trip yet)
    # ============================================================
    banner("SCENARIO 4 — Road trip Nelson → Christchurch (the user's example)")
    print("\nUSER: What if I want to do a 4-day road trip from Nelson to Christchurch?")
    divider()
    print("Note: build_trip_itinerary doesn't exist yet (Sprint 3). For now we'd")
    print("simulate by anchoring each day's base in a different region along the route:")
    print()
    route_anchors = [
        ("Day 1", "Nelson", "Nelson Tasman"),
        ("Day 2", "Picton", "Marlborough"),
        ("Day 3", "Kaikoura", "Canterbury"),
        ("Day 4", "Christchurch", "Canterbury"),
    ]
    for day_label, base, region in route_anchors:
        print(f"  {day_label}: build_day_itinerary(base={base!r}, region={region!r}, pace='balanced')")
    print()
    print("Quick run of Day 2 (Picton) to verify the pattern works:")
    divider()
    day2 = build_day_itinerary(BuildDayInput(
        base_location="Picton", region="Marlborough", pace="balanced",
        candidate_radius_km=40,
    ), client=client)
    if not day2.ok:
        print(f"  ERROR: {day2.error_code}: {day2.message}")
    else:
        print(f"  pool={day2.candidate_pool_size}, latency={day2.latency_ms}ms")
        for s in day2.day_plan.slots:
            if s.slot_type == "place" and s.place:
                print(f"    [{s.start_time}] {s.place.title} ({s.place.location_settlement})")
            elif s.slot_type == "meal_gap":
                print(f"    [{s.start_time}] lunch")
    print()
    print("CHAT: I can sketch this out as four day-plans, one per anchor town. Once we")
    print("      have build_trip_itinerary, this'll get smarter — it'll vary themes")
    print("      across days so you don't get the same kind of place every day.")

    # ============================================================
    # SCENARIO 5 — Refinement (no tool yet, conceptual)
    # ============================================================
    banner("SCENARIO 5 — Refinement (preview of what refine_itinerary will handle)")
    print("\nUSER: Day 2 is too much driving. Make it more relaxed.")
    divider()
    print("Note: refine_itinerary doesn't exist yet (Sprint 3). When built, it would:")
    print("  → refine_itinerary(existing_plan=<day2>,")
    print("                     change_type='change_pace',")
    print("                     new_constraints={'pace': 'relaxed', 'max_drive_minutes_between_stops': 20})")
    print("  → returns updated_plan + diff (slots replaced/removed, params changed)")
    print()
    print("Until that exists, the orchestrator can call build_day_itinerary again with")
    print("the relaxed params + include_doc_ids of slots the user wants to keep.")

    print("\n" + "=" * 78)
    print("  Walkthrough complete. Tools compose into a usable conversational shape.")
    print("=" * 78)


if __name__ == "__main__":
    main()
