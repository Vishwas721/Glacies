// The left panel (PRD §39): load or start a scenario, change routes, add one, save, simulate.

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "../api/client";
import { useSaveScenario, useScenarios, useStartSimulation } from "../api/queries";
import type {
  AddRoute,
  RouteList as RouteListData,
  ScenarioRecord,
  StopFeature,
} from "../api/types";
import { AddRouteForm } from "./AddRouteForm";
import { type Draft, emptyDraft, fromScenario, toScenario } from "./draft";
import { RouteList } from "./RouteList";
import { validateScenario } from "./validate";

interface Props {
  city: string;
  routes: RouteListData;
  draft: Draft;
  onDraftChange: (draft: Draft) => void;
  selectedRoute: number | null;
  onSelectRoute: (routeIdx: number | null) => void;
  picking: boolean;
  onPickingChange: (picking: boolean) => void;
  picked: StopFeature[];
  onPickedChange: (stops: StopFeature[]) => void;
  /** Search the route list for this, e.g. a route chosen on the map. */
  searchSeed?: { text: string; n: number };
  /** Scenarios queued or running now: simulating one again would only queue a duplicate. */
  activeScenarios?: ReadonlySet<string>;
  /** A simulation was queued; its progress shows in the dock. */
  onSimulation: (id: string) => void;
}

export function ScenarioBuilder(props: Props) {
  const { city, routes, draft, onDraftChange } = props;
  const scenarios = useScenarios(city);
  const client = useQueryClient();
  const save = useSaveScenario(city);
  const start = useStartSimulation(city);
  const [problems, setProblems] = useState<string[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [savedAs, setSavedAs] = useState<string | null>(null); // id of the unchanged saved draft

  const change = (next: Draft) => {
    setSavedAs(null);
    onDraftChange(next);
  };

  // Opening fetches the scenario and applies it; repository scenarios become an editable copy.
  const open = async (id: string) => {
    setProblems([]);
    try {
      const record = await client.fetchQuery({
        queryKey: ["scenario", city, id],
        queryFn: () => api<ScenarioRecord>(`/api/cities/${city}/scenarios/${id}`),
      });
      const { draft: next, unsupported } = fromScenario(record.scenario, routes.routes);
      const copy = !record.editable;
      setNotes([
        ...(copy
          ? [
              `${id} is a repository scenario: simulate it as it is, or edit and save your own copy.`,
            ]
          : []),
        ...unsupported.map((u) => `Not editable here, dropped: ${u}`),
      ]);
      onDraftChange(copy ? { ...next, scenarioId: `${next.scenarioId}_copy` } : next);
      // Unedited, the scenario on the server is exactly this one, so it can run as it is.
      setSavedAs(unsupported.length ? null : record.scenario.scenario_id);
    } catch (e) {
      setProblems([e instanceof Error ? e.message : String(e)]);
    }
  };

  const userIds = new Set(
    (scenarios.data ?? []).filter((s) => s.editable).map((s) => s.scenario_id),
  );
  const onSave = () => {
    const scenario = toScenario(draft);
    const found = validateScenario(scenario);
    setProblems(found);
    if (found.length) return;
    save.mutate(
      { scenario, exists: userIds.has(scenario.scenario_id) },
      {
        onSuccess: () => setSavedAs(scenario.scenario_id),
        onError: (e) => setProblems([e instanceof ApiError ? e.message : String(e)]),
      },
    );
  };
  const alreadyRunning = savedAs !== null && (props.activeScenarios?.has(savedAs) ?? false);
  const onSimulate = () => {
    if (!savedAs || alreadyRunning) return;
    start.mutate(savedAs, {
      onSuccess: (r) => props.onSimulation(r.job_id),
      onError: (e) => setProblems([e.message]),
    });
  };

  const setAdded = (added: AddRoute[]) => change({ ...draft, added });
  const changes = draft.removed.length + Object.keys(draft.headway).length + draft.added.length;

  return (
    <div className="builder">
      <section aria-label="Scenario" className="card">
        <label>
          Open{" "}
          <select
            aria-label="Open scenario"
            value=""
            onChange={(e) => e.target.value && void open(e.target.value)}
          >
            <option value="">choose…</option>
            {(scenarios.data ?? []).map((s) => (
              <option key={s.scenario_id} value={s.scenario_id}>
                {s.title} {s.editable ? "" : "(repository)"}
              </option>
            ))}
          </select>
        </label>{" "}
        <button type="button" className="link" onClick={() => change(emptyDraft())}>
          new
        </button>
        <label>
          Id{" "}
          <input
            value={draft.scenarioId}
            placeholder="my_scenario"
            onChange={(e) => change({ ...draft, scenarioId: e.target.value })}
          />
        </label>
        <label>
          Title{" "}
          <input
            value={draft.title}
            onChange={(e) => change({ ...draft, title: e.target.value })}
          />
        </label>
        <label>
          Description{" "}
          <textarea
            value={draft.description}
            onChange={(e) => change({ ...draft, description: e.target.value })}
          />
        </label>
        {notes.map((n) => (
          <p key={n} className="note">
            {n}
          </p>
        ))}
      </section>
      <RouteList
        data={routes}
        draft={draft}
        onChange={change}
        selected={props.selectedRoute}
        onSelect={props.onSelectRoute}
        seed={props.searchSeed}
      />
      <AddRouteForm
        picking={props.picking}
        onPickingChange={props.onPickingChange}
        picked={props.picked}
        onPickedChange={props.onPickedChange}
        added={draft.added}
        onAddedChange={setAdded}
      />
      <section aria-label="Run" className="card run-bar">
        <p className="note">
          {changes} change{changes === 1 ? "" : "s"}
          {savedAs ? `, saved as ${savedAs}` : ", not saved"}
        </p>
        {alreadyRunning && (
          <p className="note">{savedAs} is already queued or running: follow it under Runs.</p>
        )}
        {problems.length > 0 && (
          <ul className="error" aria-label="Problems">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        <button type="button" onClick={onSave} disabled={save.isPending}>
          Save
        </button>{" "}
        <button
          type="button"
          className="primary"
          onClick={onSimulate}
          disabled={!savedAs || start.isPending || alreadyRunning}
        >
          Simulate
        </button>
      </section>
    </div>
  );
}
