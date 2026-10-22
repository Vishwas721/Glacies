import type { StyleSpecification } from "maplibre-gl";

// OpenFreeMap: no key, no request limits, attribution added from its tiles (phase 7 decisions).
// VITE_BASEMAP=blank gives a plain background, for offline work and CI.
const OPENFREEMAP = "https://tiles.openfreemap.org/styles/positron";
const BLANK: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#f2f1ee" } }],
};

export function basemapStyle(name: string | undefined): string | StyleSpecification {
  return name === "blank" ? BLANK : OPENFREEMAP;
}
