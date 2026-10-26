// Where the longitude and latitude ticks fall on the map edges, like a printed sheet.
// They are only drawn while the map is north-up and flat: tilted or rotated, a screen edge no
// longer follows a meridian or a parallel, and ticks there would be wrong.

import type { Map as MapLibre } from "maplibre-gl";

export interface Ticks {
  lng: { value: number; x: number }[];
  lat: { value: number; y: number }[];
  step: number;
}

const STEPS = [0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5];

/** The tick step giving about four to eight ticks over `span` degrees. */
export function tickStep(span: number): number {
  return STEPS.find((s) => span / s <= 8) ?? STEPS[STEPS.length - 1]!;
}

export function ticksFor(map: MapLibre): Ticks | null {
  if (Math.abs(map.getBearing()) > 0.5 || map.getPitch() > 0.5) return null;
  const b = map.getBounds();
  const { width, height } = map.getCanvas().getBoundingClientRect();
  const step = tickStep(Math.max(b.getEast() - b.getWest(), b.getNorth() - b.getSouth()));
  const centre = map.getCenter();
  // Whole multiples of the step, so labels do not drift with floating-point sums.
  const multiples = (from: number, to: number) => {
    const out = [];
    for (let i = Math.ceil(from / step); i * step <= to; i++) out.push(i * step);
    return out;
  };
  const lng = multiples(b.getWest(), b.getEast())
    .map((value) => ({ value, x: map.project([value, centre.lat]).x }))
    .filter((t) => t.x > 40 && t.x < width - 40);
  const lat = multiples(b.getSouth(), b.getNorth())
    .map((value) => ({ value, y: map.project([centre.lng, value]).y }))
    .filter((t) => t.y > 30 && t.y < height - 30);
  return { lng, lat, step };
}

/** Degrees with the decimals the step needs: 0.05 → 77.65°E, 0.5 → 77.5°E. */
export function tickLabel(v: number, step: number, pos: string, neg: string): string {
  const digits = Math.max(0, Math.ceil(-Math.log10(step) - 1e-9));
  return `${Math.abs(v).toFixed(digits)}°${v >= 0 ? pos : neg}`;
}
