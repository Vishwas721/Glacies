// Step 3 of the Easy view: the answer, for the place picked and for the whole city, in plain
// words, every number with its label.

import type { Changes, CityDetail, MetricRow } from "../api/types";
import { KIND_CSS } from "../compare/layers";
import type { ResultChoice } from "../compare/results";
import { format, formatPair } from "../ui/format";
import { Field, NatureBadge } from "../ui/Quantity";
import { areasMoved, plainMetrics, READING_WORD, relative, routeChange } from "./plain";
import type { Place } from "./Easy";

interface Props {
  city: CityDetail;
  question: ResultChoice;
  place: Place | null;
  metrics: MetricRow[] | null;
  metricsError: string | null;
  changes: Changes | null;
  reach: { before: Set<string>; after: Set<string> } | null;
  onAnother: () => void;
  onPlace: () => void;
}

export function Answer(props: Props) {
  const { city, question, place, metrics, metricsError, changes, reach } = props;
  const moved = metrics ? areasMoved(metrics) : null;
  return (
    <section className="easy-step" aria-labelledby="answer-title">
      <p className="kicker">Step 3 of 3 · the answer</p>
      <h1 id="answer-title" className="easy-title">
        {question.label}
      </h1>

      {changes && changes.routes.length > 0 && (
        <ul className="changed" aria-label="What this changes">
          {changes.routes.map((r) => (
            <li key={r.mutation_idx}>
              <i style={{ background: KIND_CSS[r.kind] }} aria-hidden="true" />
              <strong>{r.name ?? r.route_id}</strong> {routeChange(r)}
            </li>
          ))}
        </ul>
      )}

      {place && <ForYou place={place} reach={reach} />}

      <div className="answer-block rise" style={{ "--i": 1 } as React.CSSProperties}>
        <h2 className="answer-head">For the whole city</h2>
        {metricsError && <p className="error">{metricsError}</p>}
        {!metrics && !metricsError && <p className="note">Reading the results…</p>}
        {moved && (
          <p className="plain">
            <strong className="gain">{format(moved.gaining.scenario, "count")}</strong> areas can
            reach more estimated jobs within 45 minutes, and{" "}
            <strong className="loss">{format(moved.losing.scenario, "count")}</strong> can reach
            fewer. <NatureBadge nature={moved.gaining.nature} />
          </p>
        )}
        {metrics && (
          <dl className="plain-metrics">
            {plainMetrics(metrics).map((m) => {
              const [before, after] = formatPair(m.row.baseline, m.row.scenario, m.row.unit);
              const size = relative(m.row);
              return (
                <div key={m.label} data-reading={m.reading ?? "neutral"}>
                  <dt title={m.hint}>
                    {m.label}
                    <span className="hint">{m.hint}</span>
                  </dt>
                  <dd>
                    <span className="pair">
                      {before} <span aria-label="becomes">→</span> {after}
                    </span>
                    <span className="verdict">
                      {m.reading ? READING_WORD[m.reading] : "not better or worse by itself"}
                      {size && m.reading !== "no change" ? ` · ${size}` : ""}
                    </span>
                    <NatureBadge nature={m.row.nature} />
                  </dd>
                </div>
              );
            })}
          </dl>
        )}
        {changes && changes.largest_boardings_changes.length > 0 && (
          <>
            <h3 className="answer-sub">Where riders moved</h3>
            <ul className="riders">
              {changes.largest_boardings_changes.slice(0, 4).map((r) => (
                <li key={r.route_idx}>
                  <strong>{r.name ?? `route ${r.route_idx}`}</strong>
                  <span>
                    <Field value={r.boardings_baseline} info={changes.fields.boardings_baseline} />{" "}
                    →{" "}
                    <Field value={r.boardings_scenario} info={changes.fields.boardings_scenario} />{" "}
                    boardings in the morning
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="answer-block trust rise" style={{ "--i": 2 } as React.CSSProperties}>
        <h2 className="answer-head">How sure is this?</h2>
        <p className="plain">
          These are model results <NatureBadge nature="simulated" />, built on the real timetable{" "}
          <NatureBadge nature="observed" /> and estimated homes and jobs{" "}
          <NatureBadge nature="estimated" />, for mornings from {city.window[0]} to {city.window[1]}
          . Buses keep to their timetable: traffic is not modelled. Read very small changes as
          &ldquo;about the same&rdquo;.
        </p>
      </div>

      <div className="easy-actions">
        <button type="button" className="primary big" onClick={props.onAnother}>
          Ask another question
        </button>
        <button type="button" className="link" onClick={props.onPlace}>
          {place ? "Try another place" : "Pick a place"}
        </button>
      </div>
    </section>
  );
}

function ForYou({ place, reach }: { place: Place; reach: Props["reach"] }) {
  if (!reach) {
    return (
      <div className="answer-block">
        <p className="note">Working out what changes from {place.label}…</p>
      </div>
    );
  }
  const gained = [...reach.after].filter((h) => !reach.before.has(h)).length;
  const lost = [...reach.before].filter((h) => !reach.after.has(h)).length;
  const [before, after] = formatPair(reach.before.size, reach.after.size, "count");
  return (
    <div className="answer-block you rise">
      <h2 className="answer-head">For trips from {place.label}</h2>
      <p className="big-figure">
        <span className="figure">
          {before} <span className="arrow">→</span> {after}
        </span>
        <span className="figure-label">
          areas within 45 minutes <NatureBadge nature="simulated" />
        </span>
      </p>
      <p className="plain">
        {gained === 0 && lost === 0
          ? "Nothing changes within 45 minutes from here: the change is too far away, or not enough to bring new areas within reach."
          : [
              gained ? `${format(gained, "count")} areas come within reach` : null,
              lost ? `${format(lost, "count")} drop out` : null,
            ]
              .filter(Boolean)
              .join(", and ") + "."}
      </p>
    </div>
  );
}
