import type { FieldInfo } from "../api/types";

export type ZoneLayer = "none" | "population" | "employment" | "accessibility";
/** Which network a result layer shows; "change" is scenario minus baseline. */
export type View = "baseline" | "scenario" | "change";
export type Loads = "none" | "crowding" | "flows";

export interface LayerState {
  network: boolean;
  stops: boolean;
  zones: ZoneLayer;
  percentile: number;
  thresholdMin: number;
  view: View;
  loads: Loads;
}

export const INITIAL_LAYERS: LayerState = {
  network: true,
  stops: false,
  zones: "accessibility",
  percentile: 50,
  thresholdMin: 45,
  view: "change",
  loads: "none",
};

export interface Legend {
  top: number;
  info: FieldInfo | undefined;
}
