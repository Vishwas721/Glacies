//! Metro segments per zone on a hand-checkable toy (Phase 5 M3).

mod common;

use common::{builder, t, trip};
use glacies_raptor::{
    zone_paths, zone_travel_times, Access, MetroNetwork, Params, StopIdx, Timetable, ZoneEgress,
    NO_STATION,
};

const PARAMS: Params = Params { max_rounds: 4, min_transfer_time: 60 };
const A: StopIdx = StopIdx(0); // bus stop at the origin
const B: StopIdx = StopIdx(1); // metro, station X (10)
const C: StopIdx = StopIdx(2); // metro, station Y (11), line 1
const D: StopIdx = StopIdx(3); // metro, station Y (11), line 2
const E: StopIdx = StopIdx(4); // metro, station Z (12)
const F: StopIdx = StopIdx(5); // bus stop
const G: StopIdx = StopIdx(6); // metro, station W (13), a short walk from Z
const H: StopIdx = StopIdx(7); // metro, station V (14)

/// Bus 1 A 08:00 -> B 08:10; metro 2 B 08:12 -> C 08:20; metro 3 D 08:23 -> E 08:30 (C -> D is
/// a 1-minute platform change inside station Y); bus 4 E 08:32 -> F 08:40; metro 6 G 08:35 ->
/// H 08:45 (E -> G is a 2-minute walk between stations Z and W).
fn toy() -> Timetable {
    let mut b = builder(
        8,
        vec![
            trip(1, &[(A, "08:00"), (B, "08:10")]),
            trip(2, &[(B, "08:12"), (C, "08:20")]),
            trip(3, &[(D, "08:23"), (E, "08:30")]),
            trip(4, &[(E, "08:32"), (F, "08:40")]),
            trip(6, &[(G, "08:35"), (H, "08:45")]),
        ],
    );
    b.add_footpath(C, D, 60).unwrap();
    b.add_footpath(E, G, 120).unwrap();
    b.build().0
}

fn metro() -> MetroNetwork {
    MetroNetwork {
        metro_trip: vec![false, false, true, true, false, false, true],
        station: vec![NO_STATION, 10, 11, 11, 12, NO_STATION, 13, 14],
    }
}

/// Zones 0-3 are a minute from C, E, F and H; zone 4 is a minute from B but 10 minutes on foot
/// from the origin; zone 5 has no stop.
fn zones() -> ZoneEgress {
    ZoneEgress::new(6, &[(0, C, 60), (1, E, 60), (2, F, 60), (3, H, 60), (4, B, 60)]).unwrap()
}

#[test]
fn segments_match_hand_reading() {
    // Leaving 07:59 (1 min to A) catches bus 1; leaving 08:01 misses every vehicle.
    // Zone 0: bus, metro X -> Y: one segment (X, Y).
    // Zone 1: ... metro X -> Y, change platforms in Y, metro Y -> Z: still one gate pass (X, Z).
    // Zone 2: as zone 1, then bus 4: one segment (X, Z).
    // Zone 3: as zone 1, then walk to station W and ride to V: two segments (X, Z), (W, V).
    // Zone 4: by transit 12 min, on foot 10 min: walked at both departures.
    // Zone 5: never reached.
    let result = zone_paths(
        &toy(),
        &PARAMS,
        &[Access { stop: A, duration: 60, board_only: false }],
        &["07:59", "08:01"].map(t),
        &zones(),
        &[(4, 600)],
        &[0, 1, 2, 3, 4, 5],
        &metro(),
        120 * 60,
    )
    .unwrap();

    assert_eq!(result.zones, [0, 1, 2, 3, 4, 5]);
    assert_eq!(result.reached, [1, 1, 1, 1, 2, 0]);
    assert_eq!(result.walked, [0, 0, 0, 0, 2, 0]);
    assert_eq!(result.metro, [1, 1, 1, 1, 0, 0]);
    assert_eq!(
        result.segments,
        [(0, 10, 11, 1), (1, 10, 12, 1), (2, 10, 12, 1), (3, 10, 12, 1), (3, 13, 14, 1)]
    );
}

#[test]
fn the_time_limit_drops_long_journeys() {
    // Zone 3 is reached at 08:46 (47 min after 07:59); with a 30-minute limit only zones 0
    // (22 min) and 4 (on foot) remain.
    let result = zone_paths(
        &toy(),
        &PARAMS,
        &[Access { stop: A, duration: 60, board_only: false }],
        &[t("07:59")],
        &zones(),
        &[(4, 600)],
        &[0, 3, 4],
        &metro(),
        30 * 60,
    )
    .unwrap();

    assert_eq!(result.reached, [1, 0, 1]);
    assert_eq!(result.segments, [(0, 10, 11, 1)]);
}

#[test]
fn unknown_target_is_an_error() {
    let result =
        zone_paths(&toy(), &PARAMS, &[], &[t("07:59")], &zones(), &[], &[9], &metro(), 3600);
    assert!(result.is_err());
}

#[test]
fn a_board_only_ride_must_be_followed_by_a_vehicle() {
    // Leaving 08:05: the walk to A (1 min) misses bus 1, but a 5-minute ride to station X
    // (B, 08:10) catches metro 2 to Y (C, 08:20): zone 0 by metro, 16 min door to door.
    // Zone 4 is a minute's walk from B, but riding to B and walking out uses no vehicle, so
    // it is not reached; as an ordinary walk the same access would reach it.
    let access = |board_only| {
        [
            Access { stop: A, duration: 60, board_only: false },
            Access { stop: B, duration: 300, board_only },
        ]
    };
    let paths = |board_only| {
        zone_paths(
            &toy(),
            &PARAMS,
            &access(board_only),
            &[t("08:05")],
            &zones(),
            &[],
            &[0, 4],
            &metro(),
            120 * 60,
        )
        .unwrap()
    };

    let ride = paths(true);
    assert_eq!(ride.reached, [1, 0]);
    assert_eq!(ride.metro, [1, 0]);
    assert_eq!(ride.segments, [(0, 10, 11, 1)]);
    assert_eq!(paths(false).reached, [1, 1]);

    let times = |board_only| {
        zone_travel_times(
            &toy(),
            &PARAMS,
            &access(board_only),
            &[t("08:05")],
            &zones(),
            &[],
            &[50],
            120 * 60,
        )
        .unwrap()
    };
    // The matrix covers every zone: the metro goes on to zones 1-3 (26, 36, 41 min).
    let ride = times(true);
    assert_eq!(ride.zones, [0, 1, 2, 3]);
    assert_eq!(ride.times, [16, 26, 36, 41].map(|m| m * 60));
    assert_eq!(times(false).zones, [0, 1, 2, 3, 4]);
}

#[test]
fn a_walk_to_the_same_stop_wins_over_a_board_only_ride() {
    // B can be walked to (10 min) and ridden to (5 min): it counts as walked to, so zone 4 is
    // reached on foot through B, and the faster ride is not used to board there.
    let result = zone_paths(
        &toy(),
        &PARAMS,
        &[
            Access { stop: B, duration: 600, board_only: false },
            Access { stop: B, duration: 300, board_only: true },
        ],
        &[t("08:05")],
        &zones(),
        &[],
        &[0, 4],
        &metro(),
        120 * 60,
    )
    .unwrap();

    assert_eq!(result.reached, [0, 1]); // 08:15 at B misses metro 2 (08:12)
}
