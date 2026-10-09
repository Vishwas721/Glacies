//! Python bindings (`import glacies_raptor`). Arrays cross the boundary as `NumPy` arrays;
//! long-running searches release the GIL and parallelise with Rayon. Times are seconds since
//! service-day midnight; `UNREACHED` marks stops that cannot be reached.

// PyO3 extracts each Python argument into an owned value before calling the method, so
// arguments cannot be taken by reference.
#![allow(clippy::needless_pass_by_value)]

use ::glacies_raptor as core;
use numpy::ndarray::Array2;
use numpy::{IntoPyArray, PyArray1, PyArray2, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

type U32Array<'py> = Bound<'py, PyArray1<u32>>;
type F64Array<'py> = Bound<'py, PyArray1<f64>>;

fn value_error(err: impl std::fmt::Display) -> PyErr {
    PyValueError::new_err(err.to_string())
}

fn slice<'a, T: numpy::Element>(
    array: &'a PyReadonlyArray1<'_, T>,
    name: &str,
) -> PyResult<&'a [T]> {
    array.as_slice().map_err(|_| value_error(format!("{name} must be a contiguous 1-D array")))
}

fn accesses(stops: &[u32], seconds: &[u32], what: &str) -> PyResult<Vec<core::Access>> {
    if stops.len() != seconds.len() {
        return Err(value_error(format!("{what}: stops and seconds differ in length")));
    }
    Ok(stops
        .iter()
        .zip(seconds)
        .map(|(&stop, &duration)| core::Access { stop: core::StopIdx(stop), duration })
        .collect())
}

/// Zone egress walks from `(zone, stop, seconds)` columns.
fn zone_egress(
    stop_count: usize,
    zone_count: usize,
    zones: &PyReadonlyArray1<'_, u32>,
    stops: &PyReadonlyArray1<'_, u32>,
    seconds: &PyReadonlyArray1<'_, u32>,
) -> PyResult<core::ZoneEgress> {
    let (ez, es, esec) = (
        slice(zones, "egress_zones")?,
        slice(stops, "egress_stops")?,
        slice(seconds, "egress_seconds")?,
    );
    if es.len() != ez.len() || esec.len() != ez.len() {
        return Err(value_error("egress arrays differ in length"));
    }
    if let Some(&stop) = es.iter().find(|&&s| s as usize >= stop_count) {
        return Err(value_error(format!("egress references unknown stop {stop}")));
    }
    let walks: Vec<(u32, core::StopIdx, u32)> = ez
        .iter()
        .zip(es)
        .zip(esec)
        .map(|((&zone, &stop), &seconds)| (zone, core::StopIdx(stop), seconds))
        .collect();
    core::ZoneEgress::new(zone_count, &walks).map_err(value_error)
}

fn params(max_rounds: usize, min_transfer_time: u32) -> core::Params {
    core::Params { max_rounds, min_transfer_time }
}

/// One leg of a journey; fields that do not apply to the leg's kind are `None`.
#[pyclass(frozen, get_all, skip_from_py_object, module = "glacies_raptor")]
#[derive(Clone)]
struct Leg {
    kind: &'static str,
    from_stop: Option<u32>,
    to_stop: Option<u32>,
    duration: u32,
    route: Option<u32>,
    trip_id: Option<u32>,
    board: Option<u32>,
    alight: Option<u32>,
}

impl From<core::Leg> for Leg {
    fn from(leg: core::Leg) -> Self {
        let blank = Self {
            kind: "",
            from_stop: None,
            to_stop: None,
            duration: 0,
            route: None,
            trip_id: None,
            board: None,
            alight: None,
        };
        match leg {
            core::Leg::Access { to, duration } => {
                Self { kind: "access", to_stop: Some(to.0), duration, ..blank }
            }
            core::Leg::Egress { from, duration } => {
                Self { kind: "egress", from_stop: Some(from.0), duration, ..blank }
            }
            core::Leg::Transfer { from, to, duration } => Self {
                kind: "transfer",
                from_stop: Some(from.0),
                to_stop: Some(to.0),
                duration,
                ..blank
            },
            core::Leg::Ride { route, trip_id, from, to, board, alight } => Self {
                kind: "ride",
                from_stop: Some(from.0),
                to_stop: Some(to.0),
                duration: alight.0 - board.0,
                route: Some(route.0),
                trip_id: Some(trip_id),
                board: Some(board.0),
                alight: Some(alight.0),
            },
        }
    }
}

