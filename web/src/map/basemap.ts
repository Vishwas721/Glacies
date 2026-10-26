import type { StyleSpecification } from "maplibre-gl";

// OpenFreeMap: no key, no request limits, attribution added from its tiles (phase 7 decisions).
// Its dark style keeps the basemap quiet under the data (ADR 0023). VITE_BASEMAP=blank gives a
// plain background, for offline work and CI.
const OPENFREEMAP = "https://tiles.openfreemap.org/styles/dark";
const BLANK: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#0b1218" } }],
};

export function basemapStyle(name: string | undefined): string | StyleSpecification {
  return name === "blank" ? BLANK : OPENFREEMAP;
}
