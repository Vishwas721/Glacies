# Glossary

## Data nature labels (PRD §56)

Every number Glacies shows carries one of these labels. They map to
`glacies.provenance.DataNature`.

| Label | Meaning | Example |
|---|---|---|
| **Observed** | Measured in a source dataset | BMRCL hourly station entries; GTFS scheduled departures |
| **Estimated** | Derived by a model from observed data | Employment proxy from building area + land use + POIs |
| **Simulated** | Produced by a Glacies run | Route loads, travel times, accessibility after a scenario |
| **Assumed** | A parameter chosen by the developer | Walking speed 1.2 m/s, bus capacity 70, H3 resolution 8 |

## Transit & data terms

| Term | Definition |
|---|---|
| **GTFS** | General Transit Feed Specification, the CSV-in-a-zip format for schedules (stops, routes, trips, stop_times, calendar) |
| **Feed** | One GTFS dataset from one publisher |
| **Route (GTFS)** | A customer-facing line, e.g. "500D". May contain trips with different stop patterns |
| **Route (RAPTOR)** | A set of trips that visit *exactly* the same stop sequence. One GTFS route often splits into several RAPTOR routes |
| **Trip** | One vehicle run along a stop sequence at specific times |
| **Stop pattern** | The ordered list of stops a trip visits |
| **Headway** | Time between consecutive departures on a route (inverse of frequency) |
| **Service day / calendar** | Which dates a trip runs. GTFS times may exceed 24:00:00 for after-midnight trips |
| **Transfer** | Changing from one vehicle to another, optionally with a walk between stops |
| **Footpath** | A walking link between two stops used for transfers |
| **Access / egress** | Walking from the origin to the first stop / from the last stop to the destination |
| **RAPTOR** | Round-bAsed Public Transit Optimized Router: round *k* finds the best arrivals using at most *k* vehicles |
| **Range RAPTOR (rRAPTOR)** | RAPTOR over a departure-time window, giving travel-time distributions instead of a single departure |
| **Pareto set** | Journeys where none is better on every criterion (e.g. arrival time *and* transfers) |
| **Zone** | Spatial unit for demand and accessibility; here H3 hexagons |
| **H3** | Uber's hierarchical hexagonal grid; resolution 8 ≈ 0.74 km² per cell |
| **OD matrix** | Trips from each origin zone *i* to each destination zone *j* |
| **Production / attraction** | Trips generated at origins (O<sub>i</sub>) / attracted to destinations (D<sub>j</sub>) |
| **Gravity model** | T<sub>ij</sub> = A<sub>i</sub>O<sub>i</sub>B<sub>j</sub>D<sub>j</sub>f(c<sub>ij</sub>); demand falls with travel cost |
| **Doubly constrained** | Balancing factors A<sub>i</sub>, B<sub>j</sub> make row sums = O<sub>i</sub> and column sums = D<sub>j</sub> |
| **Furness / IPF** | Iterative proportional fitting used to compute the balancing factors |
| **Impedance / generalised cost** | Combined travel cost: in-vehicle time + weighted wait + weighted walk + transfer penalty |
| **Friction (decay) function** | f(c), e.g. exp(−βc) or c<sup>−α</sup>; β is the main calibration parameter |
| **Assignment** | Putting OD demand onto specific journeys/vehicles |
| **All-or-nothing** | Every OD pair uses only its single best path |
| **Capacity-constrained assignment** | Iterative assignment where crowded trips get penalties and demand shifts |
| **Load / volume** | Passengers on a trip segment between two consecutive stops |
| **Load factor** | Load ÷ capacity; > 1 means overcrowded |
| **Cumulative-opportunity accessibility** | Number of opportunities (jobs, people) reachable within a travel-time threshold |
| **Scenario** | A list of mutations applied to a baseline network; stored as a diff, not a copy |
| **Baseline** | The unmodified network a scenario is compared against |
| **NSGA-II** | Multi-objective genetic algorithm that returns a Pareto front |
| **Pareto front** | Set of trade-off solutions (e.g. waiting time vs. fleet hours) |
