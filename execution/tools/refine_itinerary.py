"""`refine_itinerary` — adjust an existing day plan based on a structured change request.

The chat orchestrator interprets the user's natural-language utterance into a
structured `change_type` + `new_constraints` before calling this tool. This
keeps the tool deterministic — no LLM calls inside.

Branching logic by `change_type`:
  - `replace_slot` / `remove_slot` / `add_slot` → SURGICAL: touch only the
    target slot (and adjacent travel_gaps); preserve everything else exactly.
  - `change_pace` / `change_timing` / `change_themes` / `change_intensity`
    / `change_budget` → PARTIAL REBUILD: re-run build_day_itinerary with
    the updated parameters and `include_doc_ids = preserve_doc_ids` so
    accepted slots survive.
  - `broad_adjustment` → FULL REBUILD: ignore most preserves, merge new
    constraints with the original query, re-run build_day_itinerary.

Output includes a `diff` summarizing what changed (slots replaced, removed,
added, parameters modified, travel_gaps recomputed) so the chat can narrate
the change naturally.
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

from aimetadata import parse  # noqa: E402
from sanity_client import SanityClient  # noqa: E402
from tools.build_day_itinerary import (  # noqa: E402
    BuildDayInput, BuildDayOutput, DayPlan, Slot,
    _drive_minutes, _hhmm_to_min, _make_meal_gap_slot,
    _make_place_slot, _make_travel_gap_slot, _min_to_hhmm,
    DURATION_MINUTES_BY_BAND, build_day_itinerary,
)
from tools.search_places import (  # noqa: E402
    NearFilter, SearchPlaceResult, SearchPlacesInput, search_places,
)


CHANGE_TYPES = {
    "replace_slot",
    "remove_slot",
    "add_slot",
    "change_pace",
    "change_timing",
    "change_themes",
    "change_intensity",
    "change_budget",
    "broad_adjustment",
}


@dataclass
class RefineInput:
    existing_plan: DayPlan                              # the plan to modify
    change_type: str                                    # one of CHANGE_TYPES
    target_slot_index: Optional[int] = None             # required for replace_/remove_/add_slot
    new_constraints: dict = field(default_factory=dict) # any of build_day_itinerary's filter fields
    preserve_doc_ids: list[str] = field(default_factory=list)
    reject_doc_ids: list[str] = field(default_factory=list)
    change_request_text: Optional[str] = None           # verbatim user utterance, for logging


@dataclass
class SlotReplacement:
    slot_index: int
    old_doc_id: Optional[str]
    old_title: Optional[str]
    new_doc_id: Optional[str]
    new_title: Optional[str]
    reason: str


@dataclass
class Diff:
    summary: str
    slots_replaced: list[SlotReplacement] = field(default_factory=list)
    slots_added: list[dict] = field(default_factory=list)
    slots_removed: list[dict] = field(default_factory=list)
    parameters_changed: dict = field(default_factory=dict)
    travel_gaps_recomputed: list[dict] = field(default_factory=list)


@dataclass
class RefineOutput:
    ok: bool
    updated_plan: Optional[DayPlan]
    diff: Optional[Diff]
    feasibility: Optional[Any]                          # mirrors build_day_itinerary's Feasibility
    unresolved_constraints: list[str]
    regeneration_mode_used: str                         # surgical | partial_rebuild | full_rebuild
    latency_ms: int
    error_code: Optional[str] = None
    message: Optional[str] = None


# =====================================================================
# Public entry point
# =====================================================================


def refine_itinerary(
    inp: RefineInput,
    client: Optional[SanityClient] = None,
) -> RefineOutput:
    started = time.monotonic()
    client = client or SanityClient()

    if inp.change_type not in CHANGE_TYPES:
        return _error(
            inp, started,
            "INVALID_CHANGE_TYPE",
            f"change_type {inp.change_type!r} not in {sorted(CHANGE_TYPES)}",
        )

    if inp.change_type in {"replace_slot", "remove_slot", "add_slot"}:
        return _surgical(inp, client, started)

    if inp.change_type == "broad_adjustment":
        return _full_rebuild(inp, client, started)

    # Otherwise: partial rebuild
    return _partial_rebuild(inp, client, started)


# =====================================================================
# Surgical: replace_slot / remove_slot / add_slot
# =====================================================================


def _surgical(
    inp: RefineInput, client: SanityClient, started: float
) -> RefineOutput:
    plan = inp.existing_plan
    slots = list(plan.slots)
    diff = Diff(summary="")
    unresolved: list[str] = []

    if inp.change_type == "remove_slot":
        if inp.target_slot_index is None or inp.target_slot_index >= len(slots):
            return _error(inp, started, "INVALID_TARGET",
                          f"target_slot_index {inp.target_slot_index!r} out of range")
        removed = slots.pop(inp.target_slot_index)
        diff.slots_removed.append({"slot_index": removed.slot_index,
                                   "title": removed.place.title if removed.place else None,
                                   "type": removed.slot_type})
        # Recompute adjacent travel_gaps + reflow times
        slots = _drop_orphan_travel_gaps(slots)
        slots = _reflow_times(slots, plan.start_time)
        diff.summary = (f"Removed slot {removed.slot_index} "
                        f"({removed.place.title if removed.place else removed.slot_type})")

    elif inp.change_type == "replace_slot":
        if inp.target_slot_index is None or inp.target_slot_index >= len(slots):
            return _error(inp, started, "INVALID_TARGET",
                          f"target_slot_index {inp.target_slot_index!r} out of range")
        target = slots[inp.target_slot_index]
        if target.slot_type != "place" or not target.place:
            return _error(inp, started, "TARGET_NOT_A_PLACE",
                          f"slot {inp.target_slot_index} is {target.slot_type!r}, not a place")

        # Build a new candidate constrained to themes/intensity from new_constraints
        # Anchor the search at the previous slot's coords (or plan base)
        anchor_coords = (
            slots[inp.target_slot_index - 1].place.coords
            if inp.target_slot_index > 0 and slots[inp.target_slot_index - 1].place
            else plan.base_coords
        ) or plan.base_coords

        sp_in = SearchPlacesInput(
            region=plan.region,
            themes=inp.new_constraints.get("themes", []),
            place_subtypes=inp.new_constraints.get("place_subtypes", []),
            physical_intensity_max=inp.new_constraints.get("physical_intensity_max"),
            duration_bands=inp.new_constraints.get("duration_bands", []),
            near=NearFilter(lat=anchor_coords["lat"], lng=anchor_coords["lng"],
                            radius_km=inp.new_constraints.get("candidate_radius_km", 40.0)),
            limit=15,
        )
        sp_out = search_places(sp_in, client=client)
        excluded = set(inp.reject_doc_ids)
        excluded.update(s.place.sanity_doc_id for s in slots
                        if s.slot_type == "place" and s.place)
        # Don't propose the same doc again
        candidates = [c for c in sp_out.results if c.sanity_doc_id not in excluded]
        if not candidates:
            return _error(inp, started, "NO_REPLACEMENT_FOUND",
                          "search_places returned no eligible alternatives")

        replacement: SearchPlaceResult = candidates[0]
        old = target.place
        new_visit_min = DURATION_MINUTES_BY_BAND.get(replacement.duration_band, target.duration_minutes)
        new_slot = _make_place_slot(
            slot_index=target.slot_index,
            start_min=_hhmm_to_min(target.start_time),
            duration_min=new_visit_min,
            cand=replacement,
        )
        slots[inp.target_slot_index] = new_slot
        diff.slots_replaced.append(SlotReplacement(
            slot_index=target.slot_index,
            old_doc_id=old.sanity_doc_id, old_title=old.title,
            new_doc_id=replacement.sanity_doc_id, new_title=replacement.title,
            reason=f"matched theme/intensity constraints; {replacement.match_reasons[:2]}",
        ))
        # Recompute neighbouring travel_gaps + reflow
        slots = _recompute_travel_gaps_around(slots, inp.target_slot_index, plan.base_coords)
        slots = _reflow_times(slots, plan.start_time)
        diff.summary = (f"Replaced slot {target.slot_index}: "
                        f"{old.title!r} → {replacement.title!r}")

    elif inp.change_type == "add_slot":
        # Insert a place at target_slot_index. If target_slot_index >= len, append.
        idx = inp.target_slot_index if inp.target_slot_index is not None else len(slots)
        anchor_coords = (
            slots[idx - 1].place.coords if idx > 0 and idx - 1 < len(slots)
            and slots[idx - 1].slot_type == "place" and slots[idx - 1].place
            else plan.base_coords
        ) or plan.base_coords

        sp_in = SearchPlacesInput(
            region=plan.region,
            themes=inp.new_constraints.get("themes", []),
            place_subtypes=inp.new_constraints.get("place_subtypes", []),
            physical_intensity_max=inp.new_constraints.get("physical_intensity_max"),
            duration_bands=inp.new_constraints.get("duration_bands", []),
            near=NearFilter(lat=anchor_coords["lat"], lng=anchor_coords["lng"],
                            radius_km=inp.new_constraints.get("candidate_radius_km", 40.0)),
            limit=15,
        )
        sp_out = search_places(sp_in, client=client)
        excluded = set(inp.reject_doc_ids)
        excluded.update(s.place.sanity_doc_id for s in slots
                        if s.slot_type == "place" and s.place)
        candidates = [c for c in sp_out.results if c.sanity_doc_id not in excluded]
        if not candidates:
            return _error(inp, started, "NO_ADDITION_FOUND",
                          "search_places returned no eligible additions")

        addition = candidates[0]
        visit_min = DURATION_MINUTES_BY_BAND.get(addition.duration_band, 75)
        # Insert at the requested position
        new_slot = _make_place_slot(slot_index=0, start_min=0,
                                    duration_min=visit_min, cand=addition)
        slots.insert(idx, new_slot)
        diff.slots_added.append({"slot_index": idx, "title": addition.title,
                                 "doc_id": addition.sanity_doc_id})
        slots = _recompute_travel_gaps_around(slots, idx, plan.base_coords)
        slots = _reflow_times(slots, plan.start_time)
        diff.summary = f"Added {addition.title!r} at position {idx}"

    # Reindex
    for i, s in enumerate(slots):
        s.slot_index = i

    new_plan = DayPlan(
        date=plan.date, base_location=plan.base_location, base_coords=plan.base_coords,
        region=plan.region, start_time=plan.start_time, end_time=plan.end_time,
        pace=plan.pace, slots=slots,
    )
    feas = _compute_feasibility(slots)

    return RefineOutput(
        ok=True,
        updated_plan=new_plan,
        diff=diff,
        feasibility=feas,
        unresolved_constraints=unresolved,
        regeneration_mode_used="surgical",
        latency_ms=int((time.monotonic() - started) * 1000),
    )


# =====================================================================
# Partial rebuild: change_pace / change_timing / change_themes / change_intensity / change_budget
# =====================================================================


def _partial_rebuild(
    inp: RefineInput, client: SanityClient, started: float
) -> RefineOutput:
    plan = inp.existing_plan
    new = inp.new_constraints

    # Determine which preserve_doc_ids survive
    preserve = list(inp.preserve_doc_ids)
    if not preserve:
        # If caller didn't specify, preserve nothing — full rerun under new params
        pass

    inputs = BuildDayInput(
        base_location=plan.base_location,
        region=plan.region,
        pace=new.get("pace", plan.pace),
        date=plan.date,
        start_time=new.get("start_time", plan.start_time),
        end_time=new.get("end_time", plan.end_time),
        themes=new.get("themes", []),
        place_subtypes=new.get("place_subtypes", []),
        physical_intensity_max=new.get("physical_intensity_max"),
        duration_bands=new.get("duration_bands", []),
        budget_band=new.get("budget_band"),
        max_drive_minutes_between_stops=new.get(
            "max_drive_minutes_between_stops", 30,
        ),
        candidate_radius_km=new.get("candidate_radius_km", 50.0),
        include_doc_ids=preserve,
        exclude_doc_ids=list(inp.reject_doc_ids),
        constraints=[inp.change_request_text] if inp.change_request_text else [],
    )
    rebuild_out = build_day_itinerary(inputs, client=client)
    if not rebuild_out.ok:
        return _error(inp, started, rebuild_out.error_code or "REBUILD_FAILED",
                      rebuild_out.message or "build_day_itinerary failed")

    new_plan = rebuild_out.day_plan
    diff = _compute_diff(plan, new_plan, change_type=inp.change_type, new_constraints=new)
    diff.summary = (
        f"{_describe_change(inp.change_type, new)}; "
        f"{len(diff.slots_replaced)} replaced, {len(diff.slots_added)} added, "
        f"{len(diff.slots_removed)} removed"
    )

    return RefineOutput(
        ok=True,
        updated_plan=new_plan,
        diff=diff,
        feasibility=rebuild_out.feasibility,
        unresolved_constraints=_check_unresolved(inp, rebuild_out),
        regeneration_mode_used="partial_rebuild",
        latency_ms=int((time.monotonic() - started) * 1000),
    )


# =====================================================================
# Full rebuild: broad_adjustment
# =====================================================================


def _full_rebuild(
    inp: RefineInput, client: SanityClient, started: float
) -> RefineOutput:
    plan = inp.existing_plan
    new = inp.new_constraints

    inputs = BuildDayInput(
        base_location=new.get("base_location", plan.base_location),
        region=new.get("region", plan.region),
        pace=new.get("pace", plan.pace),
        date=new.get("date", plan.date),
        start_time=new.get("start_time", plan.start_time),
        end_time=new.get("end_time", plan.end_time),
        themes=new.get("themes", []),
        place_subtypes=new.get("place_subtypes", []),
        physical_intensity_max=new.get("physical_intensity_max"),
        duration_bands=new.get("duration_bands", []),
        budget_band=new.get("budget_band"),
        max_drive_minutes_between_stops=new.get("max_drive_minutes_between_stops", 30),
        candidate_radius_km=new.get("candidate_radius_km", 50.0),
        include_doc_ids=list(inp.preserve_doc_ids),
        exclude_doc_ids=list(inp.reject_doc_ids),
        constraints=[inp.change_request_text] if inp.change_request_text else [],
    )
    rebuild_out = build_day_itinerary(inputs, client=client)
    if not rebuild_out.ok:
        return _error(inp, started, rebuild_out.error_code or "REBUILD_FAILED",
                      rebuild_out.message or "build_day_itinerary failed")

    new_plan = rebuild_out.day_plan
    diff = _compute_diff(plan, new_plan, change_type=inp.change_type, new_constraints=new)
    diff.summary = ("Full rebuild with merged constraints; "
                    f"{len(diff.slots_replaced)} replaced, "
                    f"{len(diff.slots_added)} added, "
                    f"{len(diff.slots_removed)} removed")

    return RefineOutput(
        ok=True,
        updated_plan=new_plan,
        diff=diff,
        feasibility=rebuild_out.feasibility,
        unresolved_constraints=_check_unresolved(inp, rebuild_out),
        regeneration_mode_used="full_rebuild",
        latency_ms=int((time.monotonic() - started) * 1000),
    )


# =====================================================================
# Helpers
# =====================================================================


def _drop_orphan_travel_gaps(slots: list[Slot]) -> list[Slot]:
    """Remove travel_gaps that no longer connect two place slots."""
    out: list[Slot] = []
    for i, s in enumerate(slots):
        if s.slot_type == "travel_gap":
            prev = out[-1] if out else None
            nxt = slots[i + 1] if i + 1 < len(slots) else None
            if prev and prev.slot_type == "place" and nxt and nxt.slot_type == "place":
                out.append(s)
            # else drop
        else:
            out.append(s)
    return out


def _recompute_travel_gaps_around(
    slots: list[Slot], around_index: int, base_coords: dict,
) -> list[Slot]:
    """Recompute travel_gaps adjacent to `around_index`. Inserts new gaps if
    distance ≥ 5 min and adjacent slots are places.
    """
    # Find the place slot at around_index (after possibly being inserted)
    if around_index >= len(slots):
        return slots
    target = slots[around_index]
    if target.slot_type != "place":
        return slots

    # Drop any existing travel_gap immediately before/after
    out: list[Slot] = []
    skip_indices: set[int] = set()
    if around_index > 0 and slots[around_index - 1].slot_type == "travel_gap":
        skip_indices.add(around_index - 1)
    if around_index + 1 < len(slots) and slots[around_index + 1].slot_type == "travel_gap":
        skip_indices.add(around_index + 1)
    for i, s in enumerate(slots):
        if i not in skip_indices:
            out.append(s)

    # Now find target's new position in `out` and insert recomputed travel_gaps
    new_target_idx = next((i for i, s in enumerate(out) if s is target), None)
    if new_target_idx is None:
        return out

    # Insert before
    if new_target_idx > 0:
        prev_place = _previous_place_slot(out, new_target_idx)
        if prev_place and prev_place.place and target.place and prev_place.place.coords and target.place.coords:
            drive = _drive_minutes(prev_place.place.coords, target.place.coords)
            if drive >= 5:
                gap = _make_travel_gap_slot(
                    slot_index=0, start_min=0, duration_min=drive,
                    from_settlement=prev_place.place.location_settlement,
                    to_settlement=target.place.location_settlement,
                    from_coords=prev_place.place.coords, to_coords=target.place.coords,
                )
                out.insert(new_target_idx, gap)
                new_target_idx += 1

    # Insert after
    if new_target_idx + 1 < len(out):
        next_place = _next_place_slot(out, new_target_idx)
        if next_place and next_place.place and target.place and next_place.place.coords and target.place.coords:
            drive = _drive_minutes(target.place.coords, next_place.place.coords)
            if drive >= 5:
                gap = _make_travel_gap_slot(
                    slot_index=0, start_min=0, duration_min=drive,
                    from_settlement=target.place.location_settlement,
                    to_settlement=next_place.place.location_settlement,
                    from_coords=target.place.coords, to_coords=next_place.place.coords,
                )
                out.insert(new_target_idx + 1, gap)
    return out


def _previous_place_slot(slots: list[Slot], from_index: int) -> Optional[Slot]:
    for i in range(from_index - 1, -1, -1):
        if slots[i].slot_type == "place":
            return slots[i]
    return None


def _next_place_slot(slots: list[Slot], from_index: int) -> Optional[Slot]:
    for i in range(from_index + 1, len(slots)):
        if slots[i].slot_type == "place":
            return slots[i]
    return None


def _reflow_times(slots: list[Slot], start_time: str) -> list[Slot]:
    """Reset all slot start/end times in sequence starting from `start_time`."""
    cur = _hhmm_to_min(start_time)
    out: list[Slot] = []
    for s in slots:
        s.start_time = _min_to_hhmm(cur)
        s.end_time = _min_to_hhmm(cur + s.duration_minutes)
        cur += s.duration_minutes
        out.append(s)
    return out


def _compute_feasibility(slots: list[Slot]) -> Any:
    from tools.build_day_itinerary import Feasibility
    active = sum(s.duration_minutes for s in slots if s.slot_type == "place")
    idle = sum(s.duration_minutes for s in slots
               if s.slot_type in ("travel_gap", "meal_gap", "buffer"))
    longest = max((s.duration_minutes for s in slots if s.slot_type == "travel_gap"),
                  default=0)
    return Feasibility(total_active_minutes=active, total_idle_minutes=idle,
                       longest_drive_minutes=int(longest), warnings=[])


def _compute_diff(old: DayPlan, new: DayPlan,
                  change_type: str, new_constraints: dict) -> Diff:
    diff = Diff(summary="")
    old_doc_ids = [s.place.sanity_doc_id for s in old.slots
                   if s.slot_type == "place" and s.place]
    new_doc_ids = [s.place.sanity_doc_id for s in new.slots
                   if s.slot_type == "place" and s.place]
    old_set, new_set = set(old_doc_ids), set(new_doc_ids)
    removed_ids = old_set - new_set
    added_ids = new_set - old_set

    # If we both removed and added at the same position, treat as replacement.
    # Simple approximation: pair removed and added by order.
    removed = [{"doc_id": d, "title": _title_for(old, d)} for d in removed_ids]
    added = [{"doc_id": d, "title": _title_for(new, d)} for d in added_ids]
    diff.slots_removed = removed
    diff.slots_added = added

    # Parameter changes
    for k in ("pace", "start_time", "end_time"):
        ov, nv = getattr(old, k, None), getattr(new, k, None)
        if ov != nv:
            diff.parameters_changed[k] = {"old": ov, "new": nv}
    for k, v in new_constraints.items():
        if k in ("themes", "place_subtypes", "physical_intensity_max",
                 "duration_bands", "budget_band", "max_drive_minutes_between_stops"):
            diff.parameters_changed[k] = {"new": v}

    return diff


def _title_for(plan: DayPlan, doc_id: str) -> Optional[str]:
    for s in plan.slots:
        if s.slot_type == "place" and s.place and s.place.sanity_doc_id == doc_id:
            return s.place.title
    return None


def _describe_change(change_type: str, new_constraints: dict) -> str:
    if change_type == "change_pace":
        return f"Pace → {new_constraints.get('pace', '?')}"
    if change_type == "change_timing":
        return (f"Window → {new_constraints.get('start_time', '?')} – "
                f"{new_constraints.get('end_time', '?')}")
    if change_type == "change_themes":
        return f"Themes → {new_constraints.get('themes', [])}"
    if change_type == "change_intensity":
        return f"Intensity max → {new_constraints.get('physical_intensity_max', '?')}"
    if change_type == "change_budget":
        return f"Budget → {new_constraints.get('budget_band', '?')}"
    return change_type


def _check_unresolved(inp: RefineInput, rebuild_out: BuildDayOutput) -> list[str]:
    """Surface things the rebuild couldn't satisfy."""
    out: list[str] = []
    if not rebuild_out.day_plan or not any(
        s.slot_type == "place" for s in rebuild_out.day_plan.slots
    ):
        out.append("Rebuild produced no place slots; constraints may be too tight.")
    if rebuild_out.feasibility and rebuild_out.feasibility.warnings:
        out.extend(rebuild_out.feasibility.warnings)
    return out


