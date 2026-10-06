//! Toy networks from `docs/validation/raptor-toy-networks.md`, shared by integration tests.

#![allow(dead_code)] // each test binary uses a different subset

use glacies_raptor::{StopIdx, Time, TimetableBuilder, TripInput};

pub const A: StopIdx = StopIdx(0);
pub const B: StopIdx = StopIdx(1);
pub const C: StopIdx = StopIdx(2);
pub const D: StopIdx = StopIdx(3);

/// `HH:MM` on the service day.
pub fn t(hhmm: &str) -> Time {
    Time::parse_gtfs(&format!("{hhmm}:00")).expect("valid toy time")
}

/// A trip without dwell time: arrival equals departure at every stop.
pub fn trip(trip_id: u32, calls: &[(StopIdx, &str)]) -> TripInput {
    let times: Vec<Time> = calls.iter().map(|(_, hhmm)| t(hhmm)).collect();
    TripInput {
        trip_id,
        stops: calls.iter().map(|(stop, _)| *stop).collect(),
        arrivals: times.clone(),
        departures: times,
    }
}

pub fn builder(stop_count: u32, trips: Vec<TripInput>) -> TimetableBuilder {
    let mut builder = TimetableBuilder::new(stop_count);
    for input in trips {
        builder.add_trip(input).expect("valid toy trip");
    }
    builder
}

/// Toy 1: A 08:00 -> B 08:10 -> C 08:20 on T1.
pub fn toy1() -> TimetableBuilder {
    builder(
        3,
        vec![trip(1, &[(A, "08:00"), (B, "08:10"), (C, "08:20")])],
    )
}

/// Toy 2: T1 A 08:00 -> B 08:10, then T2 B 08:15 -> C 08:25.
pub fn toy2() -> TimetableBuilder {
    builder(
        3,
        vec![
            trip(1, &[(A, "08:00"), (B, "08:10")]),
            trip(2, &[(B, "08:15"), (C, "08:25")]),
        ],
    )
}

/// Toy 3: Fast A 08:00 -> B 08:05 -> D 08:15; Slow A 08:00 -> C 08:10 -> D 08:30.
pub fn toy3() -> TimetableBuilder {
    builder(
        4,
        vec![
            trip(1, &[(A, "08:00"), (B, "08:05"), (D, "08:15")]),
            trip(2, &[(A, "08:00"), (C, "08:10"), (D, "08:30")]),
        ],
    )
}