#[pymethods]
impl Leg {
    fn __repr__(&self) -> String {
        format!(
            "Leg({}, from={:?}, to={:?}, duration={}s, trip={:?})",
            self.kind, self.from_stop, self.to_stop, self.duration, self.trip_id
        )
    }
}

/// A depart-at journey (Simulated).
#[pyclass(frozen, get_all, module = "glacies_raptor")]
struct Journey {
    departure: u32,
    arrival: u32,
    travel_time: u32,
    transfers: usize,
    walking_time: u32,
    in_vehicle_time: u32,
    waiting_time: u32,
    legs: Vec<Leg>,
}

impl From<&core::Journey> for Journey {
    fn from(j: &core::Journey) -> Self {
        Self {
            departure: j.departure.0,
            arrival: j.arrival.0,
            travel_time: j.travel_time(),
            transfers: j.transfers(),
            walking_time: j.walking_time(),
            in_vehicle_time: j.in_vehicle_time(),
            waiting_time: j.waiting_time(),
            legs: j.legs.iter().copied().map(Leg::from).collect(),
        }
    }
}

#[pymethods]
impl Journey {
    fn __repr__(&self) -> String {
        format!(
            "Journey(travel_time={}s, transfers={}, walking={}s, waiting={}s, legs={})",
            self.travel_time,
            self.transfers,
            self.walking_time,
            self.waiting_time,
            self.legs.len()
        )
    }
}

/// The RAPTOR timetable. Build it once per network, then query it many times.
#[pyclass(frozen, module = "glacies_raptor")]
struct Timetable {
    inner: core::Timetable,
    overtaking_splits: usize,
}