def _error(inp: RefineInput, started: float, code: str, msg: str) -> RefineOutput:
    return RefineOutput(
        ok=False, updated_plan=None, diff=None, feasibility=None,
        unresolved_constraints=[], regeneration_mode_used="none",
        latency_ms=int((time.monotonic() - started) * 1000),
        error_code=code, message=msg,
    )


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

    # Build an initial Hibiscus Coast day plan to refine
    print("Building initial day plan: Hibiscus Coast / coastal+family / full pace")
    initial = build_day_itinerary(BuildDayInput(
        base_location="Hibiscus Coast", region="Auckland",
        pace="full", themes=["coastal", "family"],
        place_subtypes=["beach", "walk"], candidate_radius_km=30,
    ), client=client)
    if not initial.ok:
        print(f"Failed: {initial.error_code}: {initial.message}")
        sys.exit(1)
    plan = initial.day_plan
    print(f"  Initial pool={initial.candidate_pool_size}, "
          f"{sum(1 for s in plan.slots if s.slot_type == 'place')} place slots")
    for s in plan.slots:
        if s.slot_type == "place" and s.place:
            print(f"    [{s.start_time}] {s.place.title}")
        elif s.slot_type == "meal_gap":
            print(f"    [{s.start_time}] lunch")

    # ----- TEST 1: change pace from full → relaxed -----
    print("\n--- REFINE 1: change_pace → 'relaxed' ---")
    refined = refine_itinerary(RefineInput(
        existing_plan=plan,
        change_type="change_pace",
        new_constraints={"pace": "relaxed"},
        change_request_text="Make this more relaxed, fewer stops",
    ), client=client)
    print(f"  ok={refined.ok}, mode={refined.regeneration_mode_used}, latency={refined.latency_ms}ms")
    if refined.diff:
        print(f"  Diff: {refined.diff.summary}")
        for r in refined.diff.slots_removed:
            print(f"    - removed: {r['title']}")
    if refined.updated_plan:
        for s in refined.updated_plan.slots:
            if s.slot_type == "place" and s.place:
                print(f"    [{s.start_time}] {s.place.title}")
            elif s.slot_type == "meal_gap":
                print(f"    [{s.start_time}] lunch")

    # ----- TEST 2: replace_slot — swap slot 1 for something different -----
    target_idx = next(
        (i for i, s in enumerate(plan.slots)
         if s.slot_type == "place" and s.place), None
    )
    if target_idx is not None:
        print(f"\n--- REFINE 2: replace_slot (slot {target_idx}: "
              f"{plan.slots[target_idx].place.title!r}) → forest theme ---")
        refined2 = refine_itinerary(RefineInput(
            existing_plan=plan,
            change_type="replace_slot",
            target_slot_index=target_idx,
            new_constraints={"themes": ["forest", "nature"]},
            change_request_text=f"Swap {plan.slots[target_idx].place.title} for somewhere wooded",
        ), client=client)
        print(f"  ok={refined2.ok}, mode={refined2.regeneration_mode_used}, "
              f"latency={refined2.latency_ms}ms")
        if refined2.diff:
            print(f"  Diff: {refined2.diff.summary}")
            for r in refined2.diff.slots_replaced:
                print(f"    - replaced slot {r.slot_index}: {r.old_title!r} → {r.new_title!r}")
        if refined2.updated_plan:
            for s in refined2.updated_plan.slots:
                if s.slot_type == "place" and s.place:
                    print(f"    [{s.start_time}] {s.place.title}")
                elif s.slot_type == "meal_gap":
                    print(f"    [{s.start_time}] lunch")

    # ----- TEST 3: change_themes — broaden to include heritage -----
    print("\n--- REFINE 3: change_themes → ['coastal', 'heritage'] ---")
    refined3 = refine_itinerary(RefineInput(
        existing_plan=plan,
        change_type="change_themes",
        new_constraints={"themes": ["coastal", "heritage"]},
        change_request_text="Add some history to the day",
    ), client=client)
    print(f"  ok={refined3.ok}, mode={refined3.regeneration_mode_used}, latency={refined3.latency_ms}ms")
    if refined3.diff:
        print(f"  Diff: {refined3.diff.summary}")
    if refined3.updated_plan:
        for s in refined3.updated_plan.slots:
            if s.slot_type == "place" and s.place:
                print(f"    [{s.start_time}] {s.place.title}")
            elif s.slot_type == "meal_gap":
                print(f"    [{s.start_time}] lunch")
