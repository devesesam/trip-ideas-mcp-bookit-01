"""Google Maps API wrapper for the chat backend.

Two operations matter for our itinerary tools:

1. `geocode(name)` — resolve a place/town name to (lat, lng). Falls back to None
   if the name is unresolvable or the API key is missing. In-process LRU cache
   so repeated lookups within a session are free.

2. `directions(origin, destinations, optimize=False)` — get drive durations and
   road-following polylines for a sequence of stops. Replaces our haversine ×
   1.4 / 60 km/h fudge factor when the key is configured.

Defensive design: every function returns None on missing key, network failure,
or non-OK Google status. Callers are expected to fall back to haversine or
proceed without the visual route. We never crash itinerary generation because
of a Google Maps issue.

API key resolution order:
  1. GOOGLE_MAPS_API_KEY env var (Modal secret in production, .env locally)
  2. None — caller falls back

References:
- Geocoding API: https://developers.google.com/maps/documentation/geocoding/start
- Directions API: https://developers.google.com/maps/documentation/directions/start
- Polyline encoding: https://developers.google.com/maps/documentation/utilities/polylinealgorithm
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import requests


_GEOCODE_ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
_DIRECTIONS_ENDPOINT = "https://maps.googleapis.com/maps/api/directions/json"
_DIRECTIONS_WAYPOINT_CAP = 25      # Google's hard cap per request
_REQUEST_TIMEOUT_S = 10.0


def _api_key() -> Optional[str]:
    return os.environ.get("GOOGLE_MAPS_API_KEY")


def is_configured() -> bool:
    """True if the API key is present. Tools call this to decide whether to
    use Google Maps or fall back to haversine."""
    return bool(_api_key())


# =====================================================================
# Geocoding
# =====================================================================


@lru_cache(maxsize=512)
def geocode(name: str, country: str = "nz") -> Optional[tuple[float, float]]:
    """Resolve a place name to (lat, lng). Country-restricted to NZ by default
    (matches our use case). Returns None if the API key is missing, the call
    fails, or the place doesn't resolve.

    Cached per process — repeated lookups for the same name are free.
    """
    key = _api_key()
    if not key or not name or not name.strip():
        return None

    try:
        response = requests.get(
            _GEOCODE_ENDPOINT,
            params={
                "address": name,
                "components": f"country:{country}",
                "key": key,
            },
            timeout=_REQUEST_TIMEOUT_S,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None
        loc = data["results"][0].get("geometry", {}).get("location")
        if not loc or "lat" not in loc or "lng" not in loc:
            return None
        return (float(loc["lat"]), float(loc["lng"]))
    except (requests.RequestException, ValueError, KeyError):
        return None


# =====================================================================
# Directions
# =====================================================================


@dataclass
class DirectionsLeg:
    """One leg of a directions response — covers travel from one stop to the next."""
    duration_min: int                  # rounded minutes, factors in road geometry
    distance_km: float
    polyline_points: list[tuple[float, float]] = field(default_factory=list)
    """Decoded polyline as a list of (lat, lng) pairs. Empty if Google's
    overview_polyline was unavailable for this leg."""


@dataclass
class DirectionsResult:
    legs: list[DirectionsLeg]
    total_duration_min: int
    total_distance_km: float
    overview_polyline_points: list[tuple[float, float]] = field(default_factory=list)
    """Decoded overview polyline for the whole route — useful for drawing a
    single LineString without segment-by-segment styling."""
    waypoint_order: list[int] = field(default_factory=list)
    """If `optimize=True` was used, the reordered indices of the input
    intermediate waypoints. e.g. [2, 0, 1] means stop at waypoints[2] first,
    then waypoints[0], then waypoints[1]. Empty list if optimize wasn't used."""