#[pymethods]
impl Timetable {
    /// Trips are given in CSR form: trip `i` visits `stops[trip_starts[i]:trip_starts[i+1]]`.
    /// `entry_stops`/`entry_stations`/`entry_seconds` make stops platforms of a station and set
    /// the time to walk onto them from outside it (e.g. metro security); changes within a
    /// station are free. Other stops need no entry time.
    #[staticmethod]
    #[pyo3(signature = (
        stop_count, trip_ids, trip_starts, stops, arrivals, departures,
        footpath_from, footpath_to, footpath_seconds,
        entry_stops=None, entry_stations=None, entry_seconds=None,
    ))]
    #[allow(clippy::too_many_arguments)] // mirrors the columnar layout of the inputs
    fn build(
        py: Python<'_>,
        stop_count: u32,
        trip_ids: PyReadonlyArray1<'_, u32>,
        trip_starts: PyReadonlyArray1<'_, u32>,
        stops: PyReadonlyArray1<'_, u32>,
        arrivals: PyReadonlyArray1<'_, u32>,
        departures: PyReadonlyArray1<'_, u32>,
        footpath_from: PyReadonlyArray1<'_, u32>,
        footpath_to: PyReadonlyArray1<'_, u32>,
        footpath_seconds: PyReadonlyArray1<'_, u32>,
        entry_stops: Option<PyReadonlyArray1<'_, u32>>,
        entry_stations: Option<PyReadonlyArray1<'_, u32>>,
        entry_seconds: Option<PyReadonlyArray1<'_, u32>>,
    ) -> PyResult<Self> {
        let ids = slice(&trip_ids, "trip_ids")?;
        let starts = slice(&trip_starts, "trip_starts")?;
        let (stops, arr, dep) = (
            slice(&stops, "stops")?,
            slice(&arrivals, "arrivals")?,
            slice(&departures, "departures")?,
        );
        let (fp_from, fp_to, fp_s) = (
            slice(&footpath_from, "footpath_from")?,
            slice(&footpath_to, "footpath_to")?,
            slice(&footpath_seconds, "footpath_seconds")?,
        );
        if starts.len() != ids.len() + 1 || starts.last().map(|&s| s as usize) != Some(stops.len())
        {
            return Err(value_error(
                "trip_starts must have len(trip_ids) + 1 entries ending at len(stops)",
            ));
        }
        if arr.len() != stops.len() || dep.len() != stops.len() {
            return Err(value_error("stops, arrivals and departures differ in length"));
        }
        if fp_to.len() != fp_from.len() || fp_s.len() != fp_from.len() {
            return Err(value_error("footpath arrays differ in length"));
        }
        let (entry_at, entry_in, entry_s) = match (&entry_stops, &entry_stations, &entry_seconds) {
            (Some(stops), Some(stations), Some(seconds)) => (
                slice(stops, "entry_stops")?,
                slice(stations, "entry_stations")?,
                slice(seconds, "entry_seconds")?,
            ),
            (None, None, None) => (&[][..], &[][..], &[][..]),
            _ => {
                return Err(value_error(
                    "give all of entry_stops, entry_stations and entry_seconds, or none",
                ))
            }
        };
        if entry_in.len() != entry_at.len() || entry_s.len() != entry_at.len() {
            return Err(value_error("entry arrays differ in length"));
        }
        let to_time = |values: &[u32]| values.iter().map(|&v| core::Time(v)).collect::<Vec<_>>();
        py.detach(|| {
            let mut builder = core::TimetableBuilder::new(stop_count);
            for (i, &trip_id) in ids.iter().enumerate() {
                let range = starts[i] as usize..starts[i + 1] as usize;
                builder
                    .add_trip(core::TripInput {
                        trip_id,
                        stops: stops[range.clone()].iter().map(|&s| core::StopIdx(s)).collect(),
                        arrivals: to_time(&arr[range.clone()]),
                        departures: to_time(&dep[range]),
                    })
                    .map_err(value_error)?;
            }
            for ((&from, &to), &seconds) in fp_from.iter().zip(fp_to).zip(fp_s) {
                builder
                    .add_footpath(core::StopIdx(from), core::StopIdx(to), seconds)
                    .map_err(value_error)?;
            }
            for ((&stop, &station), &seconds) in entry_at.iter().zip(entry_in).zip(entry_s) {
                builder
                    .set_station_entry(core::StopIdx(stop), station, seconds)
                    .map_err(value_error)?;
            }
            let (inner, report) = builder.build();
            Ok(Self { inner, overtaking_splits: report.overtaking_splits })
        })
    }

    #[getter]
    fn stop_count(&self) -> usize {
        self.inner.stop_count()
    }

    #[getter]
    fn route_count(&self) -> usize {
        self.inner.route_count()
    }

    #[getter]
    fn trip_count(&self) -> usize {
        self.inner.trip_count()
    }

    /// Extra routes created because trips with the same stop sequence overtook each other.
    #[getter]
    fn overtaking_splits(&self) -> usize {
        self.overtaking_splits
    }

    /// Seconds to walk onto each stop from outside its station.
    fn entry_times<'py>(&self, py: Python<'py>) -> U32Array<'py> {
        let n = u32::try_from(self.inner.stop_count()).expect("stop count fits u32");
        let times: Vec<u32> = (0..n).map(|s| self.inner.entry_time(core::StopIdx(s))).collect();
        times.into_pyarray(py)
    }

    /// Earliest arrival at every stop (`UNREACHED` if none) leaving at `departure`.
    #[pyo3(signature = (origin_stops, origin_seconds, departure, max_rounds, min_transfer_time))]
    fn earliest_arrivals<'py>(
        &self,
        py: Python<'py>,
        origin_stops: PyReadonlyArray1<'_, u32>,
        origin_seconds: PyReadonlyArray1<'_, u32>,
        departure: u32,
        max_rounds: usize,
        min_transfer_time: u32,
    ) -> PyResult<Bound<'py, PyArray1<u32>>> {
        let origins = accesses(
            slice(&origin_stops, "origin_stops")?,
            slice(&origin_seconds, "origin_seconds")?,
            "origins",
        )?;
        let p = params(max_rounds, min_transfer_time);
        let arrivals: Vec<u32> = py.detach(|| {
            let profile = core::search(&self.inner, &p, &origins, core::Time(departure), &[]);
            (0..self.inner.stop_count())
                .map(|s| {
                    let stop = core::StopIdx(u32::try_from(s).expect("u32 stops"));
                    profile.earliest_arrival(stop).map_or(core::Time::UNREACHED.0, |t| t.0)
                })
                .collect()
        });
        Ok(arrivals.into_pyarray(py))
    }

    /// Earliest arrivals for many departure times: shape `(len(departures), stop_count)`.
    #[pyo3(signature = (origin_stops, origin_seconds, departures, max_rounds, min_transfer_time))]
    fn range_arrivals<'py>(
        &self,
        py: Python<'py>,
        origin_stops: PyReadonlyArray1<'_, u32>,
        origin_seconds: PyReadonlyArray1<'_, u32>,
        departures: PyReadonlyArray1<'_, u32>,
        max_rounds: usize,
        min_transfer_time: u32,
    ) -> PyResult<Bound<'py, PyArray2<u32>>> {
        let origins = accesses(
            slice(&origin_stops, "origin_stops")?,
            slice(&origin_seconds, "origin_seconds")?,
            "origins",
        )?;
        let times: Vec<core::Time> =
            slice(&departures, "departures")?.iter().map(|&d| core::Time(d)).collect();
        let p = params(max_rounds, min_transfer_time);
        let n = self.inner.stop_count();
        let flat: Vec<u32> = py.detach(|| {
            let profile = core::range_search(&self.inner, &p, &origins, &times);
            (0..times.len())
                .flat_map(|i| profile.arrivals(i).iter().map(|t| t.0).collect::<Vec<_>>())
                .collect()
        });
        let array = Array2::from_shape_vec((times.len(), n), flat).map_err(value_error)?;
        Ok(array.into_pyarray(py))
    }

    /// Travel-time percentiles from many origins to zones, in parallel (Phase 3 M2).
    ///
    /// Each origin is `(access stops, access seconds, walk-only zones, walk-only seconds)`.
    /// Zone egress walks are `(zone, stop, seconds)` triples. Returns `(origin, zone, times)`:
    /// the origin's position in `origins`, the zone, and one row of `percentiles` seconds per
    /// reached zone (`UNREACHED` = above `max_travel_time`), ordered by origin then zone.
    #[pyo3(signature = (
        origins, departures, zone_count, egress_zones, egress_stops, egress_seconds,
        percentiles, max_travel_time, max_rounds, min_transfer_time,
    ))]
    #[allow(clippy::too_many_arguments)] // mirrors the columnar layout of the inputs
    #[allow(clippy::type_complexity)] // one tuple of arrays per origin
    fn zone_travel_times_many<'py>(
        &self,
        py: Python<'py>,
        origins: Vec<(
            PyReadonlyArray1<'py, u32>,
            PyReadonlyArray1<'py, u32>,
            PyReadonlyArray1<'py, u32>,
            PyReadonlyArray1<'py, u32>,
        )>,
        departures: PyReadonlyArray1<'_, u32>,
        zone_count: usize,
        egress_zones: PyReadonlyArray1<'_, u32>,
        egress_stops: PyReadonlyArray1<'_, u32>,
        egress_seconds: PyReadonlyArray1<'_, u32>,
        percentiles: PyReadonlyArray1<'_, u8>,
        max_travel_time: u32,
        max_rounds: usize,
        min_transfer_time: u32,
    ) -> PyResult<(U32Array<'py>, U32Array<'py>, Bound<'py, PyArray2<u32>>)> {
        let (ez, es, esec) = (
            slice(&egress_zones, "egress_zones")?,
            slice(&egress_stops, "egress_stops")?,
            slice(&egress_seconds, "egress_seconds")?,
        );
        if es.len() != ez.len() || esec.len() != ez.len() {
            return Err(value_error("egress arrays differ in length"));
        }
        let stop_count = self.inner.stop_count();
        if let Some(&stop) = es.iter().find(|&&s| s as usize >= stop_count) {
            return Err(value_error(format!("egress references unknown stop {stop}")));
        }
        let walks: Vec<(u32, core::StopIdx, u32)> = ez
            .iter()
            .zip(es)
            .zip(esec)
            .map(|((&zone, &stop), &seconds)| (zone, core::StopIdx(stop), seconds))
            .collect();
        let egress = core::ZoneEgress::new(zone_count, &walks).map_err(value_error)?;
        let sets = origins
            .iter()
            .map(|(stops, seconds, zones, walk_seconds)| {
                let access = accesses(
                    slice(stops, "access stops")?,
                    slice(seconds, "access seconds")?,
                    "origins",
                )?;
                if let Some(&stop) = access.iter().find(|a| a.stop.0 as usize >= stop_count) {
                    return Err(value_error(format!(
                        "origin references unknown stop {}",
                        stop.stop.0
                    )));
                }
                let (zones, walk_seconds) =
                    (slice(zones, "walk-only zones")?, slice(walk_seconds, "walk-only seconds")?);
                if zones.len() != walk_seconds.len() {
                    return Err(value_error("walk-only zones and seconds differ in length"));
                }
                Ok((access, zones.iter().copied().zip(walk_seconds.iter().copied()).collect()))
            })
            .collect::<PyResult<Vec<(Vec<core::Access>, Vec<(u32, u32)>)>>>()?;
        let times: Vec<core::Time> =
            slice(&departures, "departures")?.iter().map(|&d| core::Time(d)).collect();
        let wanted = slice(&percentiles, "percentiles")?.to_vec();
        let p = params(max_rounds, min_transfer_time);
        let results = py
            .detach(|| {
                sets.par_iter()
                    .map(|(access, walk_only)| {
                        core::zone_travel_times(
                            &self.inner,
                            &p,
                            access,
                            &times,
                            &egress,
                            walk_only,
                            &wanted,
                            max_travel_time,
                        )
                    })
                    .collect::<Result<Vec<_>, _>>()
            })
            .map_err(value_error)?;
        let (mut origin, mut zone, mut flat) = (Vec::new(), Vec::new(), Vec::new());
        for (i, result) in results.into_iter().enumerate() {
            let i = u32::try_from(i).map_err(value_error)?;
            origin.extend(std::iter::repeat_n(i, result.zones.len()));
            zone.extend(result.zones);
            flat.extend(result.times);
        }
        let rows = zone.len();
        let matrix = Array2::from_shape_vec((rows, wanted.len()), flat)
            .map_err(value_error)?
            .into_pyarray(py);
        Ok((origin.into_pyarray(py), zone.into_pyarray(py), matrix))
    }

    /// Metro gate segments of the best journeys from many origins to their target zones, in
    /// parallel (Phase 5 M3).
    ///
    /// Each origin is `(access stops, access seconds, walk-only zones, walk-only seconds,
    /// target zones)`. `metro_trip` flags trips by id (1 = metro); `station` gives each stop's
    /// station or `UNREACHED` outside the metro. Returns `(origin, zone, reached, walked,
    /// metro)` per target and `(origin, zone, entry, exit, departures)` per segment, ordered by origin.
    #[pyo3(signature = (
        origins, departures, zone_count, egress_zones, egress_stops, egress_seconds,
        metro_trip, station, max_travel_time, max_rounds, min_transfer_time,
    ))]
    #[allow(clippy::too_many_arguments)] // mirrors the columnar layout of the inputs
    #[allow(clippy::type_complexity)] // one tuple of arrays per origin, nine arrays back
    fn zone_paths_many<'py>(
        &self,
        py: Python<'py>,
        origins: Vec<(
            PyReadonlyArray1<'py, u32>,
            PyReadonlyArray1<'py, u32>,
            PyReadonlyArray1<'py, u32>,
            PyReadonlyArray1<'py, u32>,
            PyReadonlyArray1<'py, u32>,
        )>,
        departures: PyReadonlyArray1<'_, u32>,
        zone_count: usize,
        egress_zones: PyReadonlyArray1<'_, u32>,
        egress_stops: PyReadonlyArray1<'_, u32>,
        egress_seconds: PyReadonlyArray1<'_, u32>,
        metro_trip: PyReadonlyArray1<'_, u8>,
        station: PyReadonlyArray1<'_, u32>,
        max_travel_time: u32,
        max_rounds: usize,
        min_transfer_time: u32,
    ) -> PyResult<(
        (U32Array<'py>, U32Array<'py>, U32Array<'py>, U32Array<'py>, U32Array<'py>),
        (U32Array<'py>, U32Array<'py>, U32Array<'py>, U32Array<'py>, U32Array<'py>),
    )> {
        let stop_count = self.inner.stop_count();
        let egress =
            zone_egress(stop_count, zone_count, &egress_zones, &egress_stops, &egress_seconds)?;
        let station = slice(&station, "station")?.to_vec();
        if station.len() != stop_count {
            return Err(value_error("station must have one entry per stop"));
        }
        let metro = core::MetroNetwork {
            metro_trip: slice(&metro_trip, "metro_trip")?.iter().map(|&m| m != 0).collect(),
            station, // UNREACHED (u32::MAX) is NO_STATION
        };
        let sets = origins
            .iter()
            .map(|(stops, seconds, zones, walk_seconds, targets)| {
                let access = accesses(
                    slice(stops, "access stops")?,
                    slice(seconds, "access seconds")?,
                    "origins",
                )?;
                if let Some(&stop) = access.iter().find(|a| a.stop.0 as usize >= stop_count) {
                    return Err(value_error(format!(
                        "origin references unknown stop {}",
                        stop.stop.0
                    )));
                }
                let (zones, walk_seconds) =
                    (slice(zones, "walk-only zones")?, slice(walk_seconds, "walk-only seconds")?);
                if zones.len() != walk_seconds.len() {
                    return Err(value_error("walk-only zones and seconds differ in length"));
                }
                Ok((
                    access,
                    zones.iter().copied().zip(walk_seconds.iter().copied()).collect(),
                    slice(targets, "targets")?.to_vec(),
                ))
            })
            .collect::<PyResult<Vec<(Vec<core::Access>, Vec<(u32, u32)>, Vec<u32>)>>>()?;
        let times: Vec<core::Time> =
            slice(&departures, "departures")?.iter().map(|&d| core::Time(d)).collect();
        let p = params(max_rounds, min_transfer_time);
        let results = py
            .detach(|| {
                sets.par_iter()
                    .map(|(access, walk_only, targets)| {
                        core::zone_paths(
                            &self.inner,
                            &p,
                            access,
                            &times,
                            &egress,
                            walk_only,
                            targets,
                            &metro,
                            max_travel_time,
                        )
                    })
                    .collect::<Result<Vec<_>, _>>()
            })
            .map_err(value_error)?;
        let (mut origin, mut zone, mut reached, mut walked, mut used) =
            (Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new());
        let (mut s_origin, mut s_zone, mut entry, mut exit, mut count) =
            (Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new());
        for (i, result) in results.into_iter().enumerate() {
            let i = u32::try_from(i).map_err(value_error)?;
            origin.extend(std::iter::repeat_n(i, result.zones.len()));
            for &(pos, from, to, n) in &result.segments {
                s_origin.push(i);
                s_zone.push(result.zones[pos as usize]);
                entry.push(from);
                exit.push(to);
                count.push(n);
            }
            zone.extend(result.zones);
            reached.extend(result.reached);
            walked.extend(result.walked);
            used.extend(result.metro);
        }
        Ok((
            (
                origin.into_pyarray(py),
                zone.into_pyarray(py),
                reached.into_pyarray(py),
                walked.into_pyarray(py),
                used.into_pyarray(py),
            ),
            (
                s_origin.into_pyarray(py),
                s_zone.into_pyarray(py),
                entry.into_pyarray(py),
                exit.into_pyarray(py),
                count.into_pyarray(py),
            ),
        ))
    }

    /// `range_arrivals` for many origins in parallel: shape `(origins, departures, stops)`
    /// returned as a list of 2-D arrays in the order of `origins`.
    #[pyo3(signature = (origins, departures, max_rounds, min_transfer_time))]
    fn range_arrivals_many<'py>(
        &self,
        py: Python<'py>,
        origins: Vec<(PyReadonlyArray1<'py, u32>, PyReadonlyArray1<'py, u32>)>,
        departures: PyReadonlyArray1<'_, u32>,
        max_rounds: usize,
        min_transfer_time: u32,
    ) -> PyResult<Vec<Bound<'py, PyArray2<u32>>>> {
        let origin_sets = origins
            .iter()
            .map(|(stops, seconds)| {
                accesses(
                    slice(stops, "origin stops")?,
                    slice(seconds, "origin seconds")?,
                    "origins",
                )
            })
            .collect::<PyResult<Vec<_>>>()?;
        let times: Vec<core::Time> =
            slice(&departures, "departures")?.iter().map(|&d| core::Time(d)).collect();
        let p = params(max_rounds, min_transfer_time);
        let n = self.inner.stop_count();
        let results: Vec<Vec<u32>> = py.detach(|| {
            origin_sets
                .par_iter()
                .map(|set| {
                    let profile = core::range_search(&self.inner, &p, set, &times);
                    (0..times.len())
                        .flat_map(|i| profile.arrivals(i).iter().map(|t| t.0).collect::<Vec<_>>())
                        .collect()
                })
                .collect()
        });
        results
            .into_iter()
            .map(|flat| {
                Ok(Array2::from_shape_vec((times.len(), n), flat)
                    .map_err(value_error)?
                    .into_pyarray(py))
            })
            .collect()
    }

    /// Pareto-optimal journeys (fastest per number of vehicles) from origins to destinations.
    #[pyo3(signature = (
        origin_stops, origin_seconds, departure, destination_stops, destination_seconds,
        max_rounds, min_transfer_time,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn plan(
        &self,
        py: Python<'_>,
        origin_stops: PyReadonlyArray1<'_, u32>,
        origin_seconds: PyReadonlyArray1<'_, u32>,
        departure: u32,
        destination_stops: PyReadonlyArray1<'_, u32>,
        destination_seconds: PyReadonlyArray1<'_, u32>,
        max_rounds: usize,
        min_transfer_time: u32,
    ) -> PyResult<Vec<Journey>> {
        let origins = accesses(
            slice(&origin_stops, "origin_stops")?,
            slice(&origin_seconds, "origin_seconds")?,
            "origins",
        )?;
        let destinations = accesses(
            slice(&destination_stops, "destination_stops")?,
            slice(&destination_seconds, "destination_seconds")?,
            "destinations",
        )?;
        let p = params(max_rounds, min_transfer_time);
        let journeys = py
            .detach(|| core::plan(&self.inner, &p, &origins, core::Time(departure), &destinations));
        Ok(journeys.iter().map(Journey::from).collect())
    }
}

