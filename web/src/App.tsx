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
  useResults,
  useRoute,
  useRouteDetails,
  useRoutes,
  useSimulations,
  useStops,
  useZones,
} from "./api/queries";
import type { Crowding, FieldInfo, SegmentFeature, StopFeature } from "./api/types";
import { ComparePanel } from "./compare/ComparePanel";
import {
  type ChangeLine,
  changeLinesLayer,
  changesLayer,
  deltaZoneLayer,
  loadLayer,
  type PairValue,
  pairValues,
} from "./compare/layers";
import { ModelChecks } from "./compare/ModelChecks";
import { Playback } from "./compare/Playback";
import { ResultPicker } from "./compare/ResultPicker";
import { comparableResults, type ResultChoice } from "./compare/results";
import { LayerPanel } from "./map/LayerPanel";
import { INITIAL_LAYERS, type LayerState, type Legend } from "./map/layerState";
import {
  draftLayer,
  networkLayer,
  type ClipBox,
  routeLayer,
  stopKey,
  stopsLayer,
  type ZoneValue,
  zoneLayer,
} from "./map/layers";
import { MapLegend } from "./map/MapLegend";
import { type Focus, type Lens, MapView } from "./map/MapView";
import { upperBound } from "./map/colours";
import { emptyDraft, type Draft } from "./scenario/draft";
import { draftLines, draftRouteIdx } from "./scenario/proposal";
import {
  ChangeCard,
  RouteCard,
  SegmentCard,
  type Selection,
  StopCard,
  ZoneCard,
  type ZoneFact,
  type ZoneFacts,
} from "./inspect/Inspector";
import { Reading } from "./inspect/Reading";
import { ScenarioBuilder } from "./scenario/ScenarioBuilder";
import { ModelSettings, NatureKey, Outputs, Sources } from "./data/DataPanel";
import { RunConsole } from "./runs/RunConsole";
import { isActive } from "./runs/runs";
import { Dock, type DockTab } from "./shell/Dock";
import { Masthead, type NetworkSize } from "./shell/Masthead";
import { initialMode, type Mode, MODES, rememberMode } from "./shell/modes";
import { matches, NARROW, PHONE, useMedia } from "./shell/media";
import { Rail } from "./shell/Rail";
import { format, formatDelta } from "./ui/format";

const ZONE_NAME = {
  population: "residents",
  employment: "estimated employment",
  accessibility: "estimated jobs within reach",
} as const;

const VIEW_NAME = {
  baseline: "Baseline",
  scenario: "Scenario",
  change: "Change",
  split: "Baseline | Scenario",
} as const;