def directions(
    origin: tuple[float, float],
    destination: tuple[float, float],
    waypoints: Optional[list[tuple[float, float]]] = None,
    optimize: bool = False,
) -> Optional[DirectionsResult]:
    """Get driving directions from origin to destination, optionally via
    intermediate waypoints. Returns None if the key is missing, the call fails,
    or Google returns a non-OK status. Caller falls back to haversine.

    Args:
        origin: (lat, lng) of the start point.
        destination: (lat, lng) of the end point. Same as origin for a round
            trip ("return to base").
        waypoints: optional list of (lat, lng) intermediate stops. Capped at
            25 by the Directions API; we error early if exceeded.
        optimize: if True, ask Google to reorder the waypoints for shortest
            total drive (uses the `optimize:true` prefix). Result includes
            `waypoint_order`.
    """
    key = _api_key()
    if not key:
        return None
    waypoints = waypoints or []
    if len(waypoints) > _DIRECTIONS_WAYPOINT_CAP:
        return None  # Caller can split into chunks if needed.

    waypoints_param = None
    if waypoints:
        prefix = "optimize:true|" if optimize else ""
        waypoints_param = prefix + "|".join(f"{lat},{lng}" for lat, lng in waypoints)

    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "key": key,
    }
    if waypoints_param:
        params["waypoints"] = waypoints_param

    try:
        response = requests.get(
            _DIRECTIONS_ENDPOINT,
            params=params,
            timeout=_REQUEST_TIMEOUT_S,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        if data.get("status") != "OK" or not data.get("routes"):
            return None
        route = data["routes"][0]
    except (requests.RequestException, ValueError, KeyError):
        return None

    legs_raw = route.get("legs") or []
    legs: list[DirectionsLeg] = []
    total_duration_s = 0
    total_distance_m = 0.0
    for leg in legs_raw:
        dur_s = (leg.get("duration") or {}).get("value") or 0
        dist_m = (leg.get("distance") or {}).get("value") or 0
        # Per-leg polyline isn't always available; Google encodes the whole route
        # in route.overview_polyline. We leave per-leg polyline empty and rely
        # on the overview for the visual.
        legs.append(DirectionsLeg(
            duration_min=int(round(dur_s / 60)),
            distance_km=round(dist_m / 1000, 2),
        ))
        total_duration_s += dur_s
        total_distance_m += dist_m

    overview_encoded = (route.get("overview_polyline") or {}).get("points")
    overview_points = decode_polyline(overview_encoded) if overview_encoded else []

    return DirectionsResult(
        legs=legs,
        total_duration_min=int(round(total_duration_s / 60)),
        total_distance_km=round(total_distance_m / 1000, 2),
        overview_polyline_points=overview_points,
        waypoint_order=list(route.get("waypoint_order") or []),
    )


# =====================================================================
# Polyline decoder (Google's encoding scheme — small, no external dep)
# =====================================================================


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode a Google encoded polyline string to a list of (lat, lng) tuples.

    Reference implementation:
    https://developers.google.com/maps/documentation/utilities/polylinealgorithm
    """
    if not encoded:
        return []

    points: list[tuple[float, float]] = []
    index = 0
    lat = 0
    lng = 0
    length = len(encoded)

    while index < length:
        # Decode latitude delta
        result = 0
        shift = 0
        while index < length:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        # Decode longitude delta
        result = 0
        shift = 0
        while index < length:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng

        points.append((lat / 1e5, lng / 1e5))

    return points


# =====================================================================
# Convenience: drive minutes between two coords
# =====================================================================


def drive_minutes_between(
    from_coords: tuple[float, float],
    to_coords: tuple[float, float],
) -> Optional[int]:
    """Single-leg shortcut for itinerary tools that just want a drive time.
    Returns None on any failure (caller falls back to haversine)."""
    result = directions(from_coords, to_coords)
    if not result or not result.legs:
        return None
    return result.legs[0].duration_min


__all__ = [
    "is_configured",
    "geocode",
    "directions",
    "drive_minutes_between",
    "decode_polyline",
    "DirectionsResult",
    "DirectionsLeg",
]