/// Undirected pedestrian network with stops attached to its edges (metres).
#[pyclass(module = "glacies_raptor")]
struct WalkGraph {
    inner: core::WalkGraph,
}

#[pymethods]
impl WalkGraph {
    #[new]
    fn new(
        node_count: u32,
        edge_from: PyReadonlyArray1<'_, u32>,
        edge_to: PyReadonlyArray1<'_, u32>,
        edge_length_m: PyReadonlyArray1<'_, f64>,
    ) -> PyResult<Self> {
        let (a, b, len) = (
            slice(&edge_from, "edge_from")?,
            slice(&edge_to, "edge_to")?,
            slice(&edge_length_m, "edge_length_m")?,
        );
        if b.len() != a.len() || len.len() != a.len() {
            return Err(value_error("edge arrays differ in length"));
        }
        let edges: Vec<(u32, u32, f64)> =
            a.iter().zip(b).zip(len).map(|((&x, &y), &l)| (x, y, l)).collect();
        Ok(Self { inner: core::WalkGraph::new(node_count, &edges).map_err(value_error)? })
    }

    fn attach_stops(
        &mut self,
        stops: PyReadonlyArray1<'_, u32>,
        edges: PyReadonlyArray1<'_, u32>,
        fractions: PyReadonlyArray1<'_, f64>,
        offsets_m: PyReadonlyArray1<'_, f64>,
    ) -> PyResult<()> {
        let (s, e, f, o) = (
            slice(&stops, "stops")?,
            slice(&edges, "edges")?,
            slice(&fractions, "fractions")?,
            slice(&offsets_m, "offsets_m")?,
        );
        if e.len() != s.len() || f.len() != s.len() || o.len() != s.len() {
            return Err(value_error("attachment arrays differ in length"));
        }
        let attached: Vec<(core::StopIdx, core::Attachment)> = (0..s.len())
            .map(|i| {
                (
                    core::StopIdx(s[i]),
                    core::Attachment { edge: e[i], fraction: f[i], offset_m: o[i] },
                )
            })
            .collect();
        self.inner.attach_stops(&attached).map_err(value_error)
    }

