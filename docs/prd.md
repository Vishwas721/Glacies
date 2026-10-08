Glacies
Urban Transit Digital Twin & Scenario Simulation Platform
Product Requirements Document — PRD
Project type: Research-oriented software platform
Developer: Solo developer
Initial city: Bengaluru, Karnataka, India
Budget: ₹0 / zero-cost
Primary goal: Build a technically credible transit simulation and scenario-analysis platform using free/open data and open-source software.
1. Executive Summary
Glacies is an urban public-transit digital twin designed to allow users to model, simulate, and compare changes to a city's public transportation network.
The system will ingest real transit, road, population, land-use, and building data and construct a computational representation of the city.
Users will be able to create hypothetical scenarios such as:
- increasing bus frequency
- removing routes
- adding routes
- modifying service patterns
- changing transit connections
- introducing a new transit link
- modifying stop/service characteristics
Glacies will estimate synthetic passenger demand, route passengers through the transit network, model capacity and crowding effects at an aggregate level, and compare the resulting scenario against the baseline.
The primary outputs will include:
- travel-time changes
- waiting-time changes
- passenger flows
- transit utilization
- crowding/capacity effects
- accessibility
- jobs reachable within specified travel times
- population accessibility
- before/after scenario differences
The initial implementation will focus on Bengaluru.
The platform will use a macroscopic/mesoscopic assignment model rather than microscopic vehicle simulation. This is a deliberate scope decision based on the project's solo-developer and consumer-hardware constraints. Glacies Transit Digital Twin Re…
2. Problem Statement
Urban transit networks are highly interconnected systems.
A change to one route can affect:
Route frequency
       ↓
Waiting time
       ↓
Passenger route choice
       ↓
Bus loads
       ↓
Crowding
       ↓
Travel times
       ↓
Accessibility

Traditional maps and timetable viewers generally show the existing network, but do not answer:
"What would happen if we changed it?"

Glacies addresses this by allowing users to create counterfactual transit scenarios and quantitatively compare them against the existing network.
3. Product Vision
Build an open, transparent, zero-cost urban transit experimentation platform that allows anyone to understand how changes to a city's public-transit network affect mobility and accessibility.

The long-term vision is for Glacies to evolve from a Bengaluru-specific research project into a city-agnostic transit simulation engine.
The architecture should therefore separate:
Glacies Engine
       ↑
City-specific datasets

rather than embedding Bengaluru-specific assumptions throughout the codebase.
This is particularly important because the research identifies the unofficial BMTC feed as a major risk and recommends making the architecture city-agnostic. Glacies Transit Digital Twin Re…
4. Product Goals
4.1 Primary goals
Glacies must:
1. ingest real public-transit data
2. construct a multimodal transportation network
3. perform schedule-based transit routing
4. generate synthetic transportation demand
5. assign passengers to the network
6. model transit capacity/crowding at an aggregate level
7. support hypothetical network scenarios
8. compare scenarios against a baseline
9. calculate accessibility metrics
10. visualize results interactively
11. run locally on consumer hardware
12. use free/open-source software and data
13. remain scientifically transparent and reproducible
5. Non-Goals
Glacies will not initially attempt to:
- simulate individual car physics
- simulate traffic lights
- model individual vehicle lane changes
- reproduce microscopic road traffic
- provide real-time fleet management
- become a ride-hailing system
- predict exact individual travel behavior
- provide operational dispatching
- provide production transit scheduling
- require commercial APIs
- require cloud infrastructure
- provide exact real-world passenger predictions
The research specifically recommends removing microscopic physical traffic simulation, live GTFS-RT, weather, elevation, and emissions from the initial scope. Glacies Transit Digital Twin Re…
6. Target Users
Primary user
Urban transportation researcher
Wants to:
- analyze a transit network
- test changes
- study accessibility
- compare scenarios
Secondary user
Urban planner
Wants to answer:
"What happens if we change service in this corridor?"

