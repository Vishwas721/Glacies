// The Glacies screen (PRD §39, ADR 0023): a mode rail, the mode's panel on the left (layers, the
// scenario builder, results), the map in the middle with a dock under it for runs and playback,
// and an inspector on the right for what is selected and the comparison. The city comes from
// ?city=, else the first configured one.

import type { Layer, PickingInfo } from "@deck.gl/core";
import { useCallback, useMemo, useState } from "react";

import {
  useAccessibility,
  useChanges,
  useChecks,
  useCities,
  useCity,
  useCrowding,
  useFlows,
  useNetwork,
  useRoute,
  useRoutes,
  useStops,
  useZones,
} from "./api/queries";
import type { FieldInfo, SegmentFeature, StopFeature } from "./api/types";
import { ComparePanel } from "./compare/ComparePanel";
import {
  changesLayer,
  deltaZoneLayer,
  loadLayer,
  type PairValue,
  pairValues,
} from "./compare/layers";
import { ModelChecks } from "./compare/ModelChecks";
import { Playback } from "./compare/Playback";
import { ResultPicker } from "./compare/ResultPicker";
import type { ResultChoice } from "./compare/results";
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
import { MapLegend } from "./map/MapLegend";
import { type Focus, MapView } from "./map/MapView";
import { upperBound } from "./map/colours";
import { emptyDraft, type Draft } from "./scenario/draft";
import { ScenarioBuilder } from "./scenario/ScenarioBuilder";
import { SimulationStatus } from "./scenario/SimulationStatus";
import { Dock, type DockTab } from "./shell/Dock";
import { Masthead, type NetworkSize } from "./shell/Masthead";
import { initialMode, type Mode, MODES, rememberMode } from "./shell/modes";
import { Rail } from "./shell/Rail";
import { Field } from "./ui/Quantity";
import { format, formatDelta } from "./ui/format";

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
    <div className="splash">
      <p className="splash-mark">Glacies</p>
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
  const [result, setResult] = useState<ResultChoice | null>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [mode, setModeState] = useState<Mode>(initialMode);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [dockOpen, setDockOpen] = useState(false);
  const [dockTab, setDockTab] = useState<string | null>(null);
  const [simulation, setSimulation] = useState<string | null>(null);
  const setMode = (next: Mode) => {
    setModeState(next);
    rememberMode(next);
  };
  const openDock = (tab: string) => {
    setDockTab(tab);
    setDockOpen(true);
  };
  // Without a chosen result everything shows the baseline.
  const view = result ? layers.view : "baseline";
  const resultRef = result && view !== "baseline" ? result.key : "baseline";

  const showStops = layers.stops || picking;
  const stops = useStops(city);
  const zones = useZones(city);
  const access = useAccessibility(
    city,
    resultRef,
    layers.percentile,
    layers.thresholdMin,
    layers.zones === "accessibility",
  );
  const route = useRoute(city, selectedRoute);
  const crowding = useCrowding(city, resultRef, layers.loads === "crowding");
  const flows = useFlows(city, resultRef, layers.loads === "flows");
  const changes = useChanges(city, result?.key ?? null);
  const checks = useChecks(city, resultRef, layers.loads !== "none");

  // The zone values and their label for the layer chosen.
  const zoneData = useMemo((): {
    values: ZoneValue[];
    info: FieldInfo | undefined;
    delta?: boolean;
  } | null => {
    if (layers.zones === "accessibility" && access.data) {
      const a = access.data;
      const delta = a.est_jobs_share_delta;
      if (view === "change" && delta) {
        return {
          values: a.h3_cell.map((h3, i) => ({ h3, value: delta[i]! })),
          info: a.fields.est_jobs_share_delta,
          delta: true,
        };
      }
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
  }, [layers.zones, access.data, zones.data, view]);

  const crowdValues = useMemo((): PairValue[] | null => {
    const c = crowding.data;
    if (!c) return null;
    return pairValues(
      c.pairs,
      c.passengers.map((_, i) => i),
      c.passengers,
      c.load_factor,
    );
  }, [crowding.data]);
  const flowFrames = useMemo((): PairValue[][] | null => {
    const f = flows.data;
    if (!f) return null;
    const frames: PairValue[][] = f.frames.map(() => []);
    pairValues(f.pairs, f.pair_idx, f.passengers, f.load_factor).forEach((v, i) =>
      frames[f.frame_idx[i]!]!.push(v),
    );
    return frames;
  }, [flows.data]);
  const shownFrame = flowFrames ? Math.min(frame, flowFrames.length - 1) : 0;

  const pickedKeys = useMemo(() => new Set(picked.map(stopKey)), [picked]);
  const deckLayers = useMemo(() => {
    const out: Layer[] = [];
    if (zoneData) {
      out.push(
        zoneData.delta
          ? deltaZoneLayer(zoneData.values)
          : zoneLayer(`zones-${layers.zones}`, zoneData.values),
      );
    }
    if (layers.network && network.data) out.push(networkLayer(network.data));
    if (layers.loads === "crowding" && crowdValues) out.push(loadLayer("crowding", crowdValues));
    if (layers.loads === "flows" && flowFrames) {
      out.push(loadLayer("flows", flowFrames[shownFrame] ?? []));
    }
    if (view !== "baseline" && changes.data) out.push(changesLayer(changes.data.routes));
    if (route.data && selectedRoute !== null) out.push(routeLayer(route.data.features));
    if (showStops && stops.data) out.push(stopsLayer(stops.data.features, pickedKeys));
    if (picked.length) out.push(draftLayer(picked.map((s) => s.geometry.coordinates)));
    return out;
  }, [
    zoneData,
    layers,
    crowdValues,
    flowFrames,
    shownFrame,
    view,
    changes.data,
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
        const text = zoneData?.delta
          ? formatDelta(z.value, zoneInfo.unit)
          : format(z.value, zoneInfo.unit);
        return `${text} (${zoneInfo.nature})`;
      }
      if (id === "crowding" || id === "flows") {
        const v = info.object as PairValue;
        return `${format(v.passengers, "count")} passengers, ${format(v.loadFactor, "ratio")}× design capacity (Simulated)`;
      }
      if (id === "changes") {
        const c = info.object as { name: string; kind: string };
        return `${c.name}: ${c.kind}`;
      }
      return null;
    },
    [zoneInfo, zoneData?.delta],
  );

  const [focus, setFocus] = useState<Focus | null>(null);
  // Everything a scenario changed, to fly to: the story is local (docs/demo.md step 5).
  const changedBox = useMemo((): Focus["bbox"] | null => {
    const points = (changes.data?.routes ?? []).flatMap((r) => r.coordinates.flat());
    if (view === "baseline" || points.length === 0) return null;
    const lng = points.map((p) => p[0]);
    const lat = points.map((p) => p[1]);
    return [Math.min(...lng), Math.min(...lat), Math.max(...lng), Math.max(...lat)];
  }, [changes.data, view]);

  const size = useMemo((): NetworkSize | null => {
    if (!routes.data) return null;
    return {
      routes: routes.data.routes.length,
      stops: stops.data ? stops.data.features.filter((f) => !f.properties.station).length : null,
      windowTrips: routes.data.routes.reduce((sum, r) => sum + r.window_trips, 0),
      windowTripsInfo: routes.data.fields.window_trips,
    };
  }, [routes.data, stops.data]);

  if (detail.error) return <Message text={detail.error.message} />;
  if (!detail.data) return <Message text="Loading…" />;
  const c = detail.data;
  const attribution = `Data: ${[...new Set(c.sources.map((s) => `${s.source} (${s.license})`))].join(", ")}`;
  const current = MODES.find((m) => m.id === mode)!;
  const VIEW_NAME = { baseline: "Baseline", scenario: "Scenario", change: "Change" } as const;
  const showing = result ? `${VIEW_NAME[view]} · ${result.label}` : "Baseline";

  const dockTabs: DockTab[] = [
    {
      id: "runs",
      label: "Runs",
      content: simulation ? (
        <SimulationStatus
          id={simulation}
          onShowResult={(choice) => {
            setResult(choice);
            setMode("compare");
          }}
        />
      ) : (
        <p className="note">
          No simulation started yet. Save a scenario in Design and press Simulate; its progress
          shows here.
        </p>
      ),
    },
  ];
  if (layers.loads === "flows" && flows.data) {
    dockTabs.push({
      id: "flows",
      label: "Flow playback",
      hint: flows.data.frames[shownFrame]?.start,
      content: (
        <Playback
          flows={flows.data}
          frame={shownFrame}
          onFrame={setFrame}
          playing={playing}
          onPlaying={setPlaying}
        />
      ),
    });
  }

  return (
    <div className="app" data-mode={mode} data-inspector={inspectorOpen ? "open" : "closed"}>
      <Rail
        mode={mode}
        onMode={setMode}
        status={[{ label: "API", state: "ok", detail: `serving ${c.name}` }]}
      />
      <aside className="side" aria-label={current.title}>
        <header className="side-head">
          <h2>{current.label}</h2>
          <p>{current.summary}</p>
        </header>
        <div hidden={mode !== "compare"}>
          <ResultPicker city={city} value={result} onChange={setResult} />
        </div>
        <div hidden={mode === "design"}>
          <LayerPanel
            hasResult={result !== null}
            state={layers}
            onChange={(next) => {
              if (next.loads === "flows" && layers.loads !== "flows") openDock("flows");
              setLayers(next);
            }}
            percentiles={c.accessibility.percentiles}
            thresholds={c.accessibility.thresholds_min}
          />
        </div>
        <div hidden={mode !== "design"}>
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
              onSimulation={(id) => {
                setSimulation(id);
                openDock("runs");
              }}
            />
          ) : (
            <p className="note">Loading routes…</p>
          )}
        </div>
      </aside>
      <main className="stage">
        <Masthead
          city={c}
          size={size}
          inspectorOpen={inspectorOpen}
          onInspector={setInspectorOpen}
        />
        <section className="map" aria-label="Map">
          <MapView
            bbox={c.bbox}
            layers={deckLayers}
            attribution={attribution}
            onClick={onClick}
            getTooltip={getTooltip}
            focus={focus}
            controls={
              changedBox && (
                <button
                  type="button"
                  aria-label="Fit the changed routes"
                  title="Fit the changed routes"
                  onClick={() => setFocus({ id: `changes-${Date.now()}`, bbox: changedBox })}
                >
                  <svg viewBox="0 0 14 14" aria-hidden="true">
                    <path d="M1.5 5V1.5H5M9 1.5h3.5V5M12.5 9v3.5H9M5 12.5H1.5V9" />
                    <circle cx="7" cy="7" r="1.6" />
                  </svg>
                </button>
              )
            }
          />
          <p className="map-showing" aria-live="polite">
            <span>Map shows</span> {showing}
          </p>
          <MapLegend state={layers} view={view} legend={legend} />
        </section>
        <Dock
          tabs={dockTabs}
          active={dockTab}
          open={dockOpen}
          onActive={setDockTab}
          onOpen={setDockOpen}
        />
      </main>
      <aside className="inspector" aria-label="Inspector" hidden={!inspectorOpen}>
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
        {mode === "compare" && result && <ComparePanel city={city} result={result.key} />}
        {layers.loads !== "none" && checks.data && <ModelChecks checks={checks.data} />}
        {!selection && selectedRoute === null && !(mode === "compare" && result) && (
          <p className="note inspector-empty">
            Click a zone, stop or segment on the map to see its values here.
          </p>
        )}
      </aside>
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
