// MapLibre basemap with deck.gl layers drawn on top (MapboxOverlay works with MapLibre).

import "maplibre-gl/dist/maplibre-gl.css";

import type { Layer, PickingInfo } from "@deck.gl/core";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { AttributionControl, Map as MapLibre, NavigationControl, setWorkerUrl } from "maplibre-gl";
// MapLibre finds its worker by a URL relative to its own module, which Vite's pre-bundling
// moves; bundling the worker here gives it a URL that works in dev and in the build.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { useEffect, useRef } from "react";

import { basemapStyle } from "./basemap";

setWorkerUrl(workerUrl);

interface MapViewProps {
  bbox: [number, number, number, number];
  layers: Layer[];
  /** Credits for the city's datasets, shown with the basemap's. */
  attribution: string;
  onClick?: (info: PickingInfo) => void;
  getTooltip?: (info: PickingInfo) => string | null;
}

export function MapView({ bbox, layers, attribution, onClick, getTooltip }: MapViewProps) {
  const container = useRef<HTMLDivElement>(null);
  const overlay = useRef<MapboxOverlay | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const map = new MapLibre({
      container: container.current,
      style: basemapStyle(import.meta.env.VITE_BASEMAP as string | undefined),
      bounds: [bbox[0], bbox[1], bbox[2], bbox[3]],
      attributionControl: false,
    });
    map.addControl(new AttributionControl({ compact: true, customAttribution: attribution }));
    map.addControl(new NavigationControl({ showCompass: false }), "top-left");
    const deck = new MapboxOverlay({ interleaved: false, layers: [] });
    map.addControl(deck);
    overlay.current = deck;
    return () => {
      overlay.current = null;
      map.remove();
    };
    // The map is created once per city; layers and handlers update through setProps below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bbox.join(","), attribution]);

  useEffect(() => {
    overlay.current?.setProps({
      layers,
      onClick: onClick ? (info) => onClick(info) : undefined,
      getTooltip: getTooltip ? (info) => getTooltip(info) : undefined,
    });
  }, [layers, onClick, getTooltip]);

  return <div ref={container} className="map-canvas" data-testid="map" />;
}