Secondary user
Transit advocacy organization
Wants evidence for:
- underserved areas
- accessibility gaps
- route changes
- frequency improvements
Secondary user
Student/researcher
Wants to experiment with:
- transit algorithms
- demand models
- network optimization
- accessibility analysis
7. Core Product Workflow
The complete Glacies pipeline will be:
                DATA SOURCES
                     │
       ┌─────────────┼─────────────┐
       │             │             │
      GTFS          OSM       Population
       │             │             │
       └─────────────┼─────────────┘
                     │
                     ▼
              DATA INGESTION
                     │
                     ▼
              DATA VALIDATION
                     │
                     ▼
            CANONICAL CITY MODEL
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
   TRANSIT NETWORK           SPATIAL DATA
        │                         │
        └────────────┬────────────┘
                     ▼
              ROUTING ENGINE
                     │
                     ▼
             DEMAND GENERATOR
                     │
                     ▼
                OD MATRIX
                     │
                     ▼
           PASSENGER ASSIGNMENT
                     │
                     ▼
            CAPACITY / CROWDING
                     │
                     ▼
              SCENARIO ENGINE
                     │
                     ▼
                ANALYTICS
                     │
                     ▼
             VISUALIZATION

8. System Architecture
The proposed system consists of six major layers.
┌──────────────────────────────────────────┐
│                 FRONTEND                 │
│ React + TypeScript + deck.gl + MapLibre │
└────────────────────┬─────────────────────┘
                     │
                  REST/WS
                     │
┌────────────────────▼─────────────────────┐
│                  API                     │
│                 FastAPI                  │
└────────────────────┬─────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
   Scenario       Routing     Simulation
   Manager        Engine      Workers
        │            │            │
        └────────────┼────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
    PostgreSQL                 DuckDB
     + PostGIS                + Parquet
        │                         │
        └────────────┬────────────┘
                     │
                     ▼
                Redis / Jobs

The research proposes Python for ingestion, PostGIS for spatial processing, Rust for the routing/assignment core, DuckDB/Parquet for analytical results, FastAPI for orchestration, and React/deck.gl for visualization. Glacies Transit Digital Twin Re…
9. Data Sources
The initial Bengaluru data ecosystem should use free/open sources.
9.1 BMTC
Primary candidate:
Unofficial BMTC GTFS dataset
Source identified in the research:
Vonter/bmtc-gtfs
The feed is derived from the official Namma BMTC application and uses ODbL according to the research report. However, it omits routes without functional live-tracking telematics. Glacies Transit Digital Twin Re…
Therefore:
Requirement: The ingestion system must explicitly detect incomplete coverage.
10. Bengaluru Metro
Use the researched BMRCL GTFS source where available.
Additionally, the project should use the identified:
BMRCL hourly ridership dataset
for model calibration/validation.
The research identifies hourly station-level ingress/egress data available through the Vonter/bmrcl-ridership-hourly repository. Glacies Transit Digital Twin Re…
This is extremely valuable because demand estimation is one of Glacies's biggest risks.
11. OpenStreetMap
Use OpenStreetMap as the base:
- road network
- pedestrian network
- crossings
- transit infrastructure
- relevant POIs
The research recommends using the Geofabrik Karnataka .osm.pbf extract, processed using osmium and pyrosm, rather than loading the entire network into a Python NetworkX graph. Glacies Transit Digital Twin Re…
12. Population
Use:
WorldPop
Recommended source:
India 100m constrained population dataset
The research identifies the 2020 UN-adjusted constrained dataset as the preferred initial source and reports a CC-BY 4.0 license. Glacies Transit Digital Twin Re…
Population becomes the primary basis for estimating trip origins.
13. Employment Proxy
Exact open employment data is expected to be unavailable at sufficient spatial resolution.
Glacies will therefore construct an employment proxy using:
Google Open Buildings
        +
ESA WorldCover
        +
OSM POIs
        ↓
Employment attractiveness

The research proposes using building area, land-use classification, and relevant POIs to estimate destination attractiveness. Glacies Transit Digital Twin Re…
Important:
This must be explicitly labelled as an estimated employment proxy, not actual employment data.
14. Data Pipeline
14.1 Raw data
Raw datasets must never be directly consumed by the simulation engine.
Instead:
Raw source
    ↓
Download
    ↓
Archive
    ↓
Validation
    ↓
Normalization
    ↓
Canonical dataset

