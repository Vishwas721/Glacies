# ADR 0024 — A landing page, an Easy view and a Pro view

- **Status:** Accepted
- **Date:** 2026-10-29
- **Amends:** ADR 0023 (light mode returns; the map draws data under its labels)

## Context

The screen of ADR 0023 shows everything the model knows at once. Shown to its owner, it read
as overstimulating: it was not clear what the output was or what was happening; polygons and
lines covered the basemap's place names; on the dark theme some things could not be seen. Most
people the project is for (a resident, a councillor, a journalist) want one story: what changes,
for whom. A chatbot was proposed and set aside: PRD §37 makes AI no core requirement and §70
excludes an LLM-first interface; a language model could also state numbers no run produced.

## Decision

- **Three pages.** `/` is a landing page, `/easy` the Easy view, `/pro` the full screen of
  ADR 0023. The path picks the page (no router library); links push history entries and keep
  `?city=`. The API serves the built app's `index.html` for `/easy` and `/pro` too.
- **Landing page.** The baseline's simulated flows (`results/baseline/flows`) drawn as moving
  trails over the city, a clock showing the frame, the question the project answers, and two
  doors, Easy and Pro, split by a seam like the What-If Lens divider. Below: how it works as a
  six-station line, the network in real numbers from the API, who it is for and what it is not.
  A trail's departure inside its 15-minute frame and its speed only place the drawing; the
  passengers and the stop pairs are the model's. The animation stops off screen and stands still
  for viewers who ask for reduced motion.
- **Easy view.** Three steps on a full-screen map, one panel. (1) A place, by stop name or a tap:
  the zones reached within 45 minutes in three bands of door-to-door time, with the zone's share
  of estimated jobs and residents within reach. (2) A question: the latest finished run of each
  scenario, or one bus route twice as often, half as often or removed, run through the whole
  model (with how long earlier runs took, as recorded). (3) The answer: zones that come within
  reach or drop out for that place, then a few comparison metrics in plain words with which way
  is better and the change relative to the baseline, where riders moved, and how far to trust it.
  The address bar keeps step, zone and result, so an answer can be shared.
- **Reach from one zone.** `GET /results/{ref}/reach?zone=<h3>&percentile=` (and on
  simulations) returns every destination in the travel-time matrix with its minutes, Simulated.
  The matrices already hold every zone pair within 120 min; nothing new is computed.
- **The map shows what the step is about.** Easy draws only the metro lines for orientation, the
  place, and the step's layer. Pro draws the network faint under zones or loads.
- **Data under the labels.** deck.gl draws into MapLibre (`interleaved`), below the basemap's
  first label layer, so place and road names stay readable over zones. deck.gl 9.4 reads
  `map.transform.height`, which MapLibre 6 no longer exposes; the map view defines that one
  property from the canvas height until @deck.gl/mapbox supports MapLibre 6. The CSS filter that
  greyed the basemap is gone (it would now grey the data too); the basemap styles are quiet as
  they are. The landing page hides labels: there the trails are the picture.
- **Light and dark.** The viewer's choice, else the system's, stored per browser and set on
  `<html data-theme>` before the first paint. Light uses OpenFreeMap Positron and the same
  hues darkened (tokens in `index.css`, map colours in `map/colours.ts`). Data scales do not
  change: viridis for levels, the comparison report's blue and red for changes.

## Consequences

- `/` is no longer the full screen: links and the browser tests open `/pro`.
- The Easy view's wording (`easy/plain.ts`) names five comparison metrics; a renamed metric
  drops out of the answer until the table follows.
- Switching theme rebuilds the map (another style's label layers), keeping the camera.
- Removing the `map.transform` shim is a task for the next @deck.gl/mapbox upgrade.
