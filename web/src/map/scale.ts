// A metric scale bar for the map centre, read from the zoom (MapLibre's 512-pixel tiles).

export interface Scale {
  px: number;
  label: string;
}

const EARTH_CIRCUMFERENCE_M = 40_075_016.686;
const NICE = [1, 2, 5];

/** The longest round distance (1, 2 or 5 × 10ⁿ m) that fits in `maxPx` pixels. */
export function scaleBar(zoom: number, lat: number, maxPx = 96): Scale {
  const metresPerPx = (EARTH_CIRCUMFERENCE_M * Math.cos((lat * Math.PI) / 180)) / (512 * 2 ** zoom);
  const max = metresPerPx * maxPx;
  const power = 10 ** Math.floor(Math.log10(max));
  const metres = power * NICE.filter((n) => n * power <= max).at(-1)!;
  return {
    px: Math.round(metres / metresPerPx),
    label: metres >= 1000 ? `${metres / 1000} km` : `${metres} m`,
  };
}
