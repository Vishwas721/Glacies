# ADR 0023 — The web app's layout and visual language

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

The Phase 7 screen worked but read as a test page: a white header, two fixed form columns and a
small map, with the source credits covering the bottom of the map. Three usability faults sat
under it: the demo package's 500-D change was dropped when opened (the API sends absent fields as
null), before/after pairs rounded away the change ("77.4 → 77.4, −0.006 min"), and results were
listed by cache key. A design brief proposed a dark "observatory" with a mode rail, an inspector,
a results dock, a before/after lens and an experiment console, with cyan for the network, amber
for changes and green/red for impact. PRD §39 asks for scenario, map and metrics panels; Phase 7
fixed viridis for levels and the blue/red classes of `glacies scenario compare` for changes.

## Decision

- **Layout.** A rail with four modes (Explore, Design, Compare, Data) chooses the left panel; the
  map takes the middle with a dock under it (simulation runs, flow playback) and an inspector on
  the right (the selection and the impact ledger). That is still PRD §39: scenario left, map,
  metrics right. The mode is in the address bar. Below 1280 px the inspector opens over the map,
  below 900 px the mode panel too; on a phone the rail is a tab bar, panels are bottom sheets and
  Design says that building a scenario needs a wider screen.
- **Colour.** Dark ink surfaces and hairlines from CSS tokens; one interface accent (ice) for
  what is selected or new and amber for what is changed. Data colours are not the brief's: levels
  stay viridis and changes stay blue gain / red loss in the comparison report's classes, because
  green/red fails red-green colour blindness and the map must match the report. The network is
  quiet slate (bus) and pale (metro) so zones and loads read over it; the basemap is OpenFreeMap's
  dark style, greyed and dimmed by a CSS filter on its canvas only.
- **Type.** Archivo (variable width) for text, IBM Plex Mono with tabular figures for numbers,
  ids and coordinates; both OFL, bundled with the app (no font requests, so offline and CI work).
- **Honest instruments.** Lat/lon edge ticks and the scale bar are drawn only while the map is
  flat and north-up, where they are true. Masthead figures that do not fit drop out whole rather
  than lose their data-nature badge.
- **What-If Lens.** Compare can draw baseline left of a draggable divider and scenario right of it,
  on the baseline's colour scale, cut by deck.gl's clip extension. The map view holds the divider
  and re-cuts the tagged layers on each move; through React state the lens panned at 18-31 fps
  against 136-144 fps for other views (headless Chrome, Intel UHD), and 135 fps after the change.
  While it is on, the map cannot rotate or tilt, so the cut follows a meridian.
- **Relief.** Level layers can be raised by their value on a tilted map, height and colour showing
  the same value; not for the change map or the lens.
- **Ledger readings.** Each headline metric says whether its change is better or worse, from a
  table of directions in the web app; counts that cut both ways (metro entries, boardings) are not
  judged. Definitions follow the assignment and accessibility code.
- **No new endpoints.** Everything on screen comes from the Phase 7 API. A "today at a glance"
  card was dropped: the API has baseline metrics only inside comparisons.

## Consequences

- Results show only in Compare; Explore and Design show the baseline (Design adds the draft).
- `docs/demo.md` names the new controls and colours (removed red dashed, added ice, modified
  amber).
- Light mode is gone; the data colours were checked on the dark map only.
- Directions in the ledger live in the web app and must follow any new metric the comparison adds.
