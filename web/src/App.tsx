// The Glacies screen (PRD §39): scenario on the left, map in the middle, layers and details on
// the right. The city comes from ?city=, else the first configured one.

import type { Layer, PickingInfo } from "@deck.gl/core";
import { useCallback, useMemo, useState } from "react";

import {
  useAccessibility,
  useCities,
  useCity,
  useNetwork,
  useRoute,
  useRoutes,
  useStops,
  useZones,
} from "./api/queries";
import type { FieldInfo, SegmentFeature, StopFeature } from "./api/types";
import { LayerPanel } from "./map/LayerPanel";
import { INITIAL_LAYERS, type LayerState, type Legend } from "./map/layerState";
import {
  draftLayer,
  networkLayer,
  routeLayer,
  stopKey,
  stopsLayer,
  type ZoneValue,
  zoneLayer,
} from "./map/layers";
import { MapView } from "./map/MapView";
import { upperBound } from "./map/colours";
import { emptyDraft, type Draft } from "./scenario/draft";
import { ScenarioBuilder } from "./scenario/ScenarioBuilder";
import { Field } from "./ui/Quantity";
import { format } from "./ui/format";

export function App() {
  const cities = useCities();
  const requested = new URLSearchParams(window.location.search).get("city");
  const city = requested ?? cities.data?.[0]?.id;
  if (cities.error) return <Message text={`The API is not reachable: ${cities.error.message}`} />;
  if (!city) return <Message text="Loading…" />;
  return <CityView city={city} />;
}

function Message({ text }: { text: string }) {
  return (
    <div className="shell">
      <header className="topbar">
        <h1>Glacies</h1>
      </header>
      <p className="message">{text}</p>
    </div>
  );
}

type Selection =
  | { kind: "stop"; stop: StopFeature }
  | { kind: "segment"; segment: SegmentFeature }
  | { kind: "zone"; zone: ZoneValue };

