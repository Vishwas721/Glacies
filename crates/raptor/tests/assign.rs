//! All-or-nothing assignment on hand-checkable toys (Phase 6 M1).

mod common;

use common::{builder, t, toy2, trip, A, B, C};
use glacies_raptor::{
    zone_assign, Access, DepartureProfile, MatrixError, Params, Time, Timetable, ZoneEgress,
};

const PARAMS: Params = Params { max_rounds: 4, min_transfer_time: 60 };
const WALK_TO_A: [Access; 1] = [Access { stop: A, duration: 60, board_only: false }];

/// Trip 1: A 08:00 -> B 08:10 -> C 08:20. Trip 2: A 08:30 -> C 08:40 (express).
fn toy() -> Timetable {
    builder(
        3,
        vec![
            trip(1, &[(A, "08:00"), (B, "08:10"), (C, "08:20")]),
            trip(2, &[(A, "08:30"), (C, "08:40")]),
        ],
    )
    .build()
    .0
}

/// Zone 0 is a minute from C, zone 1 a minute from B; zone 2 has no stop.
fn zones() -> ZoneEgress {
    ZoneEgress::new(3, &[(0, C, 60), (1, B, 60)]).unwrap()
}

fn times() -> [Time; 2] {
    ["07:59", "08:20"].map(t)
}

#[test]
fn trips_follow_the_profile_over_the_departures_that_reach_them() {
    // Leaving 07:59 (weight 1) catches trip 1; leaving 08:20 (weight 3) misses it and takes the
    // express to C. Zone 0 is reached at both: 10 x 1/4 = 2.5 trips ride trip 1 from position
    // 0 to 2, and 7.5 ride trip 2. Zone 1 (B) is reached only at 07:59, so all 4 of its trips
    // ride trip 1 from 0 to 1. Zone 2 is never reached.
    let result = zone_assign(
        &toy(),
        &PARAMS,
        &WALK_TO_A,
        DepartureProfile { times: &times(), weights: &[1.0, 3.0] },
        &zones(),
        &[],
        &[0, 1, 2],
        &[10.0, 4.0, 5.0],
        120 * 60,
    )
    .unwrap();

    assert_eq!(result.zones, [0, 1, 2]);
    assert_eq!(result.transit, [10.0, 4.0, 0.0]);
    assert_eq!(result.walked, [0.0, 0.0, 0.0]);
    assert_eq!(result.unreached, [0.0, 0.0, 5.0]);
    assert_eq!(result.rides, [(1, 0, 1, 4.0), (1, 0, 2, 2.5), (2, 0, 1, 7.5)]);
}

#[test]
fn walking_wins_when_it_is_as_fast() {
    // Zone 1 is 10 minutes on foot; trip 1 gets there in 12 at 07:59, and nothing gets there
    // after 08:20. All its trips walk, and none ride.
    let result = zone_assign(
        &toy(),
        &PARAMS,
        &WALK_TO_A,
        DepartureProfile { times: &times(), weights: &[1.0, 3.0] },
        &zones(),
        &[(1, 600)],
        &[1],
        &[4.0],
        120 * 60,
    )
    .unwrap();

    assert_eq!(
        (result.transit, result.walked, result.unreached),
        (vec![0.0], vec![4.0], vec![0.0])
    );
    assert!(result.rides.is_empty());
}

#[test]
fn a_transfer_loads_both_trips() {
    // Toy 2: trip 1 A 08:00 -> B 08:10, trip 2 B 08:15 -> C 08:25.
    let (tt, _) = toy2().build();
    let egress = ZoneEgress::new(1, &[(0, C, 0)]).unwrap();
    let result = zone_assign(
        &tt,
        &PARAMS,
        &WALK_TO_A,
        DepartureProfile { times: &[t("07:59")], weights: &[1.0] },
        &egress,
        &[],
        &[0],
        &[6.0],
        120 * 60,
    )
    .unwrap();

    assert_eq!(result.transit, [6.0]);
    assert_eq!(result.rides, [(1, 0, 1, 6.0), (2, 0, 1, 6.0)]);
}

#[test]
fn the_time_limit_leaves_trips_unreached() {
    // With a 15-minute limit zone 0 (22 and 21 minutes) is not reached at either departure.
    let result = zone_assign(
        &toy(),
        &PARAMS,
        &WALK_TO_A,
        DepartureProfile { times: &times(), weights: &[1.0, 3.0] },
        &zones(),
        &[],
        &[0, 1],
        &[10.0, 4.0],
        15 * 60,
    )
    .unwrap();

    assert_eq!(result.unreached, [10.0, 0.0]);
    assert_eq!(result.rides, [(1, 0, 1, 4.0)]);
}

#[test]
fn mismatched_lengths_are_an_error() {
    let profile = DepartureProfile { times: &times(), weights: &[1.0] };
    let result =
        zone_assign(&toy(), &PARAMS, &WALK_TO_A, profile, &zones(), &[], &[0], &[1.0], 3600);
    assert_eq!(result, Err(MatrixError::LengthMismatch));
    let profile = DepartureProfile { times: &times(), weights: &[1.0, 1.0] };
    let result =
        zone_assign(&toy(), &PARAMS, &WALK_TO_A, profile, &zones(), &[], &[0, 1], &[1.0], 3600);
    assert_eq!(result, Err(MatrixError::LengthMismatch));
}
