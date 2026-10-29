// Colour scales. Levels use viridis (perceptually uniform, readable with colour-vision
// deficiencies); deltas will use a diverging scale (Phase 7 M7).

import type { Theme } from "../ui/theme";

export type RGB = [number, number, number];

// Viridis sampled at 0, 1/8, ..., 1 (matplotlib's colormap, CC0).
const VIRIDIS: RGB[] = [
  [68, 1, 84],
  [71, 45, 123],
  [59, 82, 139],
  [44, 114, 142],
  [33, 145, 140],
  [40, 174, 128],
  [94, 201, 98],
  [173, 220, 48],
  [253, 231, 37],
];

export function viridis(t: number): RGB {
  const x = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0)) * (VIRIDIS.length - 1);
  const i = Math.min(VIRIDIS.length - 2, Math.floor(x));
  const f = x - i;
  const a = VIRIDIS[i] as RGB;
  const b = VIRIDIS[i + 1] as RGB;
  return [0, 1, 2].map((k) => Math.round(a[k]! + (b[k]! - a[k]!) * f)) as RGB;
}

export function toCss([r, g, b]: RGB): string {
  return `rgb(${r}, ${g}, ${b})`;
}

/**
 * The value at quantile `q` of the positive values: zone values are heavily skewed (a few hubs
 * hold most estimated jobs), so the colour scale tops out here instead of at the maximum.
 */
export function upperBound(values: readonly number[], q = 0.98): number {
  const positive = values.filter((v) => v > 0).sort((a, b) => a - b);
  if (positive.length === 0) return 1;
  return positive[Math.min(positive.length - 1, Math.floor(q * positive.length))]!;
}

/**
 * Colours of the network and of what is selected, new or changed, per theme (ADR 0023, 0024).
 * The network is quiet (slate buses, metro in the text colour) so zones and loads drawn with it
 * stay readable; interface colours never encode data values.
 */
export interface Ink {
  metro: RGB;
  bus: RGB;
  other: RGB;
  /** The route, stop or segment selected. */
  highlight: RGB;
  /** Something new: a route being drawn or added by a scenario (CSS --ice). */
  fresh: RGB;
  /** Something changed by a scenario (CSS --amber). */
  changed: RGB;
  /** Something removed by a scenario (CSS --loss). */
  removed: RGB;
}

export const INK: Record<Theme, Ink> = {
  dark: {
    metro: [214, 226, 236],
    bus: [92, 124, 150],
    other: [120, 132, 140],
    highlight: [245, 250, 255],
    fresh: [127, 220, 242],
    changed: [255, 180, 84],
    removed: [227, 73, 72],
  },
  light: {
    metro: [24, 38, 48],
    bus: [96, 124, 146],
    other: [120, 132, 140],
    highlight: [14, 26, 34],
    fresh: [8, 119, 154],
    changed: [196, 112, 0],
    removed: [194, 50, 44],
  },
};
