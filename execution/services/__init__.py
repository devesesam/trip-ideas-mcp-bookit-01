"""External-API service wrappers (Google Maps; future home for Bookit, etc.).

Each module exposes a small, defensive interface that:
  - Returns None / empty results on misconfiguration or API failure (no raises)
  - Caches reads where it makes sense (e.g. geocoding)
  - Doesn't block tool execution when the upstream is down
"""
