//! Zone travel-time percentiles on a hand-computed toy (docs/validation/raptor-toy-networks.md).

mod common;

use common::{builder, t, trip, A, B, C};
use glacies_raptor::{
    zone_travel_times, Access, MatrixError, Params, Timetable, ZoneEgress, NOT_REACHED,
};

const PARAMS: Params = Params { max_rounds: 4, min_transfer_time: 60 };
const PERCENTILES: [u8; 3] = [25, 50, 75];

/// Toy 5: T1 A 08:00 -> B 08:10 -> C 08:20 and T2 A 08:30 -> B 08:40 -> C 08:50.
fn toy5() -> Timetable {
    builder(
        3,
        vec![
            trip(1, &[(A, "08:00"), (B, "08:10"), (C, "08:20")]),
            trip(2, &[(A, "08:30"), (B, "08:40"), (C, "08:50")]),
        ],
    )
    .build()
    .0
}

/// Zone 0 is 2 min from C, zone 1 is 1 min from B (and 25 min on foot), zone 2 has no stop.
fn zones() -> ZoneEgress {
    ZoneEgress::new(3, &[(0, C, 120), (1, B, 60)]).unwrap()
}

fn run(max_minutes: u32) -> glacies_raptor::ZoneTimes {
    let origin = [Access { stop: A, duration: 60, board_only: false }];
    let departures = ["07:58", "07:59", "08:00", "08:01"].map(t);
    zone_travel_times(
        &toy5(),
        &PARAMS,
        &origin,
        &departures,
        &zones(),
        &[(1, 1500)],
        &PERCENTILES,
        max_minutes * 60,
    )
    .unwrap()
}

#[test]
fn percentiles_match_hand_calculation() {
    // Leaving at 07:58/07:59 catches T1 (on the platform at 07:59/08:00); 08:00/08:01 misses
    // it (on the platform 08:01/08:02) and takes T2.
    // Zone 0: arrive 08:22, 08:22, 08:52, 08:52 -> 24, 23, 52, 51 min.
    //   Sorted 23, 24, 51, 52: p25 = 23, p50 = 24, p75 = 51 (nearest rank).
    // Zone 1: by bus 13, 12, 41, 40 min; on foot 25 min -> 13, 12, 25, 25.
    //   Sorted 12, 13, 25, 25: p25 = 12, p50 = 13, p75 = 25.
    // Zone 2 has no stop and no walk: not reached.
    let result = run(120);

    assert_eq!(result.zones, [0, 1]);
    assert_eq!(result.times, [23 * 60, 24 * 60, 51 * 60, 12 * 60, 13 * 60, 25 * 60]);
}

#[test]
fn percentiles_above_the_limit_are_not_reached() {
    // With a 30-minute limit, zone 0's p75 (51 min) is dropped; with 20 minutes zone 0 is
    // dropped entirely (p25 = 23 min) and only zone 1 remains.
    let thirty = run(30);
    assert_eq!(thirty.zones, [0, 1]);
    assert_eq!(thirty.times[..3], [23 * 60, 24 * 60, NOT_REACHED]);

    let twenty = run(20);
    assert_eq!(twenty.zones, [1]);
    assert_eq!(twenty.times, [12 * 60, 13 * 60, NOT_REACHED]);
}

#[test]
fn an_origin_zone_reaches_itself_on_foot() {
    // A zero-second walk (the origin zone itself) is reached at every departure.
    let result = zone_travel_times(
        &toy5(),
        &PARAMS,
        &[],
        &[t("08:00")],
        &zones(),
        &[(2, 0)],
        &PERCENTILES,
        3600,
    )
    .unwrap();

    assert_eq!(result.zones, [2]);
    assert_eq!(result.times, [0, 0, 0]);
}

#[test]
fn bad_inputs_are_rejected() {
    assert_eq!(ZoneEgress::new(1, &[(3, A, 0)]), Err(MatrixError::UnknownZone { zone: 3 }));
    let bad = |percentiles: &[u8], walk: &[(u32, u32)]| {
        zone_travel_times(&toy5(), &PARAMS, &[], &[t("08:00")], &zones(), walk, percentiles, 60)
    };
    assert_eq!(bad(&[0], &[]), Err(MatrixError::BadPercentile { percentile: 0 }));
    assert_eq!(bad(&[101], &[]), Err(MatrixError::BadPercentile { percentile: 101 }));
    assert_eq!(bad(&[50], &[(9, 0)]), Err(MatrixError::UnknownZone { zone: 9 }));
}
