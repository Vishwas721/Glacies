// What the map shows when nothing is selected: the layers on screen in plain words, with the
// API's own descriptions and labels, and what to try next in this mode.

import type { FieldInfo } from "../api/types";
import type { Mode } from "../shell/modes";
import { NatureBadge } from "../ui/Quantity";

const NEXT: Record<Mode, string> = {
  explore:
    "Click a zone for its residents, estimated employment and reach; a segment for its trips. Relief (map controls) raises zones by their value.",
  design:
    "Find a route to take it out or change how often it runs, or pick stops for a new one. The draft is drawn on the map before you simulate.",
  compare:
    "Pick a finished run under Results. Lens puts the baseline and the scenario side by side; Change shows where access moved.",
  data: "",
};

interface Props {
  mode: Mode;
  zoneLayer: string | null;
  zoneInfo: FieldInfo | undefined;
  window: [string, string];
  network: boolean;
}

export function Reading({ mode, zoneLayer, zoneInfo, window, network }: Props) {
  return (
    <section className="card reading" aria-label="Reading the map">
      <p className="eyebrow">Reading the map</p>
      <dl>
        {zoneLayer && zoneInfo && (
          <>
            <dt>
              Zones: {zoneLayer} <NatureBadge nature={zoneInfo.nature} />
            </dt>
            <dd>{zoneInfo.description}</dd>
          </>
        )}
        {network && (
          <>
            <dt>
              Network <NatureBadge nature="observed" />
            </dt>
            <dd>
              Bus and metro stop-to-stop segments, wider where more vehicles run {window[0]}–
              {window[1]}; metro is pale. Lines are straight between stops{" "}
              <NatureBadge nature="assumed" />: the feeds have no shapes.
            </dd>
          </>
        )}
      </dl>
      {NEXT[mode] && <p className="note reading-next">{NEXT[mode]}</p>}
    </section>
  );
}