15. Data Versioning
Each dataset must have:
dataset_name
source
source_url
download_date
version
license
checksum
processing_version

Example:
{
  "dataset": "bmtc_gtfs",
  "source": "Vonter/bmtc-gtfs",
  "downloaded_at": "...",
  "checksum": "...",
  "processor_version": "0.1.0"
}

This makes experiments reproducible.
16. GTFS Validator
The system must validate:
Required files
agency.txt
stops.txt
routes.txt
trips.txt
stop_times.txt
calendar.txt

and optional:
shapes.txt
frequencies.txt
calendar_dates.txt

Validation should detect:
- missing fields
- invalid IDs
- duplicate stops
- orphaned trips
- impossible timestamps
- missing route relationships
- invalid coordinates
- malformed geometries
- invalid calendars
- overlapping/inconsistent services
17. Canonical Transit Model
GTFS should be transformed into an internal model.
Conceptually:
Agency
 ├── Routes
 │    ├── Trips
 │    │    ├── Stop Times
 │    │    └── Shape
 │    └── Stops
 │
 └── Calendar

The canonical representation should be independent of GTFS so other cities can eventually be supported.
18. Routing Engine
Core algorithm
RAPTOR
The research recommends implementing RAPTOR rather than relying entirely on an external black-box routing engine. Glacies Transit Digital Twin Re…
19. Why RAPTOR
RAPTOR operates on transit routes and rounds representing transfers.
Conceptually:
Round 0
Walking

Round 1
First transit boarding

Round 2
One transfer

Round 3
Two transfers

...

The engine should support optimization based on:
- arrival time
- transfers
- walking time
20. Routing Engine Requirements
The routing engine must support:
Input
origin
destination
departure_time

Output
arrival_time
travel_time
walking_time
waiting_time
transfers
route_sequence
stop_sequence

Example:
{
  "travel_time": 42,
  "walking_time": 7,
  "waiting_time": 5,
  "transfers": 1,
  "legs": [...]
}

21. Routing Implementation
The proposed implementation is:
Rust + PyO3
Rust handles:
- compact data structures
- timetable arrays
- routing loops
- memory efficiency
- high-throughput routing
Python handles orchestration and data processing.
The research specifically recommends this architecture for memory safety and performance under the 24 GB RAM constraint. Glacies Transit Digital Twin Re…
22. Demand Generation
Because actual origin-destination data is unavailable, Glacies will generate synthetic demand.
The initial model will be:
Doubly Constrained Gravity Model
Conceptually:
\[
T_{ij}=A_iO_iB_jD_jf(c_{ij})
\]
where:
- \(O_i\) = trip production at origin
- \(D_j\) = trip attraction at destination
- \(c_{ij}\) = travel impedance
- \(f(c)\) = friction/decay function
- \(A_i,B_j\) = balancing factors
The model will iteratively balance total productions and attractions. Glacies Transit Digital Twin Re…
23. Trip Origins
Trip origins will be derived from:
WorldPop
The city will be divided into spatial zones.
For example:
Bengaluru
   ↓
H3 / hexagonal grid
   ↓
Population per cell

Each cell becomes a potential origin zone.
24. Trip Destinations
Destination attractiveness will be estimated using:
Building area
+
Land use
+
Commercial POIs
+
Employment assumptions

This will produce:
employment_score(zone)

rather than claiming exact employment counts.
25. Demand Calibration
Demand must be calibrated against available observed data.
The primary calibration target will be:
BMRCL hourly ridership
The research proposes adjusting the travel-impedance/friction parameters until simulated metro usage aligns with empirical ridership. Glacies Transit Digital Twin Re…
26. Passenger Assignment
Once OD demand is generated:
OD Matrix
    ↓
RAPTOR
    ↓
Optimal journeys
    ↓
Transit assignment

Passengers are assigned to available transit journeys.
27. Capacity Modeling
Glacies will not simulate individual passengers physically.
Instead:
Passenger demand
      ↓
Transit trip
      ↓
Passenger load
      ↓
Vehicle capacity

If demand exceeds capacity:
load > capacity
      ↓
crowding penalty
      ↓
reroute / alternative assignment

