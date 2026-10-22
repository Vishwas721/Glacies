// Colour scales. Levels use viridis (perceptually uniform, readable with colour-vision
// deficiencies); deltas will use a diverging scale (Phase 7 M7).

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

export const MODE_COLOUR: Record<string, RGB> = {
  metro: [123, 50, 148],
  bus: [70, 110, 160],
};
export const OTHER_MODE: RGB = [120, 120, 120];
export const HIGHLIGHT: RGB = [230, 85, 13];
