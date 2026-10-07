//! Flat, cache-friendly timetable for RAPTOR (Delling, Pajor, Werneck 2012, §3).
//!
//! A RAPTOR *route* is a set of trips that visit exactly the same stop sequence and never
//! overtake each other (FIFO). Every array is a flat `Vec` addressed through offsets, so there
//! are no per-stop or per-trip heap objects.

use std::collections::BTreeMap;
use std::fmt;

use crate::{RouteIdx, StopIdx, Time};

/// One scheduled trip, as handed to the builder.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TripInput {
    /// Caller's identifier (e.g. the canonical `trip_idx`), returned in journeys.
    pub trip_id: u32,
    pub stops: Vec<StopIdx>,
    pub arrivals: Vec<Time>,
    pub departures: Vec<Time>,
}

/// Why a trip or footpath was rejected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BuildError {
    TooFewStops { trip_id: u32 },
    LengthMismatch { trip_id: u32 },
    UnknownStop { trip_id: u32, stop: StopIdx },
    ArrivalAfterDeparture { trip_id: u32, position: usize },
    TimeGoesBackwards { trip_id: u32, position: usize },
    DuplicateTripId { trip_id: u32 },
    UnknownFootpathStop { stop: StopIdx },
    UnknownEntryStop { stop: StopIdx },
}

impl fmt::Display for BuildError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TooFewStops { trip_id } => write!(f, "trip {trip_id} has fewer than 2 stops"),
            Self::LengthMismatch { trip_id } => {
                write!(f, "trip {trip_id}: stops, arrivals and departures differ in length")
            }
            Self::UnknownStop { trip_id, stop } => {
                write!(f, "trip {trip_id} visits unknown stop {}", stop.0)
            }
            Self::ArrivalAfterDeparture { trip_id, position } => {
                write!(f, "trip {trip_id}: arrival after departure at position {position}")
            }
            Self::TimeGoesBackwards { trip_id, position } => {
                write!(f, "trip {trip_id}: time goes backwards at position {position}")
            }
            Self::DuplicateTripId { trip_id } => write!(f, "trip id {trip_id} added twice"),
            Self::UnknownFootpathStop { stop } => {
                write!(f, "footpath references unknown stop {}", stop.0)
            }
            Self::UnknownEntryStop { stop } => {
                write!(f, "station entry set for unknown stop {}", stop.0)
            }
        }
    }
}

impl std::error::Error for BuildError {}

/// A walking connection between two stops, in seconds.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Footpath {
    pub to: StopIdx,
    pub duration: u32,
}

/// Facts about the build worth reporting (e.g. in a build report).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct BuildReport {
    /// Extra routes created because trips with the same stop sequence overtook each other.
    pub overtaking_splits: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct RouteInfo {
    stops_start: u32,
    stop_count: u32,
    trips_start: u32,
    trip_count: u32,
    times_start: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct StopTime {
    arrival: Time,
    departure: Time,
}

/// Immutable timetable; build it with [`TimetableBuilder`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Timetable {
    stop_count: u32,
    routes: Vec<RouteInfo>,
    route_stops: Vec<StopIdx>,
    /// Per route: `trip_count` rows of `stop_count` stop times, trip-major.
    stop_times: Vec<StopTime>,
    trip_ids: Vec<u32>,
    /// CSR: `stop_routes[stop_routes_start[s]..stop_routes_start[s + 1]]`.
    stop_routes_start: Vec<u32>,
    stop_routes: Vec<(RouteIdx, u32)>,
    footpaths_start: Vec<u32>,
    footpaths: Vec<Footpath>,
    /// Per stop: seconds to enter it on foot from outside its station, and the station.
    entry: Vec<StationEntry>,
}

/// Read-only view of one route.
#[derive(Debug, Clone, Copy)]
pub struct RouteView<'a> {
    tt: &'a Timetable,
    info: RouteInfo,
}

