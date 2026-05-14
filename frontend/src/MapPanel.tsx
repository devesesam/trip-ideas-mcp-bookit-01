/**
 * MapPanel — renders the latest itinerary's route_geojson alongside the chat.
 *
 * Reads `latestRoute`, `latestRouteId`, and `isBuildingItinerary` from
 * `useChatContext()` (so a single useChat instance is shared with ChatPanel).
 *
 * Tile source: CartoDB Voyager — neutral palette, no API key, free per OSM
 * attribution. If we ever want fancier base layers (terrain, satellite), swap
 * the tile URL or upgrade to MapLibre/Mapbox.
 *
 * GeoJSON coordinate convention: backend emits [lng, lat] (GeoJSON standard).
 * react-leaflet's <GeoJSON> consumes that directly. Do NOT swap to
 * <Polyline positions={...}> — Leaflet's `positions` expects [lat, lng] and
 * will transpose the map.
 *
 * Three render states:
 *   - empty:     no itinerary yet → centred NZ map + caption
 *   - building:  isBuildingItinerary true → empty map + loading overlay
 *   - rendered: latestRoute set → full geojson, auto-fit bounds on new routes
 */

import { useEffect, useMemo } from "react";
import {
  GeoJSON,
  MapContainer,
  TileLayer,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import type {
  Feature,
  FeatureCollection,
  Geometry,
  Point,
} from "geojson";
import { Map as MapIcon, Loader2 } from "lucide-react";
import { useChatContext } from "./ChatContext";
import "leaflet/dist/leaflet.css";


// =====================================================================
// Constants — NZ default view + brand colours
// =====================================================================

const NZ_CENTRE: [number, number] = [-41.0, 173.5];
const NZ_DEFAULT_ZOOM = 5;

// CartoDB Voyager — free OSM tiles, neutral palette
const TILE_URL =
  "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png";
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';

// Brand colours — read from the same CSS custom properties as the chat UI
function brandAccent(): string {
  if (typeof window === "undefined") return "rgb(175, 222, 255)";
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue("--ti-accent")
    .trim();
  return raw ? `rgb(${raw})` : "rgb(175, 222, 255)";
}

function brandPrimary(): string {
  if (typeof window === "undefined") return "rgb(0, 0, 0)";
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue("--ti-primary")
    .trim();
  return raw ? `rgb(${raw})` : "rgb(0, 0, 0)";
}


// =====================================================================
// Styling helpers — keyed off feature.properties.role
// =====================================================================

interface GeoProps {
  role?: string;
  title?: string;
  label?: string;
  settlement?: string;
  start_time?: string;
  end_time?: string;
  themes?: string[];
  day_index?: number;
  from_settlement?: string;
  to_settlement?: string;
  estimated_km?: number;
  estimated_drive_minutes?: number;
}

function lineStyle(feature?: Feature<Geometry, GeoProps>) {
  const role = feature?.properties?.role;
  const accent = brandAccent();
  if (role === "inter_day_drive") {
    return {
      color: accent,
      weight: 3,
      opacity: 0.9,
      dashArray: "6 6",
    };
  }
  // drive_route or any other LineString
  return {
    color: accent,
    weight: 4,
    opacity: 1,
  };
}

function pointToLayer(feature: Feature<Point, GeoProps>, latlng: L.LatLng) {
  const role = feature.properties?.role;
  if (role === "base") {
    return L.circleMarker(latlng, {
      radius: 7,
      color: brandPrimary(),
      weight: 2,
      fillColor: "white",
      fillOpacity: 1,
    });
  }
  // place
  return L.circleMarker(latlng, {
    radius: 6,
    color: brandPrimary(),
    weight: 1.5,
    fillColor: brandAccent(),
    fillOpacity: 0.95,
  });
}

function onEachFeature(feature: Feature<Geometry, GeoProps>, layer: L.Layer) {
  const p = feature.properties || {};
  if (feature.geometry.type === "Point") {
    if (p.role === "place" && p.title) {
      const time = p.start_time ? `<div style="opacity:.7;font-size:11px">${p.start_time}</div>` : "";
      const settlement = p.settlement ? `<div style="opacity:.7;font-size:11px">${p.settlement}</div>` : "";
      layer.bindTooltip(
        `<strong>${p.title}</strong>${time}${settlement}`,
        { direction: "top", offset: [0, -6], opacity: 1 },
      );
    } else if (p.role === "base" && p.label) {
      layer.bindTooltip(p.label, { direction: "top", offset: [0, -6] });
    }
  } else if (feature.geometry.type === "LineString" && p.role === "inter_day_drive") {
    if (p.from_settlement && p.to_settlement) {
      const km = p.estimated_km != null ? `${p.estimated_km.toFixed(0)} km` : "";
      const mins = p.estimated_drive_minutes != null ? `~${p.estimated_drive_minutes} min` : "";
      const sub = [km, mins].filter(Boolean).join(" · ");
      layer.bindTooltip(
        `${p.from_settlement} → ${p.to_settlement}${sub ? `<br/><span style="opacity:.7;font-size:11px">${sub}</span>` : ""}`,
        { sticky: true },
      );
    }
  }
}


// =====================================================================
// FitBoundsOnRoute — re-fits the map whenever a new geojson arrives
// =====================================================================

function FitBoundsOnRoute({
  route,
  routeId,
}: {
  route: FeatureCollection<Geometry, GeoProps> | null;
  routeId: string | null;
}) {
  const map = useMap();

  useEffect(() => {
    if (!route || !routeId) return;
    const features = route.features ?? [];
    if (!features.length) return;
    const layer = L.geoJSON(route as unknown as GeoJSON.GeoJsonObject);
    const bounds = layer.getBounds();
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 12 });
    }
  }, [map, route, routeId]);

  return null;
}