function crowdPairs(c: Crowding | undefined): PairValue[] | null {
  if (!c) return null;
  return pairValues(
    c.pairs,
    c.passengers.map((_, i) => i),
    c.passengers,
    c.load_factor,
  );
}

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
  // Below 1280 px the inspector opens over the map, so it starts closed there.
  const [inspectorOpen, setInspectorOpen] = useState(() => !matches(NARROW));
  // On a phone the map comes first; the panel opens from the tab bar.
  const [sideOpen, setSideOpen] = useState(() => !matches(PHONE));
  const phone = useMedia(PHONE);
  const [dockOpen, setDockOpen] = useState(false);
  const [dockTab, setDockTab] = useState<string | null>(null);
  const [simulation, setSimulation] = useState<string | null>(null);
  const setMode = (next: Mode) => {
    setModeState(next);
    rememberMode(next);
    setSideOpen(true);
    // On a phone the two panels share the bottom of the screen: one at a time.
    if (matches(PHONE)) setInspectorOpen(false);
  };
  /** A chosen result opens the inspector, where its ledger is: closed, it would hide it. */
  const showResult = (choice: ResultChoice | null) => {
    setResult(choice);
    if (choice) {
      setInspectorOpen(true);
      if (matches(PHONE)) setSideOpen(false);
    }
  };
  /** Selecting something on the map opens the inspector to show it. */
  const select = useCallback((next: Selection | null) => {
    setSelection(next);
    if (next) {
      setInspectorOpen(true);
      if (matches(PHONE)) setSideOpen(false);
    }
  }, []);
  const openDock = (tab: string) => {
    setDockTab(tab);
    setDockOpen(true);
  };
  // A result is only drawn in Compare: Explore is the baseline, Design the baseline and draft.
  const view = result && mode === "compare" ? layers.view : "baseline";
  const resultRef = result && view !== "baseline" ? result.key : "baseline";
  // The What-If Lens: baseline left of the divider, scenario right of it.
  const split = view === "split";
  const [lensFraction, setLensFraction] = useState(0.5);
  const [lensLng, setLensLng] = useState<number | null>(null);

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
  const baseAccess = useAccessibility(
    city,
    "baseline",
    layers.percentile,
    layers.thresholdMin,
    split && layers.zones === "accessibility",
  );
  const baseCrowding = useCrowding(city, "baseline", split && layers.loads === "crowding");
  const flows = useFlows(city, resultRef, layers.loads === "flows");
  const changes = useChanges(city, result?.key ?? null);
  const simulations = useSimulations(city);
  const results = useResults(city);
  const checks = useChecks(city, resultRef, layers.loads !== "none");

  // The zone values and their label for the layer chosen.
  const zoneData = useMemo((): {
    values: ZoneValue[];
    info: FieldInfo | undefined;
    delta?: boolean;
    /** In the lens, the baseline values drawn left of the divider. */
    baseline?: ZoneValue[];
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
      const b = baseAccess.data;
      return {
        values: a.h3_cell.map((h3, i) => ({ h3, value: a.est_jobs_share[i]! })),
        info: a.fields.est_jobs_share,
        ...(split && b
          ? { baseline: b.h3_cell.map((h3, i) => ({ h3, value: b.est_jobs_share[i]! })) }
          : {}),
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
  }, [layers.zones, access.data, baseAccess.data, zones.data, view, split]);

  const crowdValues = useMemo(() => crowdPairs(crowding.data), [crowding.data]);
  const baseCrowdValues = useMemo(
    () => (split ? crowdPairs(baseCrowding.data) : null),
    [split, baseCrowding.data],
  );
  const lensCentre = lensLng ?? (detail.data ? (detail.data.bbox[0] + detail.data.bbox[2]) / 2 : 0);

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
  // The draft scenario on the map while it is being designed, before any simulation.
  const draftIdx = useMemo(
    () => draftRouteIdx(draft, routes.data?.routes ?? []),
    [draft, routes.data],
  );
  const draftDetails = useRouteDetails(city, draftIdx);
  const stopCoords = useMemo(
    () =>
      new Map(
        (stops.data?.features ?? []).map((f) => [
          `${f.properties.feed}:${f.properties.stop_id}`,
          f.geometry.coordinates,
        ]),
      ),
    [stops.data],
  );
  const proposal = useMemo(
    () => (mode === "design" ? draftLines(draft, draftDetails, stopCoords) : []),
    [mode, draft, draftDetails, stopCoords],
  );
  // Relief raises levels only: a raised change map or lens would mislead or break the cut.
  const reliefUsable =
    layers.zones !== "none" && !split && !(view === "change" && layers.zones === "accessibility");
  const relief = layers.relief && reliefUsable;
  const deckLayers = useMemo(() => {
    const out: Layer[] = [];
    const west: ClipBox = [-180, -90, lensCentre, 90];
    const east: ClipBox = [lensCentre, -90, 180, 90];
    // In relief the network goes first: the zones' near-clear low hexagons still fill the depth
    // buffer, and lines drawn after them at ground level would vanish.
    const network_ = layers.network && network.data ? networkLayer(network.data) : null;
    if (relief && network_) out.push(network_);
    if (zoneData?.baseline) {
      // One colour scale for both sides, or equal colours would not mean equal values.
      const top = upperBound(zoneData.baseline.map((v) => v.value));
      out.push(zoneLayer("zones-split-baseline", zoneData.baseline, { top, clip: west }));
      out.push(zoneLayer("zones-split-scenario", zoneData.values, { top, clip: east }));
    } else if (zoneData) {
      out.push(
        zoneData.delta
          ? deltaZoneLayer(zoneData.values)
          : zoneLayer(`zones-${layers.zones}`, zoneData.values, { relief }),
      );
    }
    if (!relief && network_) out.push(network_);
    if (layers.loads === "crowding" && baseCrowdValues && crowdValues) {
      out.push(loadLayer("crowding-baseline", baseCrowdValues, west));
      out.push(loadLayer("crowding", crowdValues, east));
    } else if (layers.loads === "crowding" && crowdValues) {
      out.push(loadLayer("crowding", crowdValues));
    }
    if (layers.loads === "flows" && flowFrames) {
      out.push(loadLayer("flows", flowFrames[shownFrame] ?? []));
    }
    if (view !== "baseline" && changes.data) {
      out.push(changesLayer(changes.data.routes, split ? east : undefined));
    }
    if (proposal.length) out.push(changeLinesLayer("proposal", proposal));
    if (route.data && selectedRoute !== null) out.push(routeLayer(route.data.features));
    if (showStops && stops.data) out.push(stopsLayer(stops.data.features, pickedKeys));
    if (picked.length) out.push(draftLayer(picked.map((s) => s.geometry.coordinates)));
    return out;
  }, [
    zoneData,
    layers,
    crowdValues,
    baseCrowdValues,
    split,
    lensCentre,
    relief,
    proposal,
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
        else select({ kind: "stop", stop });
      } else if (id === "network") {
        select({ kind: "segment", segment: info.object as SegmentFeature });
      } else if (id?.startsWith("zones-")) {
        select({ kind: "zone", h3: (info.object as ZoneValue).h3 });
      } else if (id === "changes") {
        select({ kind: "change", mutationIdx: (info.object as ChangeLine).mutationIdx });
      } else {
        setSelection(null);
      }
    },
    [picking, select],
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
      if (id?.startsWith("crowding") || id === "flows") {
        const v = info.object as PairValue;
        return `${format(v.passengers, "count")} passengers, ${format(v.loadFactor, "ratio")}× design capacity (Simulated)`;
      }
      if (id === "changes" || id === "proposal") {
        const c = info.object as ChangeLine;
        return `${c.name}: ${c.kind}`;
      }
      return null;
    },
    [zoneInfo, zoneData?.delta],
  );

  const [focus, setFocus] = useState<Focus | null>(null);
  const lens = useMemo(
    (): Lens | null =>
      split
        ? {
            fraction: lensFraction,
            onFraction: setLensFraction,
            onLng: setLensLng,
            left: "Baseline",
            right: "Scenario",
          }
        : null,
    [split, lensFraction],
  );
  const [searchSeed, setSearchSeed] = useState<{ text: string; n: number } | undefined>();

  const zoneFacts = useMemo((): ZoneFacts | null => {
    if (selection?.kind !== "zone") return null;
    const h3 = selection.h3;
    const facts: ZoneFact[] = [];
    let edge = false;
    const z = zones.data;
    const zi = z ? z.h3_cell.indexOf(h3) : -1;
    if (z && zi >= 0) {
      facts.push({ label: "Residents", value: z.population[zi]!, info: z.fields.population });
      if (z.est_employment_share) {
        facts.push({
          label: "Share of estimated employment",
          value: z.est_employment_share[zi]!,
          info: z.fields.est_employment_share,
        });
      }
    }
    const a = access.data;
    const ai = a ? a.h3_cell.indexOf(h3) : -1;
    if (a && ai >= 0) {
      const delta = a.est_jobs_share_delta?.[ai];
      // A scenario's accessibility carries the change; the baseline is scenario minus it.
      const withBaseline = (value: number) =>
        delta !== undefined && resultRef !== "baseline" ? { baseline: value - delta } : {};
      facts.push({
        label: `Estimated jobs within ${a.threshold_min} min (p${a.percentile})`,
        value: a.est_jobs_share[ai]!,
        info: a.fields.est_jobs_share,
        ...withBaseline(a.est_jobs_share[ai]!),
      });
      facts.push({
        label: `Population within ${a.threshold_min} min (p${a.percentile})`,
        value: a.population_share[ai]!,
        info: a.fields.population_share,
      });
      edge = a.edge_zone[ai] ?? false;
    }
    return { h3, facts, edge };
  }, [selection, zones.data, access.data, resultRef]);
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
  const showing =
    mode === "design" && proposal.length
      ? `Draft, not simulated · ${draft.title || draft.scenarioId || "untitled"}`
      : result
        ? `${VIEW_NAME[view]} · ${result.label}`
        : "Baseline";

  const active = (simulations.data ?? []).filter(isActive);
  const queue = simulations.error
    ? { label: "Queue", state: "down" as const, detail: simulations.error.message }
    : active.length
      ? { label: "Queue", state: "busy" as const, detail: `${active.length} queued or running` }
      : { label: "Queue", state: "ok" as const, detail: "idle" };

  const dockTabs: DockTab[] = [
    {
      id: "runs",
      label: "Runs",
      hint: active.length ? `${active.length} active` : undefined,
      content: (
        <RunConsole
          city={city}
          current={simulation}
          onCurrent={setSimulation}
          onShowResult={(choice) => {
            // Name the result by its scenario's title once the results list has it.
            const listed = comparableResults(results.data ?? []).find((r) => r.key === choice.key);
            // Mode first: on a phone switching mode closes the inspector showResult opens.
            setMode("compare");
            setLayers({ ...layers, view: "change" });
            showResult(listed ?? choice);
          }}
        />
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
    <div
      className="app"
      data-mode={mode}
      data-inspector={inspectorOpen ? "open" : "closed"}
      data-side={sideOpen ? "open" : "closed"}
    >
      <Rail
        mode={mode}
        onMode={(next) => (next === mode ? setSideOpen(!sideOpen) : setMode(next))}
        status={[{ label: "API", state: "ok", detail: `serving ${c.name}` }, queue]}
      />
      <aside className="side" aria-label={current.title}>
        <header className="side-head">
          <h2>{current.label}</h2>
          <p>{current.summary}</p>
          <button
            type="button"
            className="panel-close"
            aria-label="Close the panel"
            onClick={() => setSideOpen(false)}
          >
            ×
          </button>
        </header>
        <div hidden={mode !== "compare"}>
          <ResultPicker city={city} value={result} onChange={showResult} />
        </div>
        {mode === "data" && (
          <>
            <Sources city={c} />
            <Outputs city={c} />
          </>
        )}
        <div hidden={mode === "design" || mode === "data"}>
          <LayerPanel
            hasResult={result !== null && mode === "compare"}
            state={layers}
            onChange={(next) => {
              if (next.loads === "flows" && layers.loads !== "flows") openDock("flows");
              setLayers(next);
            }}
            percentiles={c.accessibility.percentiles}
            thresholds={c.accessibility.thresholds_min}
          />
        </div>
        {mode === "design" && phone && (
          <p className="card note">
            Building a scenario needs a wider screen, at least 700 px: picking stops and editing
            routes do not fit a phone. Here you can explore, compare results and follow runs.
          </p>
        )}
        <div hidden={mode !== "design" || phone}>
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
              searchSeed={searchSeed}
              activeScenarios={new Set(active.map((s) => s.scenario_id))}
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
            lens={lens}
            tilt={relief}
            controls={
              <>
                <button
                  type="button"
                  aria-label="Relief"
                  aria-pressed={relief}
                  disabled={!reliefUsable}
                  title={
                    reliefUsable
                      ? "Raise zones by their value on a tilted map"
                      : "Relief needs a level layer (not Change or Lens)"
                  }
                  onClick={() => setLayers({ ...layers, relief: !layers.relief })}
                >
                  <svg viewBox="0 0 14 14" aria-hidden="true">
                    <path d="M1 11.5 4.5 6l2.5 3 2-2.5 4 5z" />
                  </svg>
                </button>
                {changedBox && (
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
                )}
              </>
            }
          />
          <p className="map-showing" aria-live="polite">
            <span>Map shows</span> {showing}
          </p>
          <MapLegend
            state={layers}
            view={view}
            legend={legend}
            relief={relief}
            routeChanges={proposal.length > 0 || (view !== "baseline" && Boolean(changes.data))}
          />
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
        <button
          type="button"
          className="panel-close"
          aria-label="Close the inspector"
          onClick={() => setInspectorOpen(false)}
        >
          ×
        </button>
        {mode === "data" && (
          <>
            <NatureKey />
            <ModelSettings city={c} />
          </>
        )}
        {selection?.kind === "zone" && zoneFacts && (
          <ZoneCard zone={zoneFacts} onClose={() => setSelection(null)} />
        )}
        {selection?.kind === "stop" && (
          <StopCard
            stop={selection.stop}
            info={stops.data?.fields.routes}
            onClose={() => setSelection(null)}
          />
        )}
        {selection?.kind === "segment" && (
          <SegmentCard
            segment={selection.segment}
            fields={network.data?.fields}
            window={c.window}
            onClose={() => setSelection(null)}
          />
        )}
        {selection?.kind === "change" &&
          changes.data &&
          (() => {
            const change = changes.data.routes.find(
              (r) => r.mutation_idx === selection.mutationIdx,
            );
            return (
              change && (
                <ChangeCard
                  change={change}
                  fields={changes.data.fields}
                  onClose={() => setSelection(null)}
                />
              )
            );
          })()}
        {route.data && selectedRoute !== null && (
          <RouteCard
            route={route.data}
            onClose={() => setSelectedRoute(null)}
            onEdit={
              mode === "design"
                ? undefined
                : () => {
                    const r = route.data!.route;
                    setSearchSeed({ text: r.short_name ?? r.route_id, n: Date.now() });
                    setMode("design");
                  }
            }
          />
        )}
        {mode === "compare" && result && (
          <ComparePanel city={city} result={result.key} title={result.label} />
        )}
        {layers.loads !== "none" && checks.data && <ModelChecks checks={checks.data} />}
        {!selection &&
          selectedRoute === null &&
          mode !== "data" &&
          !(mode === "compare" && result) && (
            <Reading
              mode={mode}
              zoneLayer={layers.zones === "none" ? null : ZONE_NAME[layers.zones]}
              zoneInfo={zoneInfo}
              window={c.window}
              network={layers.network}
            />
          )}
      </aside>
    </div>
  );
}
