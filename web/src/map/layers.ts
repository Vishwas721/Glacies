// deck.gl layers built from API data. Kept free of React so the data-to-layer mapping can be
// tested without a WebGL context.

import { ClipExtension, type ClipExtensionProps } from "@deck.gl/extensions";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { LineLayer, PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";

import type { LonLat, Network, PatternFeature, SegmentFeature, StopFeature } from "../api/types";
import { HIGHLIGHT, MODE_COLOUR, NEW, OTHER_MODE, type RGB, upperBound, viridis } from "./colours";

export interface ZoneValue {
  h3: string;
  value: number;
}

/** West, south, east, north: the part of the map a layer is drawn in. */
export type ClipBox = [number, number, number, number];

// One instance for every layer: a new extension object per render makes deck.gl rebuild the
// layer's shaders, and the lens re-renders on every frame of a pan (18 fps measured).
const CLIP = new ClipExtension();

/**
 * Which side of the What-If Lens a layer belongs to. The map view cuts these layers at the
 * divider itself on every move, so panning never goes through React (20-30 fps when it did).
 */
export const LENS_SIDE = new WeakMap<Layer, "west" | "east">();

/** The whole world: a lens layer's clip until the map view sets the divider's longitude. */
export const WORLD: ClipBox = [-180, -90, 180, 90];

export function onLensSide<L extends Layer>(layer: L, side: "west" | "east"): L {
  LENS_SIDE.set(layer, side);
  return layer;
}

/** Props that draw a layer only inside `clip` (the What-If Lens), cut exactly at its edge. */
export function clipped(clip: ClipBox | undefined): Partial<ClipExtensionProps> & {
  extensions?: ClipExtension[];
} {
  return clip ? { extensions: [CLIP], clipBounds: clip, clipByInstance: false } : {};
}

interface ZoneOptions {
  /** Top of the colour scale; two layers compared side by side must share it. */
  top?: number;
  clip?: ClipBox;
  /** Raise each zone by its value, up to RELIEF_TOP_M at the top of the scale. */
  relief?: boolean;
}

/** Height of a zone at the top of the colour scale, in metres: a third of the city's width. */
export const RELIEF_TOP_M = 4000;

export function zoneLayer(id: string, zones: ZoneValue[], options: ZoneOptions = {}): Layer {
  const top = options.top ?? upperBound(zones.map((z) => z.value));
  return new H3HexagonLayer<ZoneValue, ClipExtensionProps>({
    id,
    data: zones,
    getHexagon: (z) => z.h3,
    // Values below a quarter of the top fade toward clear: almost every zone reaches some tiny
    // share, and a solid low colour would hide the basemap over the whole study area.
    getFillColor: (z) => [
      ...viridis(z.value / top),
      Math.round(255 * Math.min(1, (4 * z.value) / top)),
    ],
    extruded: options.relief ?? false,
    getElevation: (z) => Math.min(1, Math.max(0, z.value / top)) * RELIEF_TOP_M,
    stroked: false,
    opacity: options.relief ? 0.9 : 0.6,
    pickable: true,
    updateTriggers: { getFillColor: top, getElevation: top },
    ...clipped(options.clip),
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
    getColor: (f) => [
      ...modeColour(f.properties.modes),
      f.properties.modes.includes("metro") ? 230 : 110,
    ],
    getWidth: (f) => 0.5 + Math.sqrt(f.properties.window_trips) / 3,
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
      selected.has(stopKey(s)) ? [...NEW, 255] : [...modeColour(s.properties.modes), 220],
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
    getColor: [...NEW, 255],
    getWidth: 4,
    widthUnits: "pixels",
  });
}
