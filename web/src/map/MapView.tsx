// MapLibre basemap with deck.gl layers drawn into it, under its labels (MapboxOverlay, interleaved,
// ADR 0024), and the instruments that read the map itself: controls, edge ticks, cursor position
// and scale.

import "maplibre-gl/dist/maplibre-gl.css";

import type { Layer, PickingInfo } from "@deck.gl/core";
import type { ClipExtensionProps } from "@deck.gl/extensions";
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

import { useTheme } from "../ui/theme";
import { basemapStyle, firstLabel } from "./basemap";
import { type ClipBox, LENS_SIDE } from "./layers";
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
  maxZoom?: number;
  padding?: number | { top: number; bottom: number; left: number; right: number };
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
  /** The What-If Lens: layers tagged with onLensSide are cut at a draggable divider. */
  lens?: Lens | null;
  /** Tilt the map to look across raised zones (relief). */
  tilt?: boolean;
  /** Hide the instruments (ticks, cursor readout, controls): a quiet map for the Easy view. */
  plain?: boolean;
  /** False for a backdrop that must not take the page's scrolling (the landing page). */
  interactive?: boolean;
  /** False hides the basemap's labels: a backdrop where the data is the picture. */
  labels?: boolean;
  /** Called with the place clicked when no layer object was under the cursor. */
  onEmptyClick?: (lngLat: [number, number]) => void;
}

export interface Lens {
  left: string;
  right: string;
}

const PADDING = 48;

/**
 * The layers as deck.gl draws them: under the basemap's labels, and lens layers cut at the
 * divider's longitude.
 */
function place(
  map: MapLibre,
  layers: Layer[],
  fraction: number,
  beforeId: string | undefined,
): Layer[] {
  const lensOn = layers.some((l) => LENS_SIDE.has(l));
  if (!lensOn && !beforeId) return layers;
  let lng = 0;
  if (lensOn) {
    const { width, height } = map.getCanvas().getBoundingClientRect();
    lng = map.unproject([fraction * width, height / 2]).lng;
  }
  return layers.map((l) => {
    const side = LENS_SIDE.get(l);
    const clipBounds: ClipBox | undefined =
      side === "west" ? [-180, -90, lng, 90] : side === "east" ? [lng, -90, 180, 90] : undefined;
    // beforeId and the clip extension's prop are not in Layer's own props type.
    const props = { ...(beforeId ? { beforeId } : {}), ...(clipBounds ? { clipBounds } : {}) };
    return l.clone(props as Partial<ClipExtensionProps> as Partial<Layer["props"]>);
  });
}

/**
 * deck.gl 9.4 draws interleaved layers with a viewport sized from `map.transform.height`, which
 * MapLibre 6 no longer exposes (the map has no `transform`), so every frame threw. It reads only
 * the height there (and near/far planes, which MapLibre passes to the layer itself): give it the
 * canvas height. Remove when @deck.gl/mapbox supports MapLibre 6.
 */
function exposeHeight(map: MapLibre) {
  if ("transform" in map) return;
  Object.defineProperty(map, "transform", {
    configurable: true,
    get: () => ({ height: map.getCanvas().clientHeight }),
  });
}

// Where the camera was when the map was last torn down: switching theme rebuilds the map and
// must not throw the viewer back to the whole city.
let lastCamera: { center: [number, number]; zoom: number; bearing: number; pitch: number } | null =
  null;

