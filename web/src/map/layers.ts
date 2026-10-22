// deck.gl layers built from API data. Kept free of React so the data-to-layer mapping can be
// tested without a WebGL context.

import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { LineLayer, PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";

import type { LonLat, Network, PatternFeature, SegmentFeature, StopFeature } from "../api/types";
import { HIGHLIGHT, MODE_COLOUR, OTHER_MODE, type RGB, upperBound, viridis } from "./colours";

export interface ZoneValue {
  h3: string;
  value: number;
}

export function zoneLayer(id: string, zones: ZoneValue[], opacity = 0.55): Layer {
  const top = upperBound(zones.map((z) => z.value));
  return new H3HexagonLayer<ZoneValue>({
    id,
    data: zones,
    getHexagon: (z) => z.h3,
    getFillColor: (z) => [...viridis(z.value / top), 255],
    extruded: false,
    stroked: false,
    opacity,
    pickable: true,
    updateTriggers: { getFillColor: top },
  });
}

const modeColour = (modes: string[]): RGB =>
  modes.includes("metro") ? MODE_COLOUR.metro! : (MODE_COLOUR[modes[0] ?? ""] ?? OTHER_MODE);

/** Stop-to-stop segments, wider where more vehicles run in the AM window. */
export function networkLayer(network: Network): Layer {
  return new LineLayer<SegmentFeature>({
    id: "network",
    data: network.features,
    getSourcePosition: (f) => f.geometry.coordinates[0],
    getTargetPosition: (f) => f.geometry.coordinates[1],
    getColor: (f) => [...modeColour(f.properties.modes), 200],
    getWidth: (f) => 1 + Math.sqrt(f.properties.window_trips) / 2,
    widthUnits: "pixels",
    widthMaxPixels: 8,
    pickable: true,
  });
}

export function stopsLayer(stops: StopFeature[], selected: ReadonlySet<string> = new Set()): Layer {
  return new ScatterplotLayer<StopFeature>({
    id: "stops",
    // Stations are drawn by their platforms; showing both would double every metro stop.
    data: stops.filter((s) => !s.properties.station),
    getPosition: (s) => s.geometry.coordinates,
    getRadius: (s) => (s.properties.modes.includes("metro") ? 60 : 25),
    radiusMinPixels: 1.5,
    radiusMaxPixels: 8,
    getFillColor: (s) =>
      selected.has(stopKey(s)) ? [...HIGHLIGHT, 255] : [...modeColour(s.properties.modes), 220],
    pickable: true,
    updateTriggers: { getFillColor: [...selected].join(",") },
  });
}

export const stopKey = (s: StopFeature) => `${s.properties.feed}:${s.properties.stop_id}`;

export function routeLayer(patterns: PatternFeature[]): Layer {
  return new PathLayer<PatternFeature>({
    id: "selected-route",
    data: patterns,
    getPath: (p) => p.geometry.coordinates,
    getColor: [...HIGHLIGHT, 230],
    getWidth: 5,
    widthUnits: "pixels",
    pickable: false,
  });
}

/** The stops picked for a new route, joined in order. */
export function draftLayer(path: LonLat[]): Layer {
  return new PathLayer<{ path: LonLat[] }>({
    id: "draft-route",
    data: path.length > 1 ? [{ path }] : [],
    getPath: (d) => d.path,
    getColor: [...HIGHLIGHT, 255],
    getWidth: 4,
    widthUnits: "pixels",
  });
}
