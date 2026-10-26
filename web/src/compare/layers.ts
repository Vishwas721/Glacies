// Layers for comparing a scenario with the baseline (PRD §41) and for its loads (PRD §42).

import type { Layer } from "@deck.gl/core";
import { PathStyleExtension, type PathStyleExtensionProps } from "@deck.gl/extensions";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { LineLayer, PathLayer } from "@deck.gl/layers";

import type { ChangeKind, ChangedRoute, LonLat, Pairs } from "../api/types";
import { CHANGED, NEW, type RGB, viridis } from "../map/colours";
import { type ClipBox, clipped, type ZoneValue } from "../map/layers";

// The same classes and colours as the comparison maps of `glacies scenario compare`
// (src/glacies/scenario/compare.py): blue gains, red losses, darker for larger changes.
export const DELTA_BREAKS = [0.0005, 0.002]; // 0.05 and 0.2 percentage points
export const GAIN: RGB[] = [
  [134, 182, 239],
  [57, 135, 229],
  [24, 79, 149],
];
export const LOSS: RGB[] = [
  [241, 157, 153],
  [227, 73, 72],
  [163, 41, 42],
];

export function deltaColour(delta: number): [number, number, number, number] {
  if (delta === 0 || !Number.isFinite(delta)) return [0, 0, 0, 0];
  const arm = delta > 0 ? GAIN : LOSS;
  const step = DELTA_BREAKS.filter((b) => Math.abs(delta) >= b).length;
  return [...arm[step]!, 230];
}

export function deltaZoneLayer(zones: ZoneValue[]): Layer {
  return new H3HexagonLayer<ZoneValue>({
    id: "zones-change",
    data: zones.filter((z) => z.value !== 0),
    getHexagon: (z) => z.h3,
    getFillColor: (z) => deltaColour(z.value),
    extruded: false,
    stroked: false,
    opacity: 0.75,
    pickable: true,
  });
}

// Removed in the loss red, added in the interface's "new" ice, modified in its "changed" amber.
export const KIND_COLOUR: Record<ChangeKind, RGB> = {
  removed: [227, 73, 72],
  added: NEW,
  modified: CHANGED,
};

export interface ChangeLine {
  mutationIdx: number;
  kind: ChangeKind;
  name: string;
  path: LonLat[];
}

/** Removed routes dashed, added routes solid and wide, modified routes solid (PRD §41). */
export function changesLayer(routes: ChangedRoute[], clip?: ClipBox): Layer {
  const data: ChangeLine[] = routes.flatMap((r) =>
    r.coordinates.map((path) => ({
      mutationIdx: r.mutation_idx,
      kind: r.kind,
      name: r.name ?? r.route_id,
      path,
    })),
  );
  const clip_ = clipped(clip);
  return new PathLayer<ChangeLine, PathStyleExtensionProps<ChangeLine>>({
    id: "changes",
    data,
    getPath: (d) => d.path,
    getColor: (d) => [...KIND_COLOUR[d.kind], 240],
    getWidth: (d) => (d.kind === "added" ? 7 : 5),
    widthUnits: "pixels",
    getDashArray: (d) => (d.kind === "removed" ? [3, 2] : [0, 0]),
    dashJustified: true,
    pickable: true,
    ...clip_,
    extensions: [new PathStyleExtension({ dash: true }), ...(clip_.extensions ?? [])],
  });
}

export interface PairValue {
  source: LonLat;
  target: LonLat;
  passengers: number;
  loadFactor: number;
}

export function pairValues(
  pairs: Pairs,
  index: number[],
  passengers: number[],
  loadFactor: number[],
): PairValue[] {
  return index.map((p, i) => {
    const c = pairs.coordinates[p]!;
    return {
      source: [c[0], c[1]],
      target: [c[2], c[3]],
      passengers: passengers[i]!,
      loadFactor: loadFactor[i]!,
    };
  });
}

/** Load factor 1.5 (well past design capacity) is the top of the colour scale. */
export const LOAD_FACTOR_TOP = 1.5;

export function loadLayer(id: string, data: PairValue[], clip?: ClipBox): Layer {
  return new LineLayer<PairValue>({
    id,
    data,
    getSourcePosition: (d) => d.source,
    getTargetPosition: (d) => d.target,
    getColor: (d) => [...viridis(d.loadFactor / LOAD_FACTOR_TOP), 230],
    getWidth: (d) => 1 + Math.sqrt(d.passengers) / 6,
    widthUnits: "pixels",
    widthMaxPixels: 12,
    pickable: true,
    ...clipped(clip),
  });
}
