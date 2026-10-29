import type { StyleSpecification } from "maplibre-gl";

import type { Theme } from "../ui/theme";

// OpenFreeMap: no key, no request limits, attribution added from its tiles (phase 7 decisions).
// Its dark and Positron styles keep the basemap quiet under the data (ADR 0023, 0024).
// VITE_BASEMAP=blank gives a plain background, for offline work and CI.
const OPENFREEMAP: Record<Theme, string> = {
  dark: "https://tiles.openfreemap.org/styles/dark",
  light: "https://tiles.openfreemap.org/styles/positron",
};
const PLAIN: Record<Theme, string> = { dark: "#0b1218", light: "#eef1f3" };

const blank = (theme: Theme): StyleSpecification => ({
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": PLAIN[theme] } }],
});

export function basemapStyle(
  name: string | undefined,
  theme: Theme = "dark",
): string | StyleSpecification {
  return name === "blank" ? blank(theme) : OPENFREEMAP[theme];
}

/**
 * The basemap's first label layer: data drawn below it leaves place and road names readable
 * (ADR 0024). None on a blank basemap, where the data goes on top.
 */
export function firstLabel(layers: { id: string; type: string }[]): string | undefined {
  return layers.find((l) => l.type === "symbol")?.id;
}