impl RouteView<'_> {
    #[must_use]
    pub fn stops(&self) -> &[StopIdx] {
        let start = self.info.stops_start as usize;
        &self.tt.route_stops[start..start + self.info.stop_count as usize]
    }

    #[must_use]
    pub fn trip_count(&self) -> usize {
        self.info.trip_count as usize
    }

    /// The caller's id of the `trip`-th trip (trips are ordered by departure).
    #[must_use]
    pub fn trip_id(&self, trip: usize) -> u32 {
        self.tt.trip_ids[self.info.trips_start as usize + trip]
    }

    #[must_use]
    pub fn arrival(&self, trip: usize, position: usize) -> Time {
        self.stop_time(trip, position).arrival
    }

    #[must_use]
    pub fn departure(&self, trip: usize, position: usize) -> Time {
        self.stop_time(trip, position).departure
    }

    /// The first trip among `0..before` that departs `position` at or after `ready`.
    ///
    /// Routes are FIFO, so departures at any position are sorted by trip and a binary search
    /// suffices.
    #[must_use]
    pub fn earliest_trip(&self, position: usize, ready: Time, before: usize) -> Option<usize> {
        let (mut lo, mut hi) = (0, before.min(self.trip_count()));
        while lo < hi {
            let mid = lo + (hi - lo) / 2;
            if self.departure(mid, position) < ready {
                lo = mid + 1;
            } else {
                hi = mid;
            }
        }
        (lo < before.min(self.trip_count())).then_some(lo)
    }

    fn stop_time(&self, trip: usize, position: usize) -> StopTime {
        let stops = self.info.stop_count as usize;
        debug_assert!(trip < self.trip_count() && position < stops);
        self.tt.stop_times[self.info.times_start as usize + trip * stops + position]
    }
}

impl Timetable {
    #[must_use]
    pub fn stop_count(&self) -> usize {
        self.stop_count as usize
    }

    #[must_use]
    pub fn route_count(&self) -> usize {
        self.routes.len()
    }

    #[must_use]
    pub fn trip_count(&self) -> usize {
        self.trip_ids.len()
    }

    /// # Panics
    /// If `route` is out of range.
    #[must_use]
    pub fn route(&self, route: RouteIdx) -> RouteView<'_> {
        RouteView { tt: self, info: self.routes[route.0 as usize] }
    }

    /// `(route, position)` for every route calling at `stop`, ordered by route then position.
    ///
    /// # Panics
    /// If `stop` is out of range.
    #[must_use]
    pub fn routes_serving(&self, stop: StopIdx) -> &[(RouteIdx, u32)] {
        let s = stop.0 as usize;
        &self.stop_routes
            [self.stop_routes_start[s] as usize..self.stop_routes_start[s + 1] as usize]
    }

    /// Walking connections leaving `stop`, ordered by destination.
    ///
    /// # Panics
    /// If `stop` is out of range.
    #[must_use]
    pub fn footpaths(&self, stop: StopIdx) -> &[Footpath] {
        let s = stop.0 as usize;
        &self.footpaths[self.footpaths_start[s] as usize..self.footpaths_start[s + 1] as usize]
    }

    /// Seconds to enter `stop` on foot from the origin or from outside its station (e.g. a
    /// metro station's entrance, security check and stairs); 0 unless set with
    /// [`TimetableBuilder::set_station_entry`].
    ///
    /// # Panics
    /// If `stop` is out of range.
    #[must_use]
    pub fn entry_time(&self, stop: StopIdx) -> u32 {
        self.entry[stop.0 as usize].seconds
    }

    /// Entry seconds for a footpath `from -> to`: free within one stop or one station.
    ///
    /// # Panics
    /// If either stop is out of range.
    #[must_use]
    pub fn entry_time_from(&self, from: StopIdx, to: StopIdx) -> u32 {
        let (a, b) = (self.entry[from.0 as usize], self.entry[to.0 as usize]);
        let same_station = a.station.is_some() && a.station == b.station;
        if from == to || same_station {
            0
        } else {
            b.seconds
        }
    }
}