// =====================================================================
// MapPanel
// =====================================================================

export interface MapPanelProps {
  className?: string;
}

export function MapPanel({ className = "" }: MapPanelProps) {
  const { latestRoute, latestRouteId, isBuildingItinerary } = useChatContext();

  const route = latestRoute as FeatureCollection<Geometry, GeoProps> | null;
  const hasRoute = !!route && Array.isArray(route.features) && route.features.length > 0;

  // Memoize the keyed GeoJSON layer so a new routeId remounts cleanly
  // (rather than diff-patching old features under new ones).
  const geojsonLayer = useMemo(() => {
    if (!hasRoute || !latestRouteId) return null;
    return (
      <GeoJSON
        key={latestRouteId}
        data={route as FeatureCollection}
        style={lineStyle as L.StyleFunction}
        pointToLayer={pointToLayer as L.GeoJSONOptions["pointToLayer"]}
        onEachFeature={onEachFeature}
      />
    );
  }, [hasRoute, latestRouteId, route]);

  return (
    <div
      className={`relative flex h-full w-full flex-col overflow-hidden bg-brand-surface-alt ${className}`}
      role="region"
      aria-label="Itinerary map"
    >
      <MapContainer
        center={NZ_CENTRE}
        zoom={NZ_DEFAULT_ZOOM}
        scrollWheelZoom
        className="h-full w-full"
        attributionControl
        zoomControl
      >
        <TileLayer attribution={TILE_ATTRIBUTION} url={TILE_URL} />
        {geojsonLayer}
        <FitBoundsOnRoute route={route} routeId={latestRouteId} />
      </MapContainer>

      {/* Empty state — overlay when no route */}
      {!hasRoute && !isBuildingItinerary && <EmptyOverlay />}

      {/* Loading overlay — when a build_* tool is currently running */}
      {isBuildingItinerary && <BuildingOverlay hasExistingRoute={hasRoute} />}
    </div>
  );
}


function EmptyOverlay() {
  return (
    <div className="pointer-events-none absolute inset-0 z-[400] flex items-center justify-center">
      <div className="pointer-events-auto mx-6 max-w-sm rounded-bubble border border-brand-border bg-brand-surface/90 px-5 py-4 text-center shadow-sm backdrop-blur">
        <MapIcon
          className="mx-auto mb-2 h-6 w-6 text-brand-text-muted"
          aria-hidden="true"
        />
        <p className="text-sm font-medium text-brand-text">
          Your itinerary will appear here
        </p>
        <p className="mt-1 text-xs text-brand-text-muted">
          Ask the chat to plan a day or a trip — places, drive routes, and
          inter-day transitions will draw on this map.
        </p>
      </div>
    </div>
  );
}


function BuildingOverlay({ hasExistingRoute }: { hasExistingRoute: boolean }) {
  return (
    <div className="pointer-events-none absolute inset-0 z-[400] flex items-center justify-center">
      <div className="pointer-events-auto flex items-center gap-2 rounded-bubble border border-brand-border bg-brand-surface/90 px-4 py-2 shadow-sm backdrop-blur">
        <Loader2 className="h-4 w-4 animate-spin text-brand-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-brand-text">
          {hasExistingRoute ? "Updating the route…" : "Composing the route…"}
        </span>
      </div>
    </div>
  );
}