This is the proposed mechanism for capturing crowding without microscopic vehicle simulation. Glacies Transit Digital Twin Re…
28. Simulation Engine
The simulation engine is therefore a:
macroscopic/mesoscopic transit assignment engine
rather than:
microscopic traffic simulator.
It will model:
- passengers
- transit trips
- travel times
- waiting
- transfers
- capacity
- aggregate crowding
- route utilization
It will NOT model:
- individual car trajectories
- lane changes
- traffic signals
- collision dynamics
29. Scenario Engine
A scenario is a set of mutations applied to the baseline network.
It must NOT duplicate the entire database.
Example:
{
  "scenario_id": "blr_frequency_test_01",
  "base_network": "bengaluru_2026",
  "mutations": [
    {
      "type": "modify_headway",
      "route_id": "500D",
      "new_interval_sec": 300
    },
    {
      "type": "remove_route",
      "route_id": "201R"
    }
  ]
}

The research recommends this diff-based approach to enable incremental recomputation. Glacies Transit Digital Twin Re…
30. Scenario Types
The system should support:
Route modifications
- add route
- remove route
- modify route
Frequency modifications
- increase frequency
- decrease frequency
- change headway
Stop modifications
- add stop
- remove stop
- modify stop
Network modifications
- add transit connection
- remove transit connection
Future
- metro expansion
- feeder routes
- express services
31. Scenario Comparison
Every scenario should be compared against a baseline.
Example:
                 BASELINE     SCENARIO

Avg travel time    48.2         42.6
Avg waiting        11.4          7.8
Transfers           1.7          1.4
Accessibility       62%          71%
Crowding            18%          13%

The UI should visually highlight differences.
32. Accessibility Engine
One of Glacies's most important features.
The system should calculate:
How much of the city's opportunity can a person reach within X minutes?

Time thresholds:
15 min
30 min
45 min
60 min

Possible metrics:
Jobs accessible
jobs reachable within 45 min

Population accessibility
population that can reach major employment zones

Accessibility change
scenario accessibility
-
baseline accessibility

33. Accessibility Heatmap
The frontend should display:
        BASELINE

       🟢🟢🟡
      🟢🟡🟠
     🟡🟠🔴

and:
        SCENARIO

       🟢🟢🟢
      🟢🟢🟡
     🟡🟢🟡

Then:
         Δ ACCESSIBILITY

       + + + 0
      + + 0 -
       0 - -

34. Optimization
Optimization will not initially attempt complete route redesign.
The first optimization problem will be:
Frequency Optimization
Given a fixed fleet:
Available buses
       ↓
Possible headways
       ↓
Simulation
       ↓
Waiting time
       ↓
Operational hours

The research recommends NSGA-II as the optimization method, with objectives including passenger waiting time and fleet operating hours. Glacies Transit Digital Twin Re…
35. Optimization Output
Instead of one arbitrary "best" solution, the system should eventually display a Pareto frontier.
For example:
Waiting time ↓

│      ●
│    ●
│  ●
│ ●
│____________________
        Cost →

Users can select different tradeoffs.
This is more appropriate for a planning tool because transportation decisions involve competing objectives.
36. Optimization Scope
Initial optimization:
Maximum ~5 trunk routes simultaneously
as suggested in the research risk mitigation. Glacies Transit Digital Twin Re…
Do not attempt whole-network route generation initially.
37. AI/ML
AI is not a core requirement.
The research explicitly identifies the core system as deterministic mathematical simulation and regards natural-language scenario generation as unnecessary for the core product. Glacies Transit Digital Twin Re…
Therefore:
Core
No AI required.
Advanced
Potential ML surrogate model for optimization.
Because repeatedly running the assignment engine thousands of times could become expensive, a surrogate could eventually predict optimization fitness. Glacies Transit Digital Twin Re…
38. Frontend
Technology
- React
- TypeScript
- deck.gl
- MapLibre or equivalent open map renderer
39. Main UI
The main interface should look conceptually like:
┌───────────────────────────────────────────────┐
│ GLACIES                         Bengaluru     │
├─────────────┬───────────────────┬─────────────┤
│ SCENARIO    │                   │ METRICS     │
│             │                   │             │
│ Routes      │                   │ Travel time │
│ ☑ 500D      │      MAP          │ 48 → 42 min │
│ ☑ 201R      │                   │             │
│             │                   │ Waiting     │
│ Frequency   │                   │ 11 → 7 min  │
│ 10 → 5 min  │                   │             │
│             │                   │ Accessibility│
│             │                   │ 62 → 71%    │
│ [SIMULATE]  │                   │             │
└─────────────┴───────────────────┴─────────────┘