/// Collects trips and footpaths, then lays them out as a [`Timetable`].
#[derive(Debug, Clone, Default)]
pub struct TimetableBuilder {
    stop_count: u32,
    trips: Vec<TripInput>,
    trip_ids: std::collections::BTreeSet<u32>,
    footpaths: Vec<(StopIdx, Footpath)>,
    entry: BTreeMap<StopIdx, StationEntry>,
}

/// Station membership of a stop and the time to enter it from outside.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct StationEntry {
    station: Option<u32>,
    seconds: u32,
}

impl TimetableBuilder {
    #[must_use]
    pub fn new(stop_count: u32) -> Self {
        Self { stop_count, ..Self::default() }
    }

    /// Validate and add one trip.
    ///
    /// # Errors
    /// If the trip has fewer than two stops, inconsistent lengths, unknown stops, an arrival
    /// after its departure, times that go backwards, or a trip id that was already added.
    pub fn add_trip(&mut self, trip: TripInput) -> Result<(), BuildError> {
        let trip_id = trip.trip_id;
        let n = trip.stops.len();
        if n < 2 {
            return Err(BuildError::TooFewStops { trip_id });
        }
        if trip.arrivals.len() != n || trip.departures.len() != n {
            return Err(BuildError::LengthMismatch { trip_id });
        }
        if let Some(&stop) = trip.stops.iter().find(|s| s.0 >= self.stop_count) {
            return Err(BuildError::UnknownStop { trip_id, stop });
        }
        for position in 0..n {
            if trip.arrivals[position] > trip.departures[position] {
                return Err(BuildError::ArrivalAfterDeparture { trip_id, position });
            }
            if position > 0 && trip.arrivals[position] < trip.departures[position - 1] {
                return Err(BuildError::TimeGoesBackwards { trip_id, position });
            }
        }
        if !self.trip_ids.insert(trip_id) {
            return Err(BuildError::DuplicateTripId { trip_id });
        }
        self.trips.push(trip);
        Ok(())
    }

    /// Add a one-way walking connection.
    ///
    /// # Errors
    /// If either stop is unknown.
    pub fn add_footpath(
        &mut self,
        from: StopIdx,
        to: StopIdx,
        duration: u32,
    ) -> Result<(), BuildError> {
        for stop in [from, to] {
            if stop.0 >= self.stop_count {
                return Err(BuildError::UnknownFootpathStop { stop });
            }
        }
        self.footpaths.push((from, Footpath { to, duration }));
        Ok(())
    }

    /// Make `stop` part of `station` (any id shared by its platforms) and charge `seconds`
    /// whenever it is reached on foot from the origin or from a stop outside that station.
    /// Changing vehicles within the station is free. A later call replaces the setting.
    ///
    /// # Errors
    /// If the stop is unknown.
    pub fn set_station_entry(
        &mut self,
        stop: StopIdx,
        station: u32,
        seconds: u32,
    ) -> Result<(), BuildError> {
        if stop.0 >= self.stop_count {
            return Err(BuildError::UnknownEntryStop { stop });
        }
        self.entry.insert(stop, StationEntry { station: Some(station), seconds });
        Ok(())
    }

