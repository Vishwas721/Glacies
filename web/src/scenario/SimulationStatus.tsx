// Progress of a queued or running simulation, with cancel (PRD §45).

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { useCancelSimulation, useSimulation } from "../api/queries";
import type { ResultChoice } from "../compare/results";

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
  return (
    <div className="card" aria-label="Simulation" role="status">
      <p>
        <strong>{sim.scenario_id}</strong>: {sim.status}
        {sim.cached ? " (reused an earlier identical run)" : ""}
      </p>
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
      {sim.error && <pre className="error">{sim.error}</pre>}
      {running && (
        <button type="button" disabled={cancel.isPending} onClick={() => cancel.mutate(sim.id)}>
          Cancel
        </button>
      )}
      {sim.status === "completed" && sim.result_key && onShowResult && (
        <button
          type="button"
          onClick={() => onShowResult({ key: sim.result_key!, label: sim.scenario_id })}
        >
          Show results
        </button>
      )}
    </div>
  );
}
