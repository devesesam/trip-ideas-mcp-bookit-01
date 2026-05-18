/**
 * Build a Google Maps Directions URL from a Tripideas route_geojson.
 *
 * Uses Google's URL API:
 *   https://www.google.com/maps/dir/?api=1
 *     &origin=<lat,lng>
 *     &destination=<lat,lng>
 *     &waypoints=<lat,lng>|<lat,lng>|...
 *     &travelmode=driving
 *
 * Two route shapes:
 *   - Day plan (no feature has `properties.day_index`):
 *       round trip — origin = destination = the base point, waypoints = places
 *   - Trip plan (any feature has `properties.day_index`):
 *       linear journey — origin = first point, destination = last point,
 *       waypoints = everything between
 *
 * Coordinate flip: GeoJSON uses [lng, lat]; Google's URL uses lat,lng.
 *
 * Cap: Google's URL API silently drops waypoints past the 9th. If we have
 * more, sample evenly to keep the shape of the route sensible.
 */

import type { Feature, FeatureCollection, Geometry, Point } from "geojson";

interface GeoProps {
  role?: string;
  day_index?: number;
}

const MAX_WAYPOINTS = 9;

export function buildGoogleMapsRouteUrl(
  route: FeatureCollection<Geometry, GeoProps> | null | undefined,
): string | null {
  if (!route?.features?.length) return null;

  // Collect Point features only (skip LineStrings — they're for rendering)
  const points = route.features.filter(
    (f): f is Feature<Point, GeoProps> => f.geometry?.type === "Point",
  );
  if (points.length < 2) return null;

  const isTrip = points.some((p) => typeof p.properties?.day_index === "number");

  let origin: Feature<Point, GeoProps>;
  let destination: Feature<Point, GeoProps>;
  let waypoints: Feature<Point, GeoProps>[];

  if (isTrip) {
    // Order by day_index then by appearance in the feature array
    const ordered = [...points]
      .map((p, i) => ({ p, i }))
      .sort((a, b) => {
        const da = a.p.properties?.day_index ?? 0;
        const db = b.p.properties?.day_index ?? 0;
        if (da !== db) return da - db;
        return a.i - b.i;
      })
      .map(({ p }) => p);

    origin = ordered[0];
    destination = ordered[ordered.length - 1];
    waypoints = ordered.slice(1, -1);
  } else {
    // Day plan — base is the round-trip anchor
    const base = points.find((p) => p.properties?.role === "base");
    const places = points.filter((p) => p.properties?.role !== "base");

    if (base && places.length) {
      origin = base;
      destination = base;
      waypoints = places;
    } else {
      // Fallback: no base — treat the whole list as linear
      origin = points[0];
      destination = points[points.length - 1];
      waypoints = points.slice(1, -1);
    }
  }

  // Sample waypoints evenly if we exceed Google's cap
  if (waypoints.length > MAX_WAYPOINTS) {
    const step = (waypoints.length - 1) / (MAX_WAYPOINTS - 1);
    const sampled: Feature<Point, GeoProps>[] = [];
    for (let i = 0; i < MAX_WAYPOINTS; i++) {
      sampled.push(waypoints[Math.round(i * step)]);
    }
    waypoints = sampled;
  }

  const params = new URLSearchParams();
  params.set("api", "1");
  params.set("origin", coordParam(origin));
  params.set("destination", coordParam(destination));
  if (waypoints.length) {
    params.set("waypoints", waypoints.map(coordParam).join("|"));
  }
  params.set("travelmode", "driving");

  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

function coordParam(f: Feature<Point, GeoProps>): string {
  // GeoJSON Point coordinates are [lng, lat]. Google wants "lat,lng".
  const [lng, lat] = f.geometry.coordinates;
  // 5 dp ≈ 1.1 m precision — plenty for navigation, keeps URL short.
  return `${lat.toFixed(5)},${lng.toFixed(5)}`;
}