function CityView({ city }: { city: string }) {
  const detail = useCity(city);
  const routes = useRoutes(city);
  const network = useNetwork(city);
  const [layers, setLayers] = useState<LayerState>(INITIAL_LAYERS);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [selectedRoute, setSelectedRoute] = useState<number | null>(null);
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<StopFeature[]>([]);
  const [selection, setSelection] = useState<Selection | null>(null);

  const showStops = layers.stops || picking;
  const stops = useStops(city);
  const zones = useZones(city);
  const access = useAccessibility(
    city,
    "baseline",
    layers.percentile,
    layers.thresholdMin,
    layers.zones === "accessibility",
  );
  const route = useRoute(city, selectedRoute);

  // The zone values and their label for the layer chosen.
  const zoneData = useMemo((): { values: ZoneValue[]; info: FieldInfo | undefined } | null => {
    if (layers.zones === "accessibility" && access.data) {
      const a = access.data;
      return {
        values: a.h3_cell.map((h3, i) => ({ h3, value: a.est_jobs_share[i]! })),
        info: a.fields.est_jobs_share,
      };
    }
    const z = zones.data;
    if (!z) return null;
    if (layers.zones === "population") {
      return {
        values: z.h3_cell.map((h3, i) => ({ h3, value: z.population[i]! })),
        info: z.fields.population,
      };
    }
    if (layers.zones === "employment" && z.est_employment_share) {
      const share = z.est_employment_share;
      return {
        values: z.h3_cell.map((h3, i) => ({ h3, value: share[i]! })),
        info: z.fields.est_employment_share,
      };
    }
    return null;
  }, [layers.zones, access.data, zones.data]);

  const pickedKeys = useMemo(() => new Set(picked.map(stopKey)), [picked]);
  const deckLayers = useMemo(() => {
    const out: Layer[] = [];
    if (zoneData) out.push(zoneLayer(`zones-${layers.zones}`, zoneData.values));
    if (layers.network && network.data) out.push(networkLayer(network.data));
    if (route.data && selectedRoute !== null) out.push(routeLayer(route.data.features));
    if (showStops && stops.data) out.push(stopsLayer(stops.data.features, pickedKeys));
    if (picked.length) out.push(draftLayer(picked.map((s) => s.geometry.coordinates)));
    return out;
  }, [
    zoneData,
    layers,
    network.data,
    route.data,
    selectedRoute,
    showStops,
    stops.data,
    picked,
    pickedKeys,
  ]);

  const legend: Legend | null = zoneData
    ? { top: upperBound(zoneData.values.map((v) => v.value)), info: zoneData.info }
    : null;

  const onClick = useCallback(
    (info: PickingInfo) => {
      const id = info.layer?.id;
      if (id === "stops") {
        const stop = info.object as StopFeature;
        if (picking) setPicked((p) => [...p, stop]);
        else setSelection({ kind: "stop", stop });
      } else if (id === "network") {
        setSelection({ kind: "segment", segment: info.object as SegmentFeature });
      } else if (id?.startsWith("zones-")) {
        setSelection({ kind: "zone", zone: info.object as ZoneValue });
      } else {
        setSelection(null);
      }
    },
    [picking],
  );

  const zoneInfo = zoneData?.info;
  const getTooltip = useCallback(
    (info: PickingInfo) => {
      if (!info.object) return null;
      const id = info.layer?.id;
      if (id === "stops") {
        const s = (info.object as StopFeature).properties;
        return `${s.name ?? s.stop_id} · ${s.modes.join(", ")}`;
      }
      if (id === "network") {
        const p = (info.object as SegmentFeature).properties;
        return `${p.modes.join(", ")} · ${p.window_trips} trips in the AM window (Observed)`;
      }
      if (id?.startsWith("zones-") && zoneInfo) {
        const z = info.object as ZoneValue;
        return `${format(z.value, zoneInfo.unit)} (${zoneInfo.nature})`;
      }
      return null;
    },
    [zoneInfo],
  );

  if (detail.error) return <Message text={detail.error.message} />;
  if (!detail.data) return <Message text="Loading…" />;
  const c = detail.data;
  const attribution = `Data: ${[...new Set(c.sources.map((s) => `${s.source} (${s.license})`))].join(", ")}`;

  return (
    <div className="shell">
      <header className="topbar">
        <h1>Glacies</h1>
        <span className="city">
          {c.name} · timetable of {c.service_date ?? "?"}
        </span>
      </header>
      <main className="layout">
        <aside className="panel" aria-label="Scenario">
          <h2>Scenario</h2>
          {routes.data ? (
            <ScenarioBuilder
              city={city}
              routes={routes.data}
              draft={draft}
              onDraftChange={setDraft}
              selectedRoute={selectedRoute}
              onSelectRoute={setSelectedRoute}
              picking={picking}
              onPickingChange={setPicking}
              picked={picked}
              onPickedChange={setPicked}
            />
          ) : (
            <p className="note">Loading routes…</p>
          )}
        </aside>
        <section className="map" aria-label="Map">
          <MapView
            bbox={c.bbox}
            layers={deckLayers}
            attribution={attribution}
            onClick={onClick}
            getTooltip={getTooltip}
          />
        </section>
        <aside className="panel" aria-label="Metrics">
          <h2>Layers</h2>
          <LayerPanel
            state={layers}
            onChange={setLayers}
            percentiles={c.accessibility.percentiles}
            thresholds={c.accessibility.thresholds_min}
            legend={legend}
          />
          {selection && (
            <SelectionCard selection={selection} info={zoneInfo} fields={network.data?.fields} />
          )}
          {route.data && selectedRoute !== null && (
            <section className="card" aria-label="Selected route">
              <h3>
                {route.data.route.short_name ?? route.data.route.route_id}{" "}
                <span className="muted">{route.data.route.long_name}</span>
              </h3>
              <p>
                <Field value={route.data.route.trips} info={route.data.fields.trips} /> on the day
              </p>
              <button type="button" className="link" onClick={() => setSelectedRoute(null)}>
                clear
              </button>
            </section>
          )}
        </aside>
      </main>
    </div>
  );
}

function SelectionCard({
  selection,
  info,
  fields,
}: {
  selection: Selection;
  info: FieldInfo | undefined;
  fields: Record<string, FieldInfo> | undefined;
}) {
  if (selection.kind === "stop") {
    const s = selection.stop.properties;
    return (
      <section className="card" aria-label="Selected stop">
        <h3>{s.name ?? s.stop_id}</h3>
        <p className="muted">
          {s.feed} stop {s.stop_id} · {s.modes.join(", ")}
        </p>
      </section>
    );
  }
  if (selection.kind === "segment") {
    const p = selection.segment.properties;
    return (
      <section className="card" aria-label="Selected segment">
        <h3>{p.modes.join(", ")} segment</h3>
        <p>
          <Field value={p.window_trips} info={fields?.window_trips} /> trips in the AM window,{" "}
          <Field value={p.routes} info={fields?.routes} /> routes
        </p>
      </section>
    );
  }
  return (
    <section className="card" aria-label="Selected zone">
      <h3>Zone {selection.zone.h3}</h3>
      <p>
        <Field value={selection.zone.value} info={info} />
      </p>
      <p className="note">{info?.description}</p>
    </section>
  );
}