40. Main Map Layers
The map should support:
Transit
- bus routes
- metro routes
- stops
- stations
Population
- population density
Employment
- estimated employment density
Accessibility
- accessibility heatmap
Simulation
- passenger flows
- route utilization
- crowding
Scenario
- removed routes
- added routes
- modified routes
41. Scenario Visualization
Changes should be visually obvious.
For example:
REMOVED
Route A ───────────

ADDED
Route B ═══════════

MODIFIED
Route C ──╱────╲───

42. Simulation Playback
The original concept envisioned animated simulation playback.
For the first version, this should be aggregate passenger-flow playback, not physical vehicle simulation.
Example:
08:00
   ↓
08:15
   ↓
08:30
   ↓
08:45

Passengers can be represented as aggregated flows rather than millions of DOM objects.
The research specifically recommends pre-aggregating large datasets before sending them to deck.gl. Glacies Transit Digital Twin Re…
43. Backend API
Potential endpoints:
City
GET /api/cities
GET /api/cities/{city}

Network
GET /api/routes
GET /api/routes/{id}
GET /api/stops
GET /api/network

Routing
POST /api/route

Request:
{
  "origin": [12.97, 77.59],
  "destination": [12.98, 77.64],
  "departure_time": "08:30"
}

44. Scenario API
POST /api/scenarios
GET /api/scenarios/{id}
PATCH /api/scenarios/{id}
DELETE /api/scenarios/{id}

45. Simulation API
Simulation should be asynchronous.
POST /api/simulations

Response:
{
  "job_id": "sim_123",
  "status": "queued"
}

Then:
GET /api/simulations/{job_id}

Possible states:
QUEUED
RUNNING
COMPLETED
FAILED
CANCELLED

46. Results API
GET /api/simulations/{id}/metrics
GET /api/simulations/{id}/accessibility
GET /api/simulations/{id}/flows
GET /api/simulations/{id}/crowding

Large results should not be loaded directly into PostgreSQL responses.
Use:
Parquet + DuckDB
for analytical workloads, as recommended in the research. Glacies Transit Digital Twin Re…
47. Job Architecture
User
 ↓
FastAPI
 ↓
Redis job queue
 ↓
Worker
 ├── Scenario preparation
 ├── Routing
 ├── Demand
 ├── Assignment
 └── Metrics
 ↓
Parquet
 ↓
DuckDB
 ↓
API
 ↓
Frontend

48. Database
PostgreSQL + PostGIS
Used for:
- city boundaries
- stops
- routes
- road geometries
- spatial zones
- buildings
- population zones
- employment zones
- scenarios
- metadata
49. Analytical Storage
Parquet
Used for:
- OD matrices
- passenger assignments
- route loads
- accessibility results
- simulation results
DuckDB
Used for:
- analytical queries
- aggregations
- filtering
- result generation
The research specifically recommends this combination because large OD datasets can exceed practical Pandas memory limits. Glacies Transit Digital Twin Re…
50. Redis
Redis will manage:
- job state
- progress
- temporary task metadata
- worker coordination
51. Non-Functional Requirements
Performance
The system should:
- avoid NetworkX for city-scale canonical graphs
- use compact routing structures
- avoid loading unnecessary datasets into RAM
- use spatial indexing
- use batch processing
- use Parquet for large analytical datasets
- support asynchronous simulations
52. Memory
The system must operate within approximately:
24 GB RAM
The routing core should avoid excessive Python object overhead.
53. Reproducibility
Every simulation must record:
scenario ID
dataset versions
routing version
demand model version
random seed
configuration
timestamp

A simulation should be reproducible.
54. Deterministic Simulation
Given:
same dataset
+
same scenario
+
same configuration
+
same random seed

the result should be identical.
55. Data Quality
Every imported dataset must have a validation report.
Example:
BMTC GTFS

