// Aggregate flow playback (PRD §42): passengers per stop pair in 15-minute frames, not vehicles.

import { useEffect } from "react";

import type { Flows } from "../api/types";
import { Field } from "../ui/Quantity";

const STEP_MS = 1200;

interface Props {
  flows: Flows;
  frame: number;
  onFrame: (frame: number) => void;
  playing: boolean;
  onPlaying: (playing: boolean) => void;
}

export function Playback({ flows, frame, onFrame, playing, onPlaying }: Props) {
  const last = flows.frames.length - 1;
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => onFrame(frame >= last ? 0 : frame + 1), STEP_MS);
    return () => clearInterval(timer);
  }, [playing, frame, last, onFrame]);

  const current = flows.frames[frame];
  if (!current) return null;
  const end = flows.frames[frame + 1]?.start;
  return (
    <section className="card" aria-label="Playback">
      <h3>Passenger flows</h3>
      <div className="row">
        <button type="button" onClick={() => onPlaying(!playing)}>
          {playing ? "Pause" : "Play"}
        </button>{" "}
        <strong>
          {current.start}
          {end ? `–${end}` : ""}
        </strong>
      </div>
      <input
        type="range"
        aria-label="Time"
        min={0}
        max={last}
        value={frame}
        onChange={(e) => {
          onPlaying(false);
          onFrame(Number(e.target.value));
        }}
      />
      <p>
        <Field value={current.passenger_segments} info={flows.fields.passenger_segments} /> summed
        over stop pairs
      </p>
      {current.partial && (
        <p className="note" role="note">
          Partial frame: the model only has trips leaving home {flows.demand_window[0]}–
          {flows.demand_window[1]}, so the network is still filling or already draining here.
          Crowding is reported for {flows.report_window[0]}–{flows.report_window[1]} only.
        </p>
      )}
      <p className="note">
        Vehicles leaving each stop in the frame; colour is load over design capacity (Assumed),
        width is passengers.
      </p>
    </section>
  );
}
