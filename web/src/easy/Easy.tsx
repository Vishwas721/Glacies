// The Easy view (ADR 0024): one story in three steps, for someone who has never used a
// transport model. Pick a place and see where you can get to; pick a what-if question; read
// who wins and who loses, for you and for the city. The map shows only what the step is about.

import type { Layer } from "@deck.gl/core";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import { LineLayer, ScatterplotLayer } from "@deck.gl/layers";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  useAccessibility,
  useChanges,
  useCities,
  useCity,
  useMetrics,
  useNetwork,
  useReach,
  useResults,
  useStops,
  useZones,
} from "../api/queries";
import type { CityDetail, LonLat, SegmentFeature } from "../api/types";
import { changesLayer, deltaZoneLayer, GAIN, LOSS } from "../compare/layers";
import { comparableResults, type ResultChoice } from "../compare/results";
import { INK, toCss, viridis } from "../map/colours";
import { type Focus, MapView } from "../map/MapView";
import { matches, PHONE } from "../shell/media";
import { PageLink, ThemeToggle, Wordmark } from "../ui/chrome";
import { useTheme } from "../ui/theme";
import { Answer } from "./Answer";
import {
  BAND_COLOUR,
  BANDS,
  band,
  boundsOf,
  type NamedStop,
  namedStops,
  nearestStop,
  within,
  zoneAt,
  zoneCentre,
} from "./place";
import { PlaceStep } from "./PlaceStep";
import { QuestionStep } from "./QuestionStep";

export interface Place {
  zone: string;
  at: LonLat;
  /** What to call it: the stop picked, or "near" the closest stop to a tapped point. */
  label: string;
  nearest: { name: string; metres: number } | null;
}

export type Step = 1 | 2 | 3;

function placeOf(zone: string, at: LonLat, stops: NamedStop[], label?: string): Place {
  const near = nearestStop(stops, at);
  return {
    zone,
    at,
    label: label ?? (near ? `near ${near.stop.name}` : "the place you picked"),
    nearest: near ? { name: near.stop.name, metres: near.metres } : null,
  };
}

function readUrl(): { step: Step; zone: string | null; result: string | null } {
  const q = new URLSearchParams(window.location.search);
  const step = Number(q.get("step"));
  return {
    step: step === 2 || step === 3 ? step : 1,
    zone: q.get("zone"),
    result: q.get("result"),
  };
}

/** The step, place and question in the address bar, so a reload or a shared link reopens them. */
function writeUrl(step: Step, place: Place | null, question: ResultChoice | null) {
  const url = new URL(window.location.href);
  url.searchParams.set("step", String(step));
  for (const [key, value] of [
    ["zone", place?.zone],
    ["result", question?.key],
  ] as const) {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  }
  window.history.replaceState(null, "", url);
}

export function Easy() {
  const cities = useCities();
  const requested = new URLSearchParams(window.location.search).get("city");
  const city = requested ?? cities.data?.[0]?.id;
  const detail = useCity(city ?? "");
  if (cities.error || detail.error) {
    return (
      <div className="splash">
        <p className="splash-mark">Glacies</p>
        <p className="message">
          The model is not reachable: {(cities.error ?? detail.error)?.message}
        </p>
      </div>
    );
  }
  if (!detail.data) {
    return (
      <div className="splash">
        <p className="splash-mark">Glacies</p>
        <p className="message">Loading…</p>
      </div>
    );
  }
  return <EasyView city={detail.data} />;
}

