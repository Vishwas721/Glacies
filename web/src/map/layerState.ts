import type { FieldInfo } from "../api/types";

export type ZoneLayer = "none" | "population" | "employment" | "accessibility";
/**
 * Which network a result layer shows; "change" is scenario minus baseline, "split" draws the
 * baseline left of the lens divider and the scenario right of it.
 */
export type View = "baseline" | "scenario" | "change" | "split";
export type Loads = "none" | "crowding" | "flows";

export interface LayerState {
  network: boolean;
  stops: boolean;
  zones: ZoneLayer;
  percentile: number;
  thresholdMin: number;
  view: View;
  loads: Loads;
  /** Zones raised by their value on a tilted map (levels only, not changes). */
  relief: boolean;
}

export const INITIAL_LAYERS: LayerState = {
  network: true,
  stops: false,
  zones: "accessibility",
  percentile: 50,
  thresholdMin: 45,
  view: "change",
  loads: "none",
  relief: false,
};

export interface Legend {
  top: number;
  info: FieldInfo | undefined;
}
