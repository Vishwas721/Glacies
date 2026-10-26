// MapLibre basemap with deck.gl layers drawn on top (MapboxOverlay works with MapLibre), and the
// instruments that read the map itself: controls, edge ticks, cursor position and scale.

import "maplibre-gl/dist/maplibre-gl.css";

import type { Layer, PickingInfo } from "@deck.gl/core";
import { MapboxOverlay } from "@deck.gl/mapbox";
import {
  AttributionControl,
  Map as MapLibre,
  setWorkerUrl,
  type LngLatBoundsLike,
} from "maplibre-gl";
// MapLibre finds its worker by a URL relative to its own module, which Vite's pre-bundling
// moves; bundling the worker here gives it a URL that works in dev and in the build.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { basemapStyle } from "./basemap";
import { EdgeTicks } from "./EdgeTicks";
import { type Ticks, ticksFor } from "./ticks";
import { LensDivider } from "./LensDivider";
import { type Scale, scaleBar } from "./scale";

setWorkerUrl(workerUrl);

type BBox = [number, number, number, number];

/** A place to fly to; `id` changes when the same box should be fitted again. */
export interface Focus {
  id: string;
  bbox: BBox;
}

interface MapViewProps {
  bbox: BBox;
  layers: Layer[];
  /** Credits for the city's datasets, shown with the basemap's. */
  attribution: string;
  onClick?: (info: PickingInfo) => void;
  getTooltip?: (info: PickingInfo) => string | null;
  focus?: Focus | null;
  /** Extra map buttons from the screen, e.g. "fit to changes". */
  controls?: ReactNode;
  /** The What-If Lens: a divider at `fraction` of the width; reports its longitude. */
  lens?: Lens | null;
}

export interface Lens {
  fraction: number;
  onFraction: (fraction: number) => void;
  onLng: (lng: number) => void;
  left: string;
  right: string;
}

const PADDING = 48;

function reportLens(map: MapLibre, lens: Lens | null | undefined) {
  if (!lens) return;
  const { width, height } = map.getCanvas().getBoundingClientRect();
  lens.onLng(map.unproject([lens.fraction * width, height / 2]).lng);
}

export function MapView(props: MapViewProps) {
  const { bbox, layers, attribution, onClick, getTooltip, focus, controls, lens } = props;
  // Read by the map's move handler, which is bound once.
  const lensRef = useRef(lens);
  useEffect(() => {
    lensRef.current = lens;
  }, [lens]);
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibre | null>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const [cursor, setCursor] = useState<{ lng: number; lat: number } | null>(null);
  const [ticks, setTicks] = useState<Ticks | null>(null);
  const [zoom, setZoom] = useState<number | null>(null);
  const [scale, setScale] = useState<Scale | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const map = new MapLibre({
      container: container.current,
      style: basemapStyle(import.meta.env.VITE_BASEMAP as string | undefined),
      bounds: [bbox[0], bbox[1], bbox[2], bbox[3]],
      fitBoundsOptions: { padding: PADDING },
      attributionControl: false,
    });
    const credits = new AttributionControl({ compact: true, customAttribution: attribution });
    map.addControl(credits, "bottom-right");
    const deck = new MapboxOverlay({ interleaved: false, layers: [] });
    map.addControl(deck);
    mapRef.current = map;
    overlay.current = deck;

    // Ticks are re-read at most once a frame while the map moves.
    let frame = 0;
    const read = () => {
      frame = 0;
      reportLens(map, lensRef.current);
      setTicks(ticksFor(map));
      setZoom(map.getZoom());
      setScale(scaleBar(map.getZoom(), map.getCenter().lat));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(read);
    };
    map.on("move", schedule);
    map.on("resize", schedule);
    map.on("load", () => {
      read();
      // Credits start folded behind the (i) button: every source stays one click away
      // and the Data mode lists them in full.
      const attrib = container.current?.querySelector(".maplibregl-ctrl-attrib");
      attrib?.classList.remove("maplibregl-compact-show");
      attrib?.removeAttribute("open");
    });
    map.on("mousemove", (e) => setCursor({ lng: e.lngLat.lng, lat: e.lngLat.lat }));
    map.on("mouseout", () => setCursor(null));
    return () => {
      cancelAnimationFrame(frame);
      overlay.current = null;
      mapRef.current = null;
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

  useEffect(() => {
    if (!focus) return;
    const [w, s, e, n] = focus.bbox;
    mapRef.current?.fitBounds([w, s, e, n] as LngLatBoundsLike, {
      padding: PADDING * 2,
      maxZoom: 13.5,
      duration: 900,
    });
  }, [focus]);

  // The lens cuts along a meridian, which a screen line only follows on a flat, north-up map:
  // while it is on, the map cannot be rotated or tilted.
  const lensOn = Boolean(lens);
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (lensOn) {
      map.dragRotate.disable();
      map.touchZoomRotate.disableRotation();
      if (map.getBearing() || map.getPitch()) map.easeTo({ bearing: 0, pitch: 0, duration: 400 });
    } else {
      map.dragRotate.enable();
      map.touchZoomRotate.enableRotation();
    }
  }, [lensOn]);
  useEffect(() => {
    if (mapRef.current) reportLens(mapRef.current, lens);
  }, [lens]);

  const fitCity = () =>
    mapRef.current?.fitBounds(bbox as LngLatBoundsLike, { padding: PADDING, duration: 700 });

  return (
    <>
      <div ref={container} className="map-canvas" data-testid="map" />
      {ticks && <EdgeTicks ticks={ticks} />}
      <div className="map-controls" role="toolbar" aria-label="Map controls">
        <button type="button" aria-label="Zoom in" onClick={() => mapRef.current?.zoomIn()}>
          <svg viewBox="0 0 14 14" aria-hidden="true">
            <path d="M7 2v10M2 7h10" />
          </svg>
        </button>
        <button type="button" aria-label="Zoom out" onClick={() => mapRef.current?.zoomOut()}>
          <svg viewBox="0 0 14 14" aria-hidden="true">
            <path d="M2 7h10" />
          </svg>
        </button>
        <button type="button" aria-label="Fit the city" title="Fit the city" onClick={fitCity}>
          <svg viewBox="0 0 14 14" aria-hidden="true">
            <path d="M1.5 5V1.5H5M9 1.5h3.5V5M12.5 9v3.5H9M5 12.5H1.5V9" />
          </svg>
        </button>
        {controls}
      </div>
      {lens && <LensDivider lens={lens} />}
      <p className="map-readout" aria-label="Cursor position">
        {cursor
          ? `${Math.abs(cursor.lat).toFixed(4)}°${cursor.lat >= 0 ? "N" : "S"}  ${Math.abs(cursor.lng).toFixed(4)}°${cursor.lng >= 0 ? "E" : "W"}`
          : "—"}
        {zoom !== null && <span>z {zoom.toFixed(1)}</span>}
        {scale && (
          <span className="scale-bar" style={{ width: scale.px }}>
            {scale.label}
          </span>
        )}
      </p>
    </>
  );
}