function EasyView({ city }: { city: CityDetail }) {
  const theme = useTheme();
  const [asked] = useState(readUrl);
  const [askedStep, setStep] = useState<Step>(asked.step);
  // Undefined until the viewer chooses: until then the address bar's choice stands.
  const [chosenPlace, setPlace] = useState<Place | null | undefined>(undefined);
  const [chosenQuestion, setQuestion] = useState<ResultChoice | null | undefined>(undefined);

  const stops = useStops(city.id);
  const zones = useZones(city.id);
  const network = useNetwork(city.id);
  const results = useResults(city.id);
  const named = useMemo(() => namedStops(stops.data?.features ?? []), [stops.data]);
  const resolution = zones.data?.resolution ?? null;

  // A shared link names a zone and a result: they open once the data to name them is here.
  const linkedPlace = useMemo(
    () => (asked.zone && named.length ? placeOf(asked.zone, zoneCentre(asked.zone), named) : null),
    [asked.zone, named],
  );
  const linkedQuestion = useMemo(
    () => comparableResults(results.data ?? []).find((r) => r.key === asked.result) ?? null,
    [asked.result, results.data],
  );
  const place = chosenPlace === undefined ? linkedPlace : chosenPlace;
  const question = chosenQuestion === undefined ? linkedQuestion : chosenQuestion;
  // An answer needs a question: a link to a result that is gone opens the questions instead.
  const step: Step = askedStep === 3 && !question && results.data ? 2 : askedStep;

  const { headline_percentile: percentile, headline_threshold_min: threshold } = city.accessibility;
  const answering = step === 3 && question !== null;
  const baseAccess = useAccessibility(city.id, "baseline", percentile, threshold, place !== null);
  const baseReach = useReach(city.id, "baseline", place?.zone ?? null);
  const scenReach = useReach(city.id, answering ? question.key : null, place?.zone ?? null);
  const scenAccess = useAccessibility(
    city.id,
    question?.key ?? "baseline",
    percentile,
    threshold,
    answering && place === null,
  );
  const changes = useChanges(city.id, answering ? question.key : null);
  const metrics = useMetrics(city.id, answering ? question.key : null);

  const placeAt = useCallback(
    (at: LonLat, label?: string) => {
      if (resolution === null) return;
      setPlace(placeOf(zoneAt(at, resolution), at, named, label));
      if (step === 2) setStep(1);
    },
    [named, resolution, step],
  );

  useEffect(() => writeUrl(step, place, question), [step, place, question]);

  const reach45 = useMemo(
    () => (baseReach.data ? within(baseReach.data.h3_cell, baseReach.data.minutes, 45) : null),
    [baseReach.data],
  );
  const scen45 = useMemo(
    () => (scenReach.data ? within(scenReach.data.h3_cell, scenReach.data.minutes, 45) : null),
    [scenReach.data],
  );

  // The camera follows the story: to the place and what it reaches, then to what changed.
  const padding = useMemo(
    () =>
      matches(PHONE)
        ? { top: 70, bottom: Math.round(window.innerHeight * 0.5), left: 24, right: 24 }
        : { top: 90, bottom: 50, left: 480, right: 60 },
    [],
  );
  const focus = useMemo((): Focus | null => {
    if (answering && changes.data) {
      const lines = changes.data.routes.flatMap((r) => r.coordinates.flat());
      const box = boundsOf(place && scen45 ? scen45 : [], [...lines, ...(place ? [place.at] : [])]);
      return box ? { id: `answer-${question.key}`, bbox: box, maxZoom: 13, padding } : null;
    }
    if (place && reach45 && step !== 3) {
      const box = boundsOf(reach45, [place.at]);
      return box ? { id: `reach-${place.zone}`, bbox: box, maxZoom: 13.5, padding } : null;
    }
    return null;
  }, [answering, changes.data, question, place, scen45, reach45, step, padding]);

  const metroLines = useMemo(
    () => (network.data?.features ?? []).filter((f) => f.properties.modes.includes("metro")),
    [network.data],
  );

  const layers = useMemo((): Layer[] => {
    const ink = INK[theme];
    const out: Layer[] = [];
    if (metroLines.length) {
      out.push(
        new LineLayer<SegmentFeature>({
          id: "metro-lines",
          data: metroLines,
          getSourcePosition: (f) => f.geometry.coordinates[0],
          getTargetPosition: (f) => f.geometry.coordinates[1],
          getColor: [...ink.metro, 150],
          getWidth: 2.5,
          widthUnits: "pixels",
          updateTriggers: { getColor: theme },
        }),
      );
    }
    if (answering && place && reach45 && scen45) {
      const cells = [...new Set([...reach45, ...scen45])].map((h3) => ({
        h3,
        state: reach45.has(h3) ? (scen45.has(h3) ? "both" : "lost") : "gained",
      }));
      out.push(
        new H3HexagonLayer<{ h3: string; state: string }>({
          id: "reach-change",
          data: cells,
          getHexagon: (c) => c.h3,
          getFillColor: (c) =>
            c.state === "gained"
              ? [...GAIN[1]!, 220]
              : c.state === "lost"
                ? [...LOSS[1]!, 220]
                : [...viridis(0.6), 70],
          stroked: false,
          extruded: false,
        }),
      );
    } else if (answering && !place && scenAccess.data?.est_jobs_share_delta) {
      const a = scenAccess.data;
      const delta = a.est_jobs_share_delta!;
      out.push(deltaZoneLayer(a.h3_cell.map((h3, i) => ({ h3, value: delta[i]! }))));
    } else if (place && baseReach.data) {
      const r = baseReach.data;
      const cells = r.h3_cell
        .map((h3, i) => ({ h3, band: band(r.minutes[i]!) }))
        .filter((c): c is { h3: string; band: number } => c.band !== null);
      out.push(
        new H3HexagonLayer<{ h3: string; band: number }>({
          id: "reach",
          data: cells,
          getHexagon: (c) => c.h3,
          getFillColor: (c) => [...BAND_COLOUR[c.band]!, 175],
          stroked: false,
          extruded: false,
        }),
      );
    }
    if (answering && changes.data) out.push(changesLayer(changes.data.routes, undefined, theme));
    if (place) {
      out.push(
        new ScatterplotLayer<LonLat>({
          id: "origin",
          data: [place.at],
          getPosition: (p) => p,
          getRadius: 9,
          radiusUnits: "pixels",
          getFillColor: [...ink.highlight, 255],
          getLineColor: [
            ...(theme === "dark" ? ([6, 9, 13] as const) : ([255, 255, 255] as const)),
            255,
          ],
          lineWidthUnits: "pixels",
          getLineWidth: 3,
          stroked: true,
          updateTriggers: { getFillColor: theme, getLineColor: theme },
        }),
      );
    }
    return out;
  }, [
    theme,
    metroLines,
    answering,
    place,
    reach45,
    scen45,
    scenAccess.data,
    baseReach.data,
    changes.data,
  ]);

  const attribution = `Data: ${[...new Set(city.sources.map((s) => `${s.source} (${s.license})`))].join(", ")}`;
  const access = useMemo(() => {
    const a = baseAccess.data;
    if (!a || !place) return null;
    const i = a.h3_cell.indexOf(place.zone);
    return i < 0
      ? null
      : {
          jobs: a.est_jobs_share[i]!,
          people: a.population_share[i]!,
          info: a.fields,
          threshold: a.threshold_min,
        };
  }, [baseAccess.data, place]);

  return (
    <div className="easy" data-step={step}>
      <div className="easy-map">
        <MapView
          bbox={city.bbox}
          layers={layers}
          attribution={attribution}
          plain
          focus={focus}
          onEmptyClick={step === 2 ? undefined : (at) => placeAt(at)}
        />
      </div>

      <header className="easy-bar">
        <Wordmark />
        <StepTrack step={step} canGo={(s) => s !== 3 || question !== null} onStep={setStep} />
        <nav className="easy-nav" aria-label="Pages">
          <PageLink to="pro">Pro view</PageLink>
          <ThemeToggle />
        </nav>
      </header>

      <main className="easy-panel" aria-live="polite">
        {step === 1 && (
          <PlaceStep
            city={city}
            stops={named}
            place={place}
            reach45={reach45}
            loading={baseReach.isFetching}
            access={access}
            onPick={(stop) => placeAt(stop.position, stop.name)}
            onClear={() => setPlace(null)}
            onNext={() => setStep(2)}
          />
        )}
        {step === 2 && (
          <QuestionStep
            city={city}
            place={place}
            onAsk={(choice) => {
              setQuestion(choice);
              setStep(3);
            }}
            onBack={() => setStep(1)}
          />
        )}
        {step === 3 && question && (
          <Answer
            city={city}
            question={question}
            place={place}
            metrics={metrics.data?.rows ?? null}
            metricsError={metrics.error?.message ?? null}
            changes={changes.data ?? null}
            reach={reach45 && scen45 ? { before: reach45, after: scen45 } : null}
            onAnother={() => setStep(2)}
            onPlace={() => setStep(1)}
          />
        )}
      </main>

      <MapKey step={step} place={place} answering={answering} />
    </div>
  );
}