Routes:       842
Stops:        12,482
Trips:        54,192

Warnings:
- 31 orphan stops
- 4 invalid shapes
- 12 routes missing frequencies

Coverage:
78%

56. Scientific Transparency
Glacies should clearly distinguish:
Observed
Actual dataset measurements.
Estimated
Model-derived quantities.
Simulated
Results produced by Glacies.
Assumed
Parameters introduced by the developer.
For example:
"Estimated employment density"

must never be presented as:
"Actual employment."

This is essential to maintain credibility.
57. Validation Strategy
Validation should occur at multiple levels.
Level 1 — Data
Does GTFS represent the actual network?
Level 2 — Routing
Does Glacies produce plausible journeys?
Level 3 — Demand
Does aggregate demand resemble available ridership?
Level 4 — Assignment
Do passenger loads make sense?
Level 5 — Scenario
Do changes produce logically plausible effects?
58. Unit Testing
The RAPTOR engine should first be tested on tiny synthetic networks.
Example:
A → B → C

Then:
A → B
     ↓
     C

Then:
A → B → C
 \       ↑
  → D ───

The research specifically recommends extensive tests using small toy networks before Bengaluru-scale data. Glacies Transit Digital Twin Re…
59. Integration Testing
Test:
GTFS
 ↓
Canonical network
 ↓
RAPTOR
 ↓
Demand
 ↓
Assignment
 ↓
Metrics

as an end-to-end pipeline.
60. MVP
The MVP should not attempt the entire vision.
The recommended MVP is:
Data
- Bengaluru GTFS
- OSM
- WorldPop
- basic employment proxy
Algorithms
- GTFS validation
- network construction
- RAPTOR
- synthetic demand
- accessibility calculation
Scenarios
- route removal
- frequency modification
- route addition
Visualization
- transit network
- population
- accessibility
- before/after comparison
61. MVP Demo
The ideal MVP demonstration:
Select several overlapping routes → modify the network → generate synthetic demand → run the assignment → compare accessibility and travel metrics against the baseline.

Example:
BASELINE

Average travel time
47.8 min

45-min accessibility
61%

Average transfers
1.8


SCENARIO

Average travel time
42.1 min

45-min accessibility
69%

Average transfers
1.5

The actual numbers must come from the simulation, not be fabricated.
62. Phase 1 — Data Foundation
Goal: Create a trustworthy Bengaluru dataset.
Tasks:
- download GTFS
- archive raw data
- validate GTFS
- process OSM
- download WorldPop
- download WorldCover
- acquire Open Buildings
- construct spatial grid
- load PostGIS
- create canonical data model
Definition of done:
A reproducible command can rebuild the city dataset from raw inputs.
63. Phase 2 — Routing Engine
Goal: Build reliable schedule-based transit routing.
Tasks:
- Rust project
- GTFS representation
- route indexing
- stop indexing
- RAPTOR
- walking access
- transfers
- journey reconstruction
- PyO3 bindings
- benchmarks
64. Phase 3 — Demand
Goal: Generate synthetic OD demand.
Tasks:
- population zones
- destination zones
- employment proxy
- gravity model
- impedance function
- balancing
- calibration
- OD matrix generation
65. Phase 4 — Assignment
Goal: Assign synthetic demand to transit.
Tasks:
- route selection
- passenger aggregation
- trip loads
- capacity
- crowding
- waiting
- transfers
- metrics
66. Phase 5 — Scenario Engine
Goal: Make the system capable of counterfactual analysis.
Tasks:
- scenario schema
- mutation engine
- baseline snapshots
- incremental recomputation
- scenario comparison
- reproducibility
67. Phase 6 — Visualization
Goal: Make results understandable.
Tasks:
- map
- route layers
- accessibility
- passenger flows
- scenario differences
- metrics dashboard
- simulation playback
68. Phase 7 — Optimization
Only after the deterministic system is stable.
Implement:
Frequency optimization
using:
NSGA-II
Initially constrain:
5 trunk routes