    /// Lay out the timetable. The result depends only on the set of trips and footpaths
    /// added, not on the order they were added in.
    ///
    /// # Panics
    /// If the network exceeds `u32` indices (billions of stop times).
    #[must_use]
    pub fn build(self) -> (Timetable, BuildReport) {
        let mut report = BuildReport::default();

        // Group by stop sequence; BTreeMap keeps routes in a deterministic order.
        let mut by_sequence: BTreeMap<Vec<StopIdx>, Vec<TripInput>> = BTreeMap::new();
        for trip in self.trips {
            by_sequence.entry(trip.stops.clone()).or_default().push(trip);
        }

        let mut routes = Vec::new();
        let mut route_stops = Vec::new();
        let mut stop_times = Vec::new();
        let mut trip_ids = Vec::new();
        for (stops, mut trips) in by_sequence {
            trips.sort_by(|a, b| {
                (&a.departures, &a.arrivals, a.trip_id).cmp(&(
                    &b.departures,
                    &b.arrivals,
                    b.trip_id,
                ))
            });
            let groups = split_fifo(trips);
            report.overtaking_splits += groups.len() - 1;
            for group in groups {
                routes.push(RouteInfo {
                    stops_start: to_u32(route_stops.len()),
                    stop_count: to_u32(stops.len()),
                    trips_start: to_u32(trip_ids.len()),
                    trip_count: to_u32(group.len()),
                    times_start: to_u32(stop_times.len()),
                });
                route_stops.extend_from_slice(&stops);
                for trip in group {
                    trip_ids.push(trip.trip_id);
                    stop_times.extend(
                        trip.arrivals
                            .iter()
                            .zip(&trip.departures)
                            .map(|(&arrival, &departure)| StopTime { arrival, departure }),
                    );
                }
            }
        }

        let n = self.stop_count as usize;
        let mut serving: Vec<Vec<(RouteIdx, u32)>> = vec![Vec::new(); n];
        for (r, info) in routes.iter().enumerate() {
            let start = info.stops_start as usize;
            for (position, stop) in
                route_stops[start..start + info.stop_count as usize].iter().enumerate()
            {
                serving[stop.0 as usize].push((RouteIdx(to_u32(r)), to_u32(position)));
            }
        }
        let (stop_routes_start, stop_routes) = to_csr(serving);

        let mut walks: Vec<Vec<Footpath>> = vec![Vec::new(); n];
        for (from, footpath) in self.footpaths {
            walks[from.0 as usize].push(footpath);
        }
        for list in &mut walks {
            list.sort_unstable();
        }
        let (footpaths_start, footpaths) = to_csr(walks);

        let mut entry = vec![StationEntry::default(); n];
        for (stop, setting) in self.entry {
            entry[stop.0 as usize] = setting;
        }

        let timetable = Timetable {
            stop_count: self.stop_count,
            routes,
            route_stops,
            stop_times,
            trip_ids,
            stop_routes_start,
            stop_routes,
            footpaths_start,
            footpaths,
            entry,
        };
        (timetable, report)
    }
}

/// Partition trips (sorted by departure) into groups in which no trip overtakes another.
///
/// Greedy first fit: each trip joins the first group whose last trip it does not overtake,
/// i.e. it is no earlier at any stop. Sorted input makes the result deterministic.
fn split_fifo(trips: Vec<TripInput>) -> Vec<Vec<TripInput>> {
    let mut groups: Vec<Vec<TripInput>> = Vec::new();
    for trip in trips {
        let fits = |group: &Vec<TripInput>| {
            group.last().is_some_and(|last| {
                last.departures.iter().zip(&trip.departures).all(|(a, b)| a <= b)
                    && last.arrivals.iter().zip(&trip.arrivals).all(|(a, b)| a <= b)
            })
        };
        match groups.iter_mut().find(|g| fits(g)) {
            Some(group) => group.push(trip),
            None => groups.push(vec![trip]),
        }
    }
    groups
}

fn to_csr<T>(lists: Vec<Vec<T>>) -> (Vec<u32>, Vec<T>) {
    let mut starts = Vec::with_capacity(lists.len() + 1);
    let mut flat = Vec::new();
    starts.push(0);
    for list in lists {
        flat.extend(list);
        starts.push(to_u32(flat.len()));
    }
    (starts, flat)
}

fn to_u32(value: usize) -> u32 {
    u32::try_from(value).expect("timetable exceeds u32 indices")
}