const STEPS: { n: Step; label: string }[] = [
  { n: 1, label: "Place" },
  { n: 2, label: "Question" },
  { n: 3, label: "Answer" },
];

/** Three stations on a line: where you are in the story; earlier stations take you back. */
function StepTrack(props: { step: Step; canGo: (s: Step) => boolean; onStep: (s: Step) => void }) {
  const { step, canGo, onStep } = props;
  return (
    <ol className="step-track" aria-label="Steps">
      {STEPS.map((s) => (
        <li key={s.n} data-state={s.n < step ? "done" : s.n === step ? "now" : "todo"}>
          <button
            type="button"
            disabled={s.n === step || !canGo(s.n)}
            aria-current={s.n === step ? "step" : undefined}
            onClick={() => onStep(s.n)}
          >
            <span className="track-dot" aria-hidden="true" />
            {s.label}
          </button>
        </li>
      ))}
    </ol>
  );
}

/** A small key in the corner, only for what the map shows at this step. */
function MapKey({
  step,
  place,
  answering,
}: {
  step: Step;
  place: Place | null;
  answering: boolean;
}) {
  const swatch = (rgb: readonly number[]) => ({
    background: toCss(rgb as [number, number, number]),
  });
  if (answering && place) {
    return (
      <aside className="easy-key" aria-label="Map key">
        <p>From your place, within 45 minutes</p>
        <span>
          <i style={swatch(GAIN[1]!)} /> newly within reach
        </span>
        <span>
          <i style={swatch(LOSS[1]!)} /> no longer within reach
        </span>
        <span>
          <i className="faint" style={swatch(viridis(0.6))} /> within reach either way
        </span>
      </aside>
    );
  }
  if (answering) {
    return (
      <aside className="easy-key" aria-label="Map key">
        <p>Areas reaching estimated jobs within 45 minutes</p>
        <span>
          <i style={swatch(GAIN[1]!)} /> can reach more
        </span>
        <span>
          <i style={swatch(LOSS[1]!)} /> can reach fewer
        </span>
      </aside>
    );
  }
  if (place && step !== 3) {
    return (
      <aside className="easy-key" aria-label="Map key">
        <p>Door to door, typical morning</p>
        {BANDS.map((top, i) => (
          <span key={top}>
            <i style={swatch(BAND_COLOUR[i]!)} /> {i === 0 ? "under" : `${BANDS[i - 1]}–`}
            {top} min
          </span>
        ))}
      </aside>
    );
  }
  return null;
}
