// Places for the Easy view: finding a stop by name, the zone under a point, the nearest stop,
// and the minutes bands of a zone's reach. Pure functions, tested without a map.

import { cellToLatLng, latLngToCell } from "h3-js";

import type { LonLat, StopFeature } from "../api/types";
import { viridis } from "../map/colours";

export interface NamedStop {
  name: string;
  position: LonLat;
  metro: boolean;
}

/**
 * One entry per stop name: a name is often several platforms or both sides of a road. A metro
 * station's own entry is preferred, so picking it starts from the station.
 */
export function namedStops(stops: StopFeature[]): NamedStop[] {
  const byName = new Map<string, NamedStop & { station: boolean }>();
  for (const s of stops) {
    const name = s.properties.name?.trim();
    if (!name) continue;
    const key = name.toLowerCase();
    const metro = s.properties.modes.includes("metro");
    const seen = byName.get(key);
    if (seen && (seen.station || !s.properties.station)) {
      seen.metro ||= metro;
      continue;
    }
    byName.set(key, {
      name,
      position: s.geometry.coordinates,
      metro: metro || (seen?.metro ?? false),
      station: s.properties.station,
    });
  }
  return [...byName.values()]
    .map(({ name, position, metro }) => ({ name, position, metro }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** Names containing the text, those starting with it first, metro stations before stops. */
export function searchStops(stops: NamedStop[], text: string, limit = 8): NamedStop[] {
  const q = text.trim().toLowerCase();
  if (q.length < 2) return [];
  const rank = (s: NamedStop) => {
    const name = s.name.toLowerCase();
    return (name.startsWith(q) ? 0 : 2) + (s.metro ? 0 : 1);
  };
  return stops
    .filter((s) => s.name.toLowerCase().includes(q))
    .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name))
    .slice(0, limit);
}

export const zoneAt = ([lng, lat]: LonLat, resolution: number): string =>
  latLngToCell(lat, lng, resolution);

export function zoneCentre(h3: string): LonLat {
  const [lat, lng] = cellToLatLng(h3);
  return [lng, lat];
}

/** Straight-line distance in metres; enough to say how far the nearest stop is. */
export function metres([x1, y1]: LonLat, [x2, y2]: LonLat): number {
  const k = Math.PI / 180;
  const a =
    Math.sin(((y2 - y1) * k) / 2) ** 2 +
    Math.cos(y1 * k) * Math.cos(y2 * k) * Math.sin(((x2 - x1) * k) / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(a));
}

export function nearestStop(
  stops: NamedStop[],
  at: LonLat,
): { stop: NamedStop; metres: number } | null {
  let best: { stop: NamedStop; metres: number } | null = null;
  for (const stop of stops) {
    const d = metres(stop.position, at);
    if (!best || d < best.metres) best = { stop, metres: d };
  }
  return best;
}

/** Upper ends of the bands the reach map is drawn in, minutes. */
export const BANDS = [15, 30, 45] as const;

/** Colours of the bands: viridis, brightest for the nearest band (levels, ADR 0023). */
export const BAND_COLOUR = [viridis(0.95), viridis(0.6), viridis(0.25)];

/** The band of a travel time (0, 1 or 2), or null beyond the last band. */
export function band(minutes: number): number | null {
  const i = BANDS.findIndex((top) => minutes <= top);
  return i < 0 ? null : i;
}

/** Zones within `limit` minutes, from a reach answer's parallel arrays. */
export function within(cells: string[], minutes: number[], limit: number): Set<string> {
  const out = new Set<string>();
  cells.forEach((c, i) => {
    if (minutes[i]! <= limit) out.add(c);
  });
  return out;
}

/** West, south, east, north around zone centres and extra points, for the camera. */
export function boundsOf(
  cells: Iterable<string>,
  extra: LonLat[] = [],
): [number, number, number, number] | null {
  const points = [...[...cells].map(zoneCentre), ...extra];
  if (points.length === 0) return null;
  const lng = points.map((p) => p[0]);
  const lat = points.map((p) => p[1]);
  return [Math.min(...lng), Math.min(...lat), Math.max(...lng), Math.max(...lat)];
}