rather than attempting whole-network route generation. Glacies Transit Digital Twin Re…
69. Phase 8 — Advanced Research
Possible future work:
- optimization surrogate models
- improved route-choice models
- additional cities
- uncertainty analysis
- resilience analysis
- network redesign
- improved demand calibration
- additional transit modes
70. Out-of-Scope Until Later
Explicitly postpone:
❌ Microscopic traffic simulation
❌ Real-time GTFS-RT
❌ Weather-driven simulation
❌ Emissions modeling
❌ Vehicle physics
❌ Traffic-light simulation
❌ Individual car simulation
❌ Full automatic route generation
❌ LLM-first scenario interface
❌ Cloud deployment
These exclusions are consistent with the research report's recommendation to aggressively control scope. Glacies Transit Digital Twin Re…
71. Major Risks
Risk 1 — BMTC dataset disappears
Probability: High
Impact: High
Mitigation:
- archive downloaded feeds
- create city-agnostic architecture
- maintain fallback datasets
The research explicitly identifies this as the highest-risk dependency. Glacies Transit Digital Twin Re…
Risk 2 — Employment proxy is inaccurate
Probability: High
Impact: High
Mitigation:
- clearly label estimates
- validate against known employment corridors
- perform sensitivity analysis
- avoid claiming precise job counts
Risk 3 — Gravity model produces unrealistic demand
Probability: Medium/High
Impact: High
Mitigation:
- calibrate against BMRCL ridership
- compare multiple parameter settings
- conduct sensitivity analysis
Risk 4 — Routing implementation becomes too complex
Probability: High
Impact: High
Mitigation:
Build in this order:
Toy network
 ↓
Simple GTFS
 ↓
Single-city routing
 ↓
Multimodal
 ↓
Large Bengaluru dataset

Risk 5 — Scope explosion
Probability: Very High
Impact: Critical
Mitigation:
Maintain a strict:
Core / Later / Never

feature classification.
72. Success Metrics
Glacies is successful when it can:
Data
- ingest Bengaluru transit data reproducibly
- detect data quality problems
Routing
- correctly solve transit journeys
- handle transfers
- handle schedule constraints
Demand
- generate a reproducible OD matrix
- calibrate against available observations
Simulation
- assign passenger demand
- calculate route loads
- calculate accessibility
Scenarios
- modify network parameters
- rerun affected computations
- compare results
Visualization
- render the network
- show accessibility
- show scenario differences
73. The Core Demonstration
The final demonstration should tell one complete story.
Step 1
Load:
Bengaluru baseline network
Step 2
Show:
Current accessibility
Step 3
Create:
Scenario
Modify frequencies
+
Remove selected overlapping service
+
Introduce proposed corridor

Step 4
Run:
Demand + routing + assignment
Step 5
Show:
Before vs After
Travel time
Waiting time
Transfers
Accessibility
Crowding
Passenger flows

Step 6
Visualize:
Where did accessibility improve?
Step 7
Explain:
What changed and why?
That is the core Glacies experience.
74. Long-Term Vision
Eventually Glacies could become:
             GLACIES
                │
       ┌────────┼────────┐
       │        │        │
    Bengaluru  Portland  Helsinki
       │        │        │
       └────────┼────────┘
                │
        Universal Transit
         Simulation Engine

The city becomes a dataset/plugin rather than the application itself.
75. Final Product Definition
The most important thing to remember is:
Glacies is not a map.

It is not:
"A Bengaluru bus visualization."

And it is not:
"An AI chatbot for transit."

It is:
A computational experimentation platform for urban public-transit networks.

Its core loop is:
REAL DATA
   ↓
MODEL
   ↓
ROUTE
   ↓
GENERATE DEMAND
   ↓
ASSIGN
   ↓
SIMULATE
   ↓
MODIFY
   ↓
RE-SIMULATE
   ↓
COMPARE
   ↓
OPTIMIZE

The strongest part of the project is therefore not the React UI.
It is the underlying pipeline:
GTFS + OSM + Population + Employment Proxy
                    ↓
             Canonical Network
                    ↓
             Rust RAPTOR
                    ↓
          Synthetic OD Demand
                    ↓
          Passenger Assignment
                    ↓
          Capacity / Crowding
                    ↓
             Scenario Engine
                    ↓
        Accessibility Analytics
                    ↓
              Visualization

That is the technical identity of Glacies.
