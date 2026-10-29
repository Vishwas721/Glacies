// Step 1 of the Easy view: where the morning starts, and where you can get to from there.

import { useId, useState } from "react";

import type { CityDetail, FieldInfo } from "../api/types";
import { format } from "../ui/format";
import { Field, NatureBadge } from "../ui/Quantity";
import type { Place } from "./Easy";
import { type NamedStop, searchStops } from "./place";

interface Props {
  city: CityDetail;
  stops: NamedStop[];
  place: Place | null;
  reach45: Set<string> | null;
  loading: boolean;
  access: {
    jobs: number;
    people: number;
    info: Record<string, FieldInfo>;
    threshold: number;
  } | null;
  onPick: (stop: NamedStop) => void;
  onClear: () => void;
  onNext: () => void;
}

export function PlaceStep(props: Props) {
  const { city, stops, place, reach45, loading, access, onPick, onClear, onNext } = props;
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const listId = useId();
  const matches = searchStops(stops, text);

  return (
    <section className="easy-step" aria-labelledby="place-title">
      <p className="kicker">Step 1 of 3</p>
      <h1 id="place-title" className="easy-title">
        Where does your morning start?
      </h1>
      <p className="easy-lede">
        Type a bus stop or metro station in {city.name}, or tap anywhere on the map. We&rsquo;ll
        show everywhere you can get to by bus, metro and walking.
      </p>

      <div className="search">
        <input
          type="search"
          role="combobox"
          aria-expanded={open && matches.length > 0}
          aria-controls={listId}
          aria-label="Search a stop or station"
          placeholder={stops.length ? "e.g. a bus stop or metro station" : "Loading stops…"}
          disabled={!stops.length}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && matches[0]) {
              onPick(matches[0]);
              setText(matches[0].name);
              setOpen(false);
            }
          }}
        />
        {open && matches.length > 0 && (
          <ul id={listId} role="listbox" className="search-list">
            {matches.map((s) => (
              <li key={s.name} role="option" aria-selected={false}>
                <button
                  type="button"
                  onClick={() => {
                    onPick(s);
                    setText(s.name);
                    setOpen(false);
                  }}
                >
                  <span>{s.name}</span>
                  {s.metro && <span className="tag">metro</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {place && (
        <div className="reach-card rise">
          <p className="reach-from">
            From <strong>{place.label}</strong>
            <button
              type="button"
              className="link"
              onClick={() => {
                onClear();
                setText("");
              }}
            >
              change
            </button>
          </p>
          {loading || !reach45 ? (
            <p className="note">Working out where you can get to…</p>
          ) : (
            <>
              <p className="big-figure">
                <span className="figure">{reach45.size.toLocaleString("en-IN")}</span>
                <span className="figure-label">
                  areas within 45 minutes <NatureBadge nature="simulated" />
                </span>
              </p>
              {access && (
                <p className="plain">
                  On a typical morning between {city.window[0]} and {city.window[1]}, those areas
                  hold <Field value={access.jobs} info={access.info.est_jobs_share} /> of the
                  city&rsquo;s estimated jobs and{" "}
                  <Field value={access.people} info={access.info.population_share} /> of its
                  residents.
                </p>
              )}
              {place.nearest && place.nearest.metres > 50 && (
                <p className="note">
                  Nearest stop: {place.nearest.name}, {format(place.nearest.metres, "m")} away in a
                  straight line.
                </p>
              )}
              {reach45.size <= 3 && (
                <p className="note">
                  Very few areas: from here most trips start with a long walk, or no bus or metro is
                  close enough to help within 45 minutes.
                </p>
              )}
            </>
          )}
        </div>
      )}

      <div className="easy-actions">
        <button type="button" className="primary big" disabled={!place} onClick={onNext}>
          Next: ask a what-if →
        </button>
        {!place && (
          <button type="button" className="link" onClick={onNext}>
            Skip, look at the whole city
          </button>
        )}
      </div>
    </section>
  );
}
