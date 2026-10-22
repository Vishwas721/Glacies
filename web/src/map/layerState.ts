import type { FieldInfo } from "../api/types";

export type ZoneLayer = "none" | "population" | "employment" | "accessibility";

export interface LayerState {
  network: boolean;
  stops: boolean;
  zones: ZoneLayer;
  percentile: number;
  thresholdMin: number;
}

export const INITIAL_LAYERS: LayerState = {
  network: true,
  stops: false,
  zones: "accessibility",
  percentile: 50,
  thresholdMin: 45,
};

export interface Legend {
  top: number;
  info: FieldInfo | undefined;
}
