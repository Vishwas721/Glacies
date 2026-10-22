// Every number on screen goes through <Quantity>, which always shows its data nature
// (CLAUDE.md rule 4): a number without a label cannot be rendered by this component.

import type { FieldInfo, Nature } from "../api/types";
import { format } from "./format";

const LABEL: Record<Nature, string> = {
  observed: "Observed",
  estimated: "Estimated",
  simulated: "Simulated",
  assumed: "Assumed",
};

export function NatureBadge({ nature }: { nature: Nature }) {
  return (
    <span className={`badge badge-${nature}`} title={`${LABEL[nature]} value`}>
      {LABEL[nature]}
    </span>
  );
}

interface QuantityProps {
  value: number;
  nature: Nature;
  unit?: string | null;
}

export function Quantity({ value, nature, unit = null }: QuantityProps) {
  return (
    <span className="quantity">
      <span className="value">{format(value, unit)}</span> <NatureBadge nature={nature} />
    </span>
  );
}

/** A quantity labelled by the API's own `fields` entry. */
export function Field({ value, info }: { value: number; info: FieldInfo | undefined }) {
  if (!info) throw new Error("an API number arrived without its data-nature label");
  return <Quantity value={value} nature={info.nature} unit={info.unit} />;
}
