// One simulation in detail (PRD §45): its stages as a track, chunk progress when the worker
// reports it, the recorded times, the error if it failed, and cancel or show results.

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { useCancelSimulation, useSimulation } from "../api/queries";
import type { ResultChoice } from "../compare/results";
import { clock, duration } from "../runs/runs";

interface Props {
  id: string;
  onShowResult?: (choice: ResultChoice) => void;
}

export function SimulationStatus({ id, onShowResult }: Props) {
  const { data: sim, error } = useSimulation(id);
  const cancel = useCancelSimulation();
  const client = useQueryClient();
  const finished = sim?.status === "completed";
  // A finished run joins the list of results to compare with.
  useEffect(() => {
    if (finished) void client.invalidateQueries({ queryKey: ["results"] });
  }, [finished, client]);
  if (error) return <p className="error">{error.message}</p>;
  if (!sim) return <p className="note">Queuing…</p>;
  const { progress } = sim;
  const step = progress.stage_index === null ? 0 : progress.stage_index + 1;
  const running = sim.status === "queued" || sim.status === "running";
  const at = progress.stage_index ?? -1;
  return (
    <div className="card run-detail" aria-label="Simulation" role="status">
      <p className="run-head">
        <span className={`run-status run-${sim.status}`}>{sim.status}</span>{" "}
        <strong>{sim.scenario_id}</strong> <span className="mono muted">{sim.id}</span>
        {sim.cached ? <span className="run-tag">reused an earlier identical run</span> : null}
      </p>
      {progress.stages.length > 0 && (
        <ol className="stage-track" aria-label="Stages">
          {progress.stages.map((name, i) => (
            <li
              key={name}
              data-state={
                i < at || (i === at && sim.status === "completed")
                  ? "done"
                  : i === at && running
                    ? "now"
                    : "todo"
              }
            >
              {name}
            </li>
          ))}
        </ol>
      )}
      {sim.status === "running" && (
        <>
          <p>
            Stage {step} of {progress.stages.length}: {progress.message ?? progress.stage}
          </p>
          {progress.total !== null && progress.done !== null && (
            <progress
              max={progress.total}
              value={progress.done}
              aria-label={`${progress.stage} progress`}
            />
          )}
        </>
      )}
      <p className="run-times mono">
        queued {clock(sim.created_at)}
        {sim.started_at && ` · started ${clock(sim.started_at)}`}
        {sim.started_at &&
          sim.finished_at &&
          ` · took ${duration(sim.started_at, sim.finished_at)}`}
      </p>
      {sim.error && <pre className="error">{sim.error}</pre>}
      <div className="run-actions">
        {running && (
          <button type="button" disabled={cancel.isPending} onClick={() => cancel.mutate(sim.id)}>
            Cancel
          </button>
        )}
        {sim.status === "completed" && sim.result_key && onShowResult && (
          <button
            type="button"
            className="primary"
            onClick={() => onShowResult({ key: sim.result_key!, label: sim.scenario_id })}
          >
            Show results
          </button>
        )}
      </div>
    </div>
  );
}