    #[getter]
    fn node_count(&self) -> usize {
        self.inner.node_count()
    }

    #[getter]
    fn edge_count(&self) -> usize {
        self.inner.edge_count()
    }

    /// Stops within `max_m` walking metres of a point on `edge`: `(stops, metres)`.
    fn stops_within<'py>(
        &self,
        py: Python<'py>,
        edge: u32,
        fraction: f64,
        offset_m: f64,
        max_m: f64,
    ) -> PyResult<(U32Array<'py>, F64Array<'py>)> {
        let at = core::Attachment { edge, fraction, offset_m };
        let found = py.detach(|| self.inner.stops_within(&at, max_m)).map_err(value_error)?;
        let (stops, metres): (Vec<u32>, Vec<f64>) =
            found.into_iter().map(|(s, d)| (s.0, d)).unzip();
        Ok((stops.into_pyarray(py), metres.into_pyarray(py)))
    }

    /// Every pair of attached stops within `max_m` metres: `(from, to, metres)`, sorted.
    fn stop_to_stop<'py>(
        &self,
        py: Python<'py>,
        max_m: f64,
    ) -> (U32Array<'py>, U32Array<'py>, F64Array<'py>) {
        let pairs = py.detach(|| self.inner.stop_to_stop(max_m));
        let mut from = Vec::with_capacity(pairs.len());
        let mut to = Vec::with_capacity(pairs.len());
        let mut metres = Vec::with_capacity(pairs.len());
        for (a, b, d) in pairs {
            from.push(a.0);
            to.push(b.0);
            metres.push(d);
        }
        (from.into_pyarray(py), to.into_pyarray(py), metres.into_pyarray(py))
    }
}

#[pymodule]
fn glacies_raptor(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("UNREACHED", core::Time::UNREACHED.0)?;
    m.add_class::<Timetable>()?;
    m.add_class::<Journey>()?;
    m.add_class::<Leg>()?;
    m.add_class::<WalkGraph>()?;
    Ok(())
}
