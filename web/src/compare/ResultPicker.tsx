// Choose which finished result the screen compares with the baseline.

import { useResults } from "../api/queries";
import { comparableResults, type ResultChoice } from "./results";

interface Props {
  city: string;
  value: ResultChoice | null;
  onChange: (choice: ResultChoice | null) => void;
}

const option = (c: ResultChoice) => (
  <option key={c.key} value={c.key}>
    {c.finishedAt ? `${c.label} · ${c.finishedAt}` : c.label}
  </option>
);

export function ResultPicker({ city, value, onChange }: Props) {
  const results = useResults(city);
  const listed = comparableResults(results.data ?? []);
  // A result chosen from a just-finished run may not be listed yet.
  const choices = value && !listed.some((c) => c.key === value.key) ? [value, ...listed] : listed;
  return (
    <section className="card" aria-label="Results">
      <h3>Results</h3>
      {results.error && <p className="error">{results.error.message}</p>}
      <select
        aria-label="Compare with"
        value={value?.key ?? ""}
        onChange={(e) => onChange(choices.find((c) => c.key === e.target.value) ?? null)}
      >
        <option value="">Baseline only</option>
        <optgroup label="Latest run of each scenario">
          {choices.filter((c) => c.latest !== false).map(option)}
        </optgroup>
        {choices.some((c) => c.latest === false) && (
          <optgroup label="Earlier runs">
            {choices.filter((c) => c.latest === false).map(option)}
          </optgroup>
        )}
      </select>
      {choices.length === 0 && !results.error && (
        <p className="note">Simulate a scenario to compare it with the baseline.</p>
      )}
    </section>
  );
}
