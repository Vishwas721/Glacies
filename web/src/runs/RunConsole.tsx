// The run console in the dock (PRD §45, ADR 0021): the simulation just started, in detail, and
// every run the queue knows for this city, with its real stage, times and outcome. Nothing here
// is estimated: progress is shown only when the worker reports chunk counts.

import type { ResultChoice } from "../compare/results";
import { useSimulations } from "../api/queries";
import { SimulationStatus } from "../scenario/SimulationStatus";
import { clock, duration, stage } from "./runs";

interface Props {
  city: string;
  /** The run started from this screen, shown in full at the top. */
  current: string | null;
  onCurrent: (id: string) => void;
  onShowResult: (choice: ResultChoice) => void;
}

export function RunConsole({ city, current, onCurrent, onShowResult }: Props) {
  const runs = useSimulations(city);
  return (
    <div className="console">
      <div className="console-current">
        {current ? (
          <SimulationStatus id={current} onShowResult={onShowResult} />
        ) : (
          <p className="note">
            No run selected. Save a scenario in Design and press Simulate, or pick a run from the
            list.
          </p>
        )}
      </div>
      <div className="console-list">
        {runs.error ? (
          <p className="error">The simulation queue is not reachable: {runs.error.message}</p>
        ) : (
          <table className="runs" aria-label="Simulation runs">
            <thead>
              <tr>
                <th scope="col">Status</th>
                <th scope="col">Scenario</th>
                <th scope="col">Stage</th>
                <th scope="col">Queued</th>
                <th scope="col">Took</th>
                <th scope="col">Run</th>
              </tr>
            </thead>
            <tbody>
              {(runs.data ?? []).map((s) => (
                <tr
                  key={s.id}
                  aria-selected={s.id === current}
                  onClick={() => onCurrent(s.id)}
                  className="run"
                >
                  <td>
                    <span className={`run-status run-${s.status}`}>{s.status}</span>
                    {s.cached && <span className="run-tag">reused</span>}
                  </td>
                  <td>{s.scenario_id}</td>
                  <td className="muted">{stage(s)}</td>
                  <td className="mono">{clock(s.created_at)}</td>
                  <td className="mono">
                    {s.started_at && s.finished_at ? duration(s.started_at, s.finished_at) : "—"}
                  </td>
                  <td>
                    <button type="button" className="link mono" onClick={() => onCurrent(s.id)}>
                      {s.id}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {runs.data?.length === 0 && <p className="note">No runs yet for this city.</p>}
      </div>
    </div>
  );
}
