// The landing page (ADR 0024): the city's simulated morning rush moving under the question the
// project answers, two ways in (Easy and Pro), how it works drawn as a transit line, the
// network in real numbers, and who it is for and what it is not.

import { TripsLayer } from "@deck.gl/geo-layers";
import type { Layer } from "@deck.gl/core";
import { useEffect, useMemo, useRef, useState } from "react";

import { useCities, useCity, useFlows, useRoutes, useZones } from "../api/queries";
import type { CityDetail } from "../api/types";
import { type Focus, MapView } from "../map/MapView";
import type { RGB } from "../map/colours";
import { Mark, PageLink, ThemeToggle } from "../ui/chrome";
import { NatureBadge, Quantity } from "../ui/Quantity";
import { type Theme, useTheme } from "../ui/theme";
import { clockText, coreBox, type Trails, trailsFromFlows } from "./trips";

/** Simulated seconds per second of animation: the four hours of flows loop in about 40 s. */
const PACE = 360;
const TRAIL_S = 420;

const TRAIL_INK: Record<Theme, { bus: RGB; metro: RGB }> = {
  dark: { bus: [127, 220, 242], metro: [255, 255, 255] },
  light: { bus: [8, 119, 154], metro: [14, 26, 34] },
};

// Additive blending on the dark map: where many trails overlap, the corridor glows.
const GLOW = {
  blend: true,
  blendColorOperation: "add",
  blendColorSrcFactor: "src-alpha",
  blendColorDstFactor: "one",
  blendAlphaOperation: "add",
  blendAlphaSrcFactor: "one",
  blendAlphaDstFactor: "one-minus-src-alpha",
} as const;

function reducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** The clock of the animation: runs while the hero is on screen, stands still otherwise. */
function useClock(range: Trails | null, running: boolean): number {
  const [time, setTime] = useState(0);
  // Seconds into the loop, kept while the hero is off screen so it resumes where it stopped.
  const elapsed = useRef(0);
  const [still] = useState(reducedMotion);
  useEffect(() => {
    if (!range || range.end <= range.start || still || !running) return;
    const span = range.end - range.start;
    let frame = 0;
    let last = performance.now();
    const tick = (stamp: number) => {
      elapsed.current = (elapsed.current + ((stamp - last) / 1000) * PACE) % span;
      last = stamp;
      setTime(range.start + elapsed.current);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [range, running, still]);
  // A still picture for viewers who asked for less motion: the busy middle of the morning.
  if (still && range) return range.start + (range.end - range.start) * 0.4;
  return time;
}

export function Landing() {
  const cities = useCities();
  const requested = new URLSearchParams(window.location.search).get("city");
  const city = requested ?? cities.data?.[0]?.id;
  const detail = useCity(city ?? "");
  if (cities.error) {
    return (
      <div className="splash">
        <p className="splash-mark">Glacies</p>
        <p className="message">The API is not reachable: {cities.error.message}</p>
      </div>
    );
  }
  if (!city || !detail.data) {
    return (
      <div className="splash">
        <p className="splash-mark">Glacies</p>
        <p className="message">Loading…</p>
      </div>
    );
  }
  return <LandingPage city={detail.data} />;
}

function LandingPage({ city }: { city: CityDetail }) {
  const theme = useTheme();
  const flows = useFlows(city.id, "baseline", true);
  const trails = useMemo(() => (flows.data ? trailsFromFlows(flows.data) : null), [flows.data]);
  const hero = useRef<HTMLElement>(null);
  const [onScreen, setOnScreen] = useState(true);
  useEffect(() => {
    const el = hero.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const watch = new IntersectionObserver(([entry]) => setOnScreen(entry?.isIntersecting ?? true));
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  const time = useClock(trails, onScreen);

  const layers = useMemo((): Layer[] => {
    if (!trails) return [];
    const ink = TRAIL_INK[theme];
    return [
      new TripsLayer({
        id: "morning-trails",
        data: trails.trails,
        getPath: (d) => d.path,
        getTimestamps: (d) => d.timestamps,
        getColor: (d) => (d.metro ? ink.metro : ink.bus),
        getWidth: (d) => 1 + Math.sqrt(d.passengers) / 5,
        widthUnits: "pixels",
        widthMaxPixels: 7,
        capRounded: true,
        jointRounded: true,
        fadeTrail: true,
        trailLength: TRAIL_S,
        currentTime: time,
        opacity: theme === "dark" ? 0.8 : 0.9,
        ...(theme === "dark" ? { parameters: GLOW } : {}),
        updateTriggers: { getColor: theme },
      }),
    ];
  }, [trails, time, theme]);

  const attribution = `Data: ${[...new Set(city.sources.map((s) => `${s.source} (${s.license})`))].join(", ")}`;
  // The camera frames where the trails are, right of the headline; the city's box reaches far
  // beyond its network.
  const focus = useMemo((): Focus | null => {
    const box = trails ? coreBox(trails) : null;
    if (!box) return null;
    const wide = window.innerWidth > 900;
    return {
      id: "trails",
      bbox: box,
      maxZoom: 12,
      padding: wide
        ? { top: 90, bottom: 200, left: Math.round(window.innerWidth * 0.45), right: 40 }
        : { top: 260, bottom: 280, left: 20, right: 20 },
    };
  }, [trails]);

  return (
    <div className="landing">
      <header className="landing-bar">
        <span className="wordmark">
          <Mark />
          <span>Glacies</span>
        </span>
        <nav aria-label="Pages">
          <a href="#how">How it works</a>
          <a href="#limits">What it is not</a>
          <PageLink to="easy">Easy view</PageLink>
          <PageLink to="pro">Pro view</PageLink>
          <ThemeToggle />
        </nav>
      </header>

      <section className="hero" ref={hero} aria-label="Introduction">
        <div className="hero-map" aria-hidden="true">
          <MapView
            bbox={city.bbox}
            layers={layers}
            attribution={attribution}
            plain
            interactive={false}
            labels={false}
            focus={focus}
            tilt
          />
        </div>
        <div className="hero-scrim" aria-hidden="true" />
        <div className="hero-copy">
          <p className="kicker">{city.name} · a digital twin of its buses and metro</p>
          <h1 className="display">
            What if your bus came <em>twice as often?</em>
          </h1>
          <p className="lede">
            Glacies is a working copy of {city.name}&rsquo;s public transport. Change a route and it
            works out, for the whole city, who gets there faster, who waits less and who loses out,
            before anything changes on the street.
          </p>
        </div>
        <aside className="hero-clock" aria-label="What the moving lines are">
          <p className="clock">{trails ? clockText(time) : "--:--"}</p>
          <p className="clock-note">
            The morning rush as the model sees it: each trail is passengers on a{" "}
            <span className="key key-bus">bus</span> or a{" "}
            <span className="key key-metro">metro</span> train between two stops.{" "}
            <NatureBadge nature="simulated" />
          </p>
          <p className="clock-note">Timetable of {city.service_date ?? "unknown date"}.</p>
          {flows.error && <p className="clock-note">No simulated flows to show yet.</p>}
        </aside>

        <nav className="doors" aria-label="Choose a view">
          <PageLink to="easy" className="door door-easy">
            <span className="door-label">Easy</span>
            <span className="door-text">
              Pick a place, ask one what-if question, get a plain answer. No settings, no jargon.
            </span>
            <span className="door-go" aria-hidden="true">
              Start here →
            </span>
          </PageLink>
          <span className="seam" aria-hidden="true" />
          <PageLink to="pro" className="door door-pro">
            <span className="door-label">Pro</span>
            <span className="door-text">
              Every layer, the scenario designer, run console, before/after lens and model checks.
            </span>
            <span className="door-go" aria-hidden="true">
              Open the instruments →
            </span>
          </PageLink>
        </nav>
      </section>

      <HowItWorks />
      <Numbers city={city} />
      <ForAndNot />

      <footer className="landing-foot">
        <p>
          Built on open data: {[...new Set(city.sources.map((s) => s.source))].join(" · ")}. Every
          number in the app says whether it is <NatureBadge nature="observed" />,{" "}
          <NatureBadge nature="estimated" />, <NatureBadge nature="simulated" /> or{" "}
          <NatureBadge nature="assumed" />.
        </p>
      </footer>
    </div>
  );
}

const STATIONS: { title: string; text: string }[] = [
  {
    title: "Real timetables",
    text: "Every bus and metro trip in the published timetables, stop by stop.",
  },
  {
    title: "One network",
    text: "Stops, routes and the streets people walk, joined into one map a computer can search.",
  },
  {
    title: "Every journey",
    text: "The fastest way between every pair of areas, for each minute of the morning rush.",
  },
  {
    title: "People",
    text: "Where people live and roughly where jobs are, so it knows who travels where.",
  },
  {
    title: "Your what-if",
    text: "Run a route more often, take one away, or draw a new one.",
  },
  {
    title: "The answer",
    text: "Who gets there faster, who waits less and who loses out, on a map and in plain numbers.",
  },
];

function HowItWorks() {
  const ref = useRef<HTMLOListElement>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const watch = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setSeen(true);
          watch.disconnect();
        }
      },
      { threshold: 0.3 },
    );
    watch.observe(el);
    return () => watch.disconnect();
  }, []);
  return (
    <section className="how" id="how" aria-labelledby="how-title">
      <p className="kicker">How it works</p>
      <h2 id="how-title" className="section-title">
        From a timetable to an answer, in six stops.
      </h2>
      <ol className="line" ref={ref} data-seen={seen}>
        {STATIONS.map((s, i) => (
          <li key={s.title} style={{ "--i": i } as React.CSSProperties}>
            <span className="station" aria-hidden="true" />
            <h3>{s.title}</h3>
            <p>{s.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Numbers({ city }: { city: CityDetail }) {
  const routes = useRoutes(city.id);
  const zones = useZones(city.id);
  const r = routes.data;
  const z = zones.data;
  const residents = z ? z.population.reduce((a, b) => a + b, 0) : null;
  return (
    <section className="numbers" aria-labelledby="numbers-title">
      <p className="kicker">{city.name} in the model</p>
      <h2 id="numbers-title" className="section-title">
        The network it works on.
      </h2>
      <dl className="figures">
        <div>
          <dt>bus and metro routes</dt>
          <dd>{r ? <Quantity value={r.routes.length} nature="observed" unit="count" /> : "…"}</dd>
        </div>
        <div>
          <dt>
            trips starting {city.window[0]}–{city.window[1]}
          </dt>
          <dd>
            {r?.fields.window_trips ? (
              <Quantity
                value={r.routes.reduce((sum, x) => sum + x.window_trips, 0)}
                nature={r.fields.window_trips.nature}
                unit="count"
              />
            ) : (
              "…"
            )}
          </dd>
        </div>
        <div>
          <dt>areas of about 0.7 km²</dt>
          <dd>{z ? <Quantity value={z.h3_cell.length} nature="assumed" unit="count" /> : "…"}</dd>
        </div>
        <div>
          <dt>residents placed on the map</dt>
          <dd>
            {z && residents !== null && z.fields.population ? (
              <Quantity value={residents} nature={z.fields.population.nature} unit="count" />
            ) : (
              "…"
            )}
          </dd>
        </div>
      </dl>
    </section>
  );
}

function ForAndNot() {
  return (
    <section className="for-not" aria-label="Who it is for and what it is not">
      <div>
        <p className="kicker">Who it is for</p>
        <ul>
          <li>
            <strong>Transport planners</strong> testing a proposal before spending on buses and
            drivers.
          </li>
          <li>
            <strong>Researchers and students</strong> finding the areas cut off from jobs.
          </li>
          <li>
            <strong>Civic groups and journalists</strong> backing a demand like &ldquo;our area
            needs a feeder bus&rdquo; with numbers.
          </li>
          <li>
            <strong>Other cities:</strong> nothing is tied to one place; give it another
            city&rsquo;s timetables and it works there.
          </li>
        </ul>
      </div>
      <div id="limits">
        <p className="kicker">What it is not</p>
        <ul>
          <li>
            <strong>Not a forecast.</strong> It compares today with today plus your change, under
            the same assumptions.
          </li>
          <li>
            <strong>No traffic.</strong> Buses keep to their timetable; jams are not modelled.
          </li>
          <li>
            <strong>Mornings only:</strong> the rush hours of one weekday timetable.
          </li>
          <li>
            <strong>Commuters are estimated,</strong> checked against real metro station counts, not
            taken from trip records.
          </li>
        </ul>
      </div>
    </section>
  );
}
