// A simple new route: stops picked on the map in order, run both ways (or one way) at a fixed
// headway and an assumed speed (schema `add_route`).

import { useState } from "react";

import type { AddRoute, StopFeature } from "../api/types";
import { NatureBadge } from "../ui/Quantity";

interface Props {
  picking: boolean;
  onPickingChange: (picking: boolean) => void;
  picked: StopFeature[];
  onPickedChange: (stops: StopFeature[]) => void;
  added: AddRoute[];
  onAddedChange: (added: AddRoute[]) => void;
}

export function AddRouteForm(props: Props) {
  const { picking, onPickingChange, picked, onPickedChange, added, onAddedChange } = props;
  const [routeId, setRouteId] = useState("NEW-1");
  const [name, setName] = useState("");
  const [headwayMin, setHeadwayMin] = useState(10);
  const [speed, setSpeed] = useState(20);
  const [span, setSpan] = useState<[string, string]>(["06:00", "22:00"]);
  const [oneWay, setOneWay] = useState(false);

  const feeds = new Set(picked.map((s) => s.properties.feed));
  const problem =
    picked.length < 2
      ? "Pick at least two stops on the map."
      : feeds.size > 1
        ? "All stops must come from one feed."
        : added.some((r) => r.route_id === routeId)
          ? `${routeId} is already added.`
          : null;

  const add = () => {
    const route: AddRoute = {
      type: "add_route",
      route_id: routeId.trim(),
      ...(name.trim() ? { name: name.trim() } : {}),
      mode: "bus",
      feed: picked[0]!.properties.feed,
      stops: picked.map((s) => s.properties.stop_id),
      one_way: oneWay,
      headway_secs: Math.round(headwayMin * 60),
      span,
      speed_kmh: speed,
    };
    onAddedChange([...added, route]);
    onPickedChange([]);
    onPickingChange(false);
  };

  return (
    <section aria-label="Add a route" className="card">
      <h3>Add a route</h3>
      {added.length > 0 && (
        <ul className="routes">
          {added.map((r) => (
            <li key={r.route_id} className="route">
              {r.name ?? r.route_id} · {r.stops.length} stops · every {r.headway_secs / 60} min{" "}
              <NatureBadge nature="assumed" />{" "}
              <button
                type="button"
                className="link"
                onClick={() => onAddedChange(added.filter((a) => a !== r))}
              >
                remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" aria-pressed={picking} onClick={() => onPickingChange(!picking)}>
        {picking ? "Stop picking" : "Pick stops on the map"}
      </button>
      {picking && <p className="note">Click stops in travel order; turn on the Stops layer.</p>}
      <ol className="picked">
        {picked.map((s, i) => (
          <li key={`${s.properties.stop_id}-${i}`}>
            {s.properties.name ?? s.properties.stop_id}{" "}
            <button
              type="button"
              className="link"
              aria-label={`Drop ${s.properties.name ?? s.properties.stop_id}`}
              onClick={() => onPickedChange(picked.filter((_, j) => j !== i))}
            >
              ×
            </button>
          </li>
        ))}
      </ol>
      <div className="form">
        <label>
          Route id <input value={routeId} onChange={(e) => setRouteId(e.target.value)} />
        </label>
        <label>
          Name <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Every{" "}
          <input
            type="number"
            min={1}
            value={headwayMin}
            onChange={(e) => setHeadwayMin(Number(e.target.value))}
          />{" "}
          min
        </label>
        <label>
          Speed{" "}
          <input
            type="number"
            min={1}
            max={120}
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
          />{" "}
          km/h <NatureBadge nature="assumed" />
        </label>
        <label>
          From <input value={span[0]} onChange={(e) => setSpan([e.target.value, span[1]])} />
        </label>
        <label>
          to <input value={span[1]} onChange={(e) => setSpan([span[0], e.target.value])} />
        </label>
        <label>
          <input type="checkbox" checked={oneWay} onChange={(e) => setOneWay(e.target.checked)} />{" "}
          One way (otherwise the same stops back)
        </label>
      </div>
      {problem && picked.length > 0 && <p className="error">{problem}</p>}
      <button type="button" disabled={problem !== null} onClick={add}>
        Add route
      </button>
    </section>
  );
}