export function MapView(props: MapViewProps) {
  const { bbox, layers, attribution, onClick, getTooltip, focus, controls, lens, tilt, plain } =
    props;
  const { onEmptyClick, interactive = true, labels = true } = props;
  const theme = useTheme();
  const [beforeId, setBeforeId] = useState<string | undefined>(undefined);
  // The divider lives here, not in the screen's state: moving it or the map re-cuts the lens
  // layers without re-rendering anything else.
  const [fraction, setFraction] = useState(0.5);
  // Read by the map's move handler, which is bound once.
  const latest = useRef({ layers, fraction, beforeId });
  useEffect(() => {
    latest.current = { layers, fraction, beforeId };
  }, [layers, fraction, beforeId]);
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibre | null>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const [cursor, setCursor] = useState<{ lng: number; lat: number } | null>(null);
  const [ticks, setTicks] = useState<Ticks | null>(null);
  const [zoom, setZoom] = useState<number | null>(null);
  const [scale, setScale] = useState<Scale | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const style = basemapStyle(import.meta.env.VITE_BASEMAP as string | undefined, theme);
    const camera = lastCamera;
    const map = new MapLibre({
      container: container.current,
      style,
      interactive,
      ...(camera
        ? camera
        : { bounds: [bbox[0], bbox[1], bbox[2], bbox[3]], fitBoundsOptions: { padding: PADDING } }),
      attributionControl: false,
    });
    const credits = new AttributionControl({ compact: true, customAttribution: attribution });
    map.addControl(credits, "bottom-right");
    exposeHeight(map);
    const deck = new MapboxOverlay({ interleaved: true, layers: [] });
    map.addControl(deck);
    mapRef.current = map;
    overlay.current = deck;

    // Ticks are re-read at most once a frame while the map moves.
    let frame = 0;
    const read = () => {
      frame = 0;
      setTicks(ticksFor(map));
      setZoom(map.getZoom());
      // A tilted map has no single scale; the bar would be wrong away from the centre.
      setScale(map.getPitch() > 0.5 ? null : scaleBar(map.getZoom(), map.getCenter().lat));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(read);
    };
    map.on("move", schedule);
    // Every move, in the same frame: a cut that lagged the map would slide across it.
    map.on("move", () => {
      const { layers: now, fraction: f, beforeId: before } = latest.current;
      if (now.some((l) => LENS_SIDE.has(l))) deck.setProps({ layers: place(map, now, f, before) });
    });
    map.on("resize", schedule);
    map.on("load", () => {
      read();
      const styleLayers = map.getStyle().layers;
      if (!labels) {
        for (const l of styleLayers) {
          if (l.type === "symbol") map.setLayoutProperty(l.id, "visibility", "none");
        }
      }
      setBeforeId(labels ? firstLabel(styleLayers) : undefined);
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
      const c = map.getCenter();
      lastCamera = {
        center: [c.lng, c.lat],
        zoom: map.getZoom(),
        bearing: map.getBearing(),
        pitch: map.getPitch(),
      };
      overlay.current = null;
      mapRef.current = null;
      setBeforeId(undefined);
      map.remove();
    };
    // The map is created once per city and theme; layers and handlers update through setProps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bbox.join(","), attribution, theme]);

  // A new city starts from its own extent, not from where the last map was.
  useEffect(
    () => () => {
      lastCamera = null;
    },
    [bbox.join(",")], // eslint-disable-line react-hooks/exhaustive-deps
  );

  useEffect(() => {
    const map = mapRef.current;
    overlay.current?.setProps({
      layers: map ? place(map, layers, fraction, beforeId) : layers,
      onClick:
        onClick || onEmptyClick
          ? (info) => {
              if (info.object || !onEmptyClick) onClick?.(info);
              else if (info.coordinate) onEmptyClick([info.coordinate[0]!, info.coordinate[1]!]);
            }
          : undefined,
      getTooltip: getTooltip ? (info) => getTooltip(info) : undefined,
    });
  }, [layers, fraction, beforeId, onClick, onEmptyClick, getTooltip, theme]);

  useEffect(() => {
    if (!focus) return;
    const [w, s, e, n] = focus.bbox;
    mapRef.current?.fitBounds([w, s, e, n] as LngLatBoundsLike, {
      padding: focus.padding ?? PADDING * 2,
      maxZoom: focus.maxZoom ?? 13.5,
      duration: 1200,
      essential: true,
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
    const map = mapRef.current;
    if (!map) return;
    if (tilt) map.easeTo({ pitch: 52, bearing: -14, duration: 900 });
    else if (map.getPitch() || map.getBearing())
      map.easeTo({ pitch: 0, bearing: 0, duration: 600 });
  }, [tilt]);

  const fitCity = () =>
    mapRef.current?.fitBounds(bbox as LngLatBoundsLike, { padding: PADDING, duration: 700 });

  if (plain) {
    return (
      <>
        <div ref={container} className="map-canvas" data-testid="map" />
        {lens && <LensDivider lens={lens} fraction={fraction} onFraction={setFraction} />}
      </>
    );
  }

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
      {lens && <LensDivider lens={lens} fraction={fraction} onFraction={setFraction} />}
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
