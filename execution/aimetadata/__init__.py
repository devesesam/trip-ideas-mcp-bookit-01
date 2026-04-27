"""aiMetadata parsing — the central data layer for v1.

The Tripideas Sanity `page.aiMetadata` field is a JSON-encoded string with
unstable value types across docs (some fields are sometimes strings,
sometimes arrays, sometimes nulls). This package exposes a parser that
reads the raw string and produces a stable in-memory view tools can rely on.

Public API:
    parse(raw_aimetadata: str) -> ParsedAiMetadata
    ParsedAiMetadata           # dataclass with normalized fields
    NearbyPlace, TrackTrail, LocationHint
"""

from .parser import (
    LocationHint,
    NearbyPlace,
    ParsedAiMetadata,
    TrackTrail,
    parse,
)

__all__ = [
    "parse",
    "ParsedAiMetadata",
    "NearbyPlace",
    "TrackTrail",
    "LocationHint",
]
