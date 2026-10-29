// Step 2 of the Easy view: a what-if question. Questions the model has already answered come
// first; a new one (one bus route, more often, less often or gone) runs the whole model.

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  useResults,
  useRoutes,
  useSaveScenario,
  useScenarios,
  useSimulation,
  useSimulations,
  useStartSimulation,
} from "../api/queries";
import type { CityDetail, Mutation, RouteSummary, Simulation } from "../api/types";
import { comparableResults, type ResultChoice } from "../compare/results";
import { duration, isActive } from "../runs/runs";
import { NatureBadge } from "../ui/Quantity";
import type { Place } from "./Easy";

interface Props {
  city: CityDetail;
  place: Place | null;
  onAsk: (choice: ResultChoice) => void;
  onBack: () => void;
}

export function QuestionStep({ city, place, onAsk, onBack }: Props) {
  const results = useResults(city.id);
  const ready = useMemo(
    () => comparableResults(results.data ?? []).filter((r) => r.latest),
    [results.data],
  );
  return (
    <section className="easy-step" aria-labelledby="question-title">
      <p className="kicker">Step 2 of 3</p>
      <h1 id="question-title" className="easy-title">
        What would you like to test?
      </h1>
      <p className="easy-lede">
        {place
          ? `Pick a change. We'll show what it does for trips from ${place.label}, and for the whole city.`
          : "Pick a change. We'll show what it does for the whole city."}
      </p>

      {results.isLoading && <p className="note">Loading the questions already answered…</p>}
      {ready.length > 0 && (
        <ul className="questions">
          {ready.map((r, i) => (
            <li key={r.key} className="rise" style={{ "--i": i } as React.CSSProperties}>
              <button type="button" className="question" onClick={() => onAsk(r)}>
                <span className="q-title">{r.label}</span>
                <span className="q-meta">Answer ready · run {r.finishedAt}</span>
                <span className="q-go" aria-hidden="true">
                  →
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {results.data && ready.length === 0 && (
        <p className="note">No questions have been answered yet. Ask your own below.</p>
      )}

      <OwnChange city={city} onAnswer={onAsk} />

      <div className="easy-actions">
        <button type="button" className="link" onClick={onBack}>
          ← Back to the place
        </button>
      </div>
    </section>
  );
}

type Action = "more" | "less" | "remove";

const ACTIONS: { id: Action; label: string; words: string }[] = [
  { id: "more", label: "Twice as often", words: "twice as often" },
  { id: "less", label: "Half as often", words: "half as often" },
  { id: "remove", label: "Take it away", words: "taken away" },
];

function mutation(route: RouteSummary, action: Action): Mutation {
  const ref = { route_id: route.route_id, feed: route.feed };
  if (action === "remove") return { type: "remove_route", ...ref };
  return { type: "modify_headway", ...ref, headway_factor: action === "more" ? 0.5 : 2 };
}

const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

const routeName = (r: RouteSummary) => r.short_name ?? r.long_name ?? r.route_id;

/** One route, one change, run through the whole model. */
function OwnChange({ city, onAnswer }: { city: CityDetail; onAnswer: Props["onAsk"] }) {
  const cityId = city.id;
  const routes = useRoutes(cityId);
  const scenarios = useScenarios(cityId);
  const simulations = useSimulations(cityId);
  const save = useSaveScenario(cityId);
  const start = useStartSimulation(cityId);
  const [text, setText] = useState("");
  const [route, setRoute] = useState<RouteSummary | null>(null);
  const [action, setAction] = useState<Action>("more");
  const [running, setRunning] = useState<{ id: string; title: string } | null>(null);

  const matches = useMemo(() => {
    const q = text.trim().toLowerCase();
    if (q.length < 1 || route) return [];
    return (routes.data?.routes ?? [])
      .filter((r) => r.mode === "bus" && r.window_trips > 0)
      .filter((r) => `${r.short_name ?? ""} ${r.long_name ?? ""}`.toLowerCase().includes(q))
      .sort(
        (a, b) =>
          Number(!(a.short_name ?? "").toLowerCase().startsWith(q)) -
            Number(!(b.short_name ?? "").toLowerCase().startsWith(q)) ||
          b.window_trips - a.window_trips,
      )
      .slice(0, 8);
  }, [text, route, routes.data]);

  // How long earlier full runs took, as recorded: the honest answer to "how long will this be".
  const took = useMemo(() => {
    const done = (simulations.data ?? []).filter(
      (s) => s.status === "completed" && !s.cached && s.started_at && s.finished_at,
    );
    const spans = done.map((s) => Date.parse(s.finished_at!) - Date.parse(s.started_at!));
    if (!spans.length) return null;
    const i = spans.indexOf(Math.min(...spans));
    const j = spans.indexOf(Math.max(...spans));
    return {
      shortest: duration(done[i]!.started_at!, done[i]!.finished_at!),
      longest: duration(done[j]!.started_at!, done[j]!.finished_at!),
    };
  }, [simulations.data]);

  const ask = async () => {
    if (!route) return;
    const words = ACTIONS.find((a) => a.id === action)!.words;
    const id = `easy-${slug(routeName(route))}-${slug(route.route_id)}-${action}`;
    const title = `${routeName(route)} ${words}`;
    const active = (simulations.data ?? []).find((s) => isActive(s) && s.scenario_id === id);
    if (active) {
      setRunning({ id: active.id, title });
      return;
    }
    const exists = (scenarios.data ?? []).some((s) => s.scenario_id === id);
    await save.mutateAsync({
      scenario: {
        schema_version: 1,
        scenario_id: id,
        title,
        description: `Made in the Easy view: route ${routeName(route)} (${route.long_name ?? route.route_id}) ${words}.`,
        mutations: [mutation(route, action)],
      },
      exists,
    });
    const job = await start.mutateAsync(id);
    setRunning({ id: job.job_id, title });
  };

  const error = save.error ?? start.error;
  return (
    <details className="own" open={running !== null || undefined}>
      <summary>Or ask your own: change one bus route</summary>
      {running ? (
        <RunProgress id={running.id} title={running.title} onDone={onAnswer} />
      ) : (
        <div className="own-body">
          <label className="field">
            <span>Bus route</span>
            {route ? (
              <span className="chosen">
                <strong>{routeName(route)}</strong> {route.long_name}
                <button
                  type="button"
                  className="link"
                  onClick={() => {
                    setRoute(null);
                    setText("");
                  }}
                >
                  change
                </button>
              </span>
            ) : (
              <input
                type="search"
                placeholder={routes.data ? "Route number, e.g. 500-D" : "Loading routes…"}
                disabled={!routes.data}
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
            )}
          </label>
          {matches.length > 0 && (
            <ul className="search-list inline">
              {matches.map((r) => (
                <li key={r.route_idx}>
                  <button type="button" onClick={() => setRoute(r)}>
                    <strong>{routeName(r)}</strong>
                    <span className="muted">{r.long_name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <fieldset className="choices">
            <legend>Make it run</legend>
            {ACTIONS.map((a) => (
              <label key={a.id} className="choice">
                <input
                  type="radio"
                  name="easy-action"
                  checked={action === a.id}
                  onChange={() => setAction(a.id)}
                />
                <span>{a.label}</span>
              </label>
            ))}
          </fieldset>
          <p className="note">
            This runs the whole city model again
            {took
              ? `: full runs on this computer have taken ${took.shortest === took.longest ? took.shortest : `${took.shortest} to ${took.longest}`}.`
              : "; it can take several minutes."}{" "}
            You can keep exploring while it works.
          </p>
          <button
            type="button"
            className="primary big"
            disabled={!route || save.isPending || start.isPending}
            onClick={() => void ask()}
          >
            Run the model
          </button>
          {error && <p className="error">{error.message}</p>}
        </div>
      )}
    </details>
  );
}

function RunProgress(props: { id: string; title: string; onDone: (c: ResultChoice) => void }) {
  const { id, title, onDone } = props;
  const sim = useSimulation(id).data;
  const client = useQueryClient();
  useEffect(() => {
    if (sim?.status === "completed" && sim.result_key) {
      void client.invalidateQueries({ queryKey: ["results"] });
      onDone({ key: sim.result_key, label: title });
    }
  }, [sim, client, onDone, title]);
  if (!sim) return <p className="note">Sending the question to the model…</p>;
  return <Progress sim={sim} />;
}

function Progress({ sim }: { sim: Simulation }) {
  const { stages, stage_index: at, message, done, total } = sim.progress;
  if (sim.status === "failed") return <p className="error">The run failed: {sim.error}</p>;
  if (sim.status === "cancelled") return <p className="note">The run was cancelled.</p>;
  const share =
    stages.length && at !== null ? (at + (done && total ? done / total : 0)) / stages.length : 0;
  return (
    <div className="progress" role="status">
      <p className="plain">
        {sim.status === "queued"
          ? "Waiting for the model to be free…"
          : `Working: ${message ?? stages[at ?? 0] ?? "starting"}`}
      </p>
      <div className="bar" aria-hidden="true">
        <span style={{ width: `${Math.round(share * 100)}%` }} />
      </div>
      {at !== null && (
        <p className="note">
          Stage {at + 1} of {stages.length}. Results are <NatureBadge nature="simulated" />.
        </p>
      )}
    </div>
  );
}
