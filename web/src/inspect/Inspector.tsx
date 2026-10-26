// What the inspector says about the thing clicked on the map: a zone, a stop, a stop-to-stop
// segment, a route, or a route the scenario changed. Every value is the API's own, labelled.

import type { ReactNode } from "react";

import type {
  ChangedRoute,
  Changes,
  FieldInfo,
  RouteDetail,
  SegmentFeature,
  StopFeature,
} from "../api/types";
import { KIND_COLOUR } from "../compare/layers";
import { toCss } from "../map/colours";
import { Field, NatureBadge, Quantity } from "../ui/Quantity";
import { formatDelta, formatPair } from "../ui/format";

/** One labelled value of a zone; `baseline` is set when a scenario result is shown. */
export interface ZoneFact {
  label: string;
  value: number;
  info: FieldInfo | undefined;
  baseline?: number;
}

export interface ZoneFacts {
  h3: string;
  facts: ZoneFact[];
  /** Within the edge buffer of the study area: destinations beyond it are not modelled. */
  edge: boolean;
}

export type Selection =
  | { kind: "stop"; stop: StopFeature }
  | { kind: "segment"; segment: SegmentFeature }
  | { kind: "zone"; h3: string }
  | { kind: "change"; mutationIdx: number };

function Card({
  eyebrow,
  title,
  onClose,
  children,
  label,
}: {
  eyebrow: ReactNode;
  title: ReactNode;
  onClose?: () => void;
  children: ReactNode;
  label: string;
}) {
  return (
    <section className="card inspect" aria-label={label}>
      <header className="inspect-head">
        <p className="eyebrow">{eyebrow}</p>
        {onClose && (
          <button type="button" className="inspect-close" aria-label="Clear" onClick={onClose}>
            ×
          </button>
        )}
      </header>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function Facts({ children }: { children: ReactNode }) {
  return <dl className="facts">{children}</dl>;
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div>
      <dt>{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function ZoneCard({ zone, onClose }: { zone: ZoneFacts; onClose: () => void }) {
  return (
    <Card
      eyebrow="Zone"
      title={<span className="mono">{zone.h3}</span>}
      onClose={onClose}
      label="Selected zone"
    >
      <Facts>
        {zone.facts.map((f) => {
          if (f.baseline === undefined) {
            return (
              <Fact key={f.label} term={f.label}>
                <Field value={f.value} info={f.info} />
              </Fact>
            );
          }
          const unit = f.info?.unit ?? null;
          const [before, after] = formatPair(f.baseline, f.value, unit);
          return (
            <Fact key={f.label} term={f.label}>
              <span className="quantity">
                <span className="value">
                  {before} → {after}
                </span>{" "}
                <span className="delta">{formatDelta(f.value - f.baseline, unit)}</span>{" "}
                {f.info && <NatureBadge nature={f.info.nature} />}
              </span>
            </Fact>
          );
        })}
      </Facts>
      {zone.edge && (
        <p className="note">
          Near the edge of the study area <NatureBadge nature="assumed" />: places beyond the
          boundary are not modelled, so access from here reads low.
        </p>
      )}
    </Card>
  );
}

export function StopCard({
  stop,
  info,
  onClose,
}: {
  stop: StopFeature;
  info: FieldInfo | undefined;
  onClose: () => void;
}) {
  const s = stop.properties;
  return (
    <Card
      eyebrow={`${s.modes.join(" · ")} stop`}
      title={s.name ?? s.stop_id}
      onClose={onClose}
      label="Selected stop"
    >
      <Facts>
        <Fact term="Stop id">
          <span className="mono">{s.stop_id}</span>
        </Fact>
        <Fact term="Feed">
          <span className="mono">{s.feed}</span>
        </Fact>
        <Fact term="Routes calling">
          <Field value={s.routes} info={info} />
        </Fact>
      </Facts>
    </Card>
  );
}

export function SegmentCard({
  segment,
  fields,
  window,
  onClose,
}: {
  segment: SegmentFeature;
  fields: Record<string, FieldInfo> | undefined;
  window: [string, string];
  onClose: () => void;
}) {
  const p = segment.properties;
  return (
    <Card
      eyebrow="Stop-to-stop segment"
      title={`${p.modes.join(" + ")} segment`}
      onClose={onClose}
      label="Selected segment"
    >
      <Facts>
        <Fact term={`Trips ${window[0]}–${window[1]}`}>
          <Field value={p.window_trips} info={fields?.window_trips} />
        </Fact>
        <Fact term="Trips on the day">
          <Field value={p.trips} info={fields?.trips} />
        </Fact>
        <Fact term="Routes">
          <Field value={p.routes} info={fields?.routes} />
        </Fact>
      </Facts>
      <p className="note">Drawn as a straight line between the stops: the feeds have no shapes.</p>
    </Card>
  );
}

export function RouteCard({
  route,
  onEdit,
  onClose,
}: {
  route: RouteDetail;
  onEdit?: () => void;
  onClose: () => void;
}) {
  const r = route.route;
  const f = route.fields;
  return (
    <Card
      eyebrow={`${r.mode} route`}
      title={
        <>
          {r.short_name ?? r.route_id} <span className="muted">{r.long_name}</span>
        </>
      }
      onClose={onClose}
      label="Selected route"
    >
      <Facts>
        <Fact term="Trips on the day">
          <Field value={r.trips} info={f.trips} />
        </Fact>
        <Fact term="Trips in the AM window">
          <Field value={r.window_trips} info={f.window_trips} />
        </Fact>
        <Fact term="Stop patterns">
          <Field value={r.patterns} info={f.patterns} />
        </Fact>
        <Fact term="Route id">
          <span className="mono">
            {r.feed}:{r.route_id}
          </span>
        </Fact>
      </Facts>
      {onEdit && (
        <button type="button" onClick={onEdit}>
          Change it in Design
        </button>
      )}
    </Card>
  );
}

export function ChangeCard({
  change,
  fields,
  onClose,
}: {
  change: ChangedRoute;
  fields: Changes["fields"];
  onClose: () => void;
}) {
  return (
    <Card
      eyebrow={
        <>
          <span className="swatch" style={{ background: toCss(KIND_COLOUR[change.kind]) }} /> route{" "}
          {change.kind}
        </>
      }
      title={change.name ?? change.route_id}
      onClose={onClose}
      label="Selected change"
    >
      <Facts>
        {change.trips_added > 0 && (
          <Fact term="Trips added">
            <Quantity value={change.trips_added} nature={fields.trips_added!.nature} unit="trips" />
          </Fact>
        )}
        {change.trips_removed > 0 && (
          <Fact term="Trips removed">
            <Quantity
              value={change.trips_removed}
              nature={fields.trips_removed!.nature}
              unit="trips"
            />
          </Fact>
        )}
        {change.boardings_baseline !== null && change.boardings_scenario !== null && (
          <Fact term="Boardings">
            <span className="quantity">
              <span className="value">
                {formatPair(change.boardings_baseline, change.boardings_scenario, "count").join(
                  " → ",
                )}
              </span>{" "}
              <NatureBadge nature={fields.boardings_scenario!.nature} />
            </span>
          </Fact>
        )}
      </Facts>
    </Card>
  );
}
