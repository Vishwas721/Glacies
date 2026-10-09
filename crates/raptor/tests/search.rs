//! Earliest-arrival search on the hand-computed toy networks (docs/validation/raptor-toy-networks.md).

mod common;

use common::{builder, t, toy1, toy2, toy3, trip, A, B, C, D};
use glacies_raptor::{search, Access, Params, StopIdx, Time, Timetable, TripInput};

const PARAMS: Params = Params { max_rounds: 4, min_transfer_time: 60 };

fn from(stop: StopIdx) -> Vec<Access> {
    vec![Access { stop, duration: 0, board_only: false }]
}

fn earliest(tt: &Timetable, origin: StopIdx, departure: &str, to: StopIdx) -> Option<Time> {
    search(tt, &PARAMS, &from(origin), t(departure), &[]).earliest_arrival(to)
}

#[test]
fn toy1_direct_arrives_at_0820() {
    let (tt, _) = toy1().build();

    assert_eq!(earliest(&tt, A, "08:00", C), Some(t("08:20")));
    assert_eq!(earliest(&tt, A, "08:00", B), Some(t("08:10")));
}

#[test]
fn toy2_one_transfer_arrives_at_0825() {
    let (tt, _) = toy2().build();
    let profile = search(&tt, &PARAMS, &from(A), t("08:00"), &[]);

    assert_eq!(profile.earliest_arrival(C), Some(t("08:25")));
    assert_eq!(profile.arrival_with(1, C), None, "C needs two vehicles");
    assert_eq!(profile.arrival_with(2, C), Some(t("08:25")));
}

#[test]
fn toy3_diamond_takes_the_fast_branch() {
    let (tt, _) = toy3().build();

    assert_eq!(earliest(&tt, A, "08:00", D), Some(t("08:15")));
}

#[test]
fn missing_the_first_departure_means_no_journey() {
    let (tt, _) = toy1().build();

    assert_eq!(earliest(&tt, A, "08:01", C), None);
}

#[test]
fn round_limit_is_respected() {
    let (tt, _) = toy2().build();
    let one_vehicle = Params { max_rounds: 1, ..PARAMS };

    let profile = search(&tt, &one_vehicle, &from(A), t("08:00"), &[]);

    assert_eq!(profile.earliest_arrival(B), Some(t("08:10")));
    assert_eq!(profile.earliest_arrival(C), None);
}

#[test]
fn minimum_transfer_time_applies_after_riding() {
    // T2 leaves B 30 s after T1 arrives: too tight with a 60 s transfer, fine with 0 s.
    let tight = || {
        builder(
            3,
            vec![trip(1, &[(A, "08:00"), (B, "08:10")]), trip(2, &[(B, "08:10"), (C, "08:20")])],
        )
        .build()
        .0
    };
    let tt = tight();

    assert_eq!(earliest(&tt, A, "08:00", C), None);
    let instant = Params { min_transfer_time: 0, ..PARAMS };
    let profile = search(&tt, &instant, &from(A), t("08:00"), &[]);
    assert_eq!(profile.earliest_arrival(C), Some(t("08:20")));
}

#[test]
fn no_transfer_time_is_needed_at_the_origin() {
    let (tt, _) = toy1().build();

    // Arriving at A exactly at 08:00 still catches T1.
    assert_eq!(earliest(&tt, A, "08:00", B), Some(t("08:10")));
}

#[test]
fn a_later_trip_is_taken_when_the_first_is_missed() {
    let (tt, _) = builder(
        2,
        vec![trip(1, &[(A, "08:00"), (B, "08:10")]), trip(2, &[(A, "08:30"), (B, "08:40")])],
    )
    .build();

    assert_eq!(earliest(&tt, A, "08:05", B), Some(t("08:40")));
}

#[test]
fn footpaths_carry_one_walk_after_a_ride() {
    // T1 A -> B; walk B -> X (120 s); T2 X -> C. X is stop 3 here.
    let x = StopIdx(3);
    let mut b = builder(
        4,
        vec![trip(1, &[(A, "08:00"), (B, "08:10")]), trip(2, &[(x, "08:15"), (C, "08:25")])],
    );
    b.add_footpath(B, x, 120).unwrap();
    let (tt, _) = b.build();

    let profile = search(&tt, &PARAMS, &from(A), t("08:00"), &[]);
    assert_eq!(profile.earliest_arrival(x), Some(t("08:12")));
    assert_eq!(profile.earliest_arrival(C), Some(t("08:25")));
}

#[test]
fn walks_are_never_chained() {
    // B -> X -> Y by two footpaths: Y must stay unreachable (one walking leg per transfer).
    let (x, y) = (StopIdx(3), StopIdx(4));
    let mut b = builder(5, vec![trip(1, &[(A, "08:00"), (B, "08:10")])]);
    b.add_footpath(B, x, 60).unwrap();
    b.add_footpath(x, y, 60).unwrap();
    let (tt, _) = b.build();

    let profile = search(&tt, &PARAMS, &from(A), t("08:00"), &[]);
    assert_eq!(profile.earliest_arrival(x), Some(t("08:11")));
    assert_eq!(profile.earliest_arrival(y), None);
}

#[test]
fn walking_in_beats_waiting_out_the_transfer_time() {
    // X is reached by vehicle at 08:10 (ready to board at 08:11) and on foot at 08:10:30
    // (ready at 08:10:30). The 08:10:45 departure from X must be catchable.
    let x = StopIdx(3);
    let mut b = builder(
        4,
        vec![trip(1, &[(A, "08:00"), (x, "08:10")]), trip(2, &[(A, "08:00"), (B, "08:09")])],
    );
    let at_08_10_45 = Time(8 * 3600 + 10 * 60 + 45);
    b.add_trip(TripInput {
        trip_id: 3,
        stops: vec![x, C],
        arrivals: vec![at_08_10_45, t("08:30")],
        departures: vec![at_08_10_45, t("08:30")],
    })
    .unwrap();
    b.add_footpath(B, x, 90).unwrap();
    let (tt, _) = b.build();

    let profile = search(&tt, &PARAMS, &from(A), t("08:00"), &[]);
    assert_eq!(profile.earliest_arrival(x), Some(t("08:10")));
    assert_eq!(profile.earliest_arrival(C), Some(t("08:30")));
}

#[test]
fn after_midnight_trips_are_reachable() {
    let (tt, _) = builder(2, vec![trip(1, &[(A, "23:50"), (B, "24:20")])]).build();

    assert_eq!(earliest(&tt, A, "23:45", B), Some(Time(87_600)));
}

#[test]
fn circular_routes_can_be_ridden_back_to_the_start() {
    let (tt, _) = builder(2, vec![trip(1, &[(A, "08:00"), (B, "08:10"), (A, "08:20")])]).build();

    let profile = search(&tt, &PARAMS, &from(B), t("08:05"), &[]);
    assert_eq!(profile.earliest_arrival(A), Some(t("08:20")));
}

/// Toy 4: T1 A 08:02 -> C 08:12, T2 A 08:06 -> C 08:16; entering station A takes `seconds`.
fn toy4(seconds: u32) -> Timetable {
    let mut b = builder(
        3,
        vec![trip(1, &[(A, "08:02"), (C, "08:12")]), trip(2, &[(A, "08:06"), (C, "08:16")])],
    );
    b.set_station_entry(A, 0, seconds).unwrap();
    b.build().0
}

#[test]
fn station_entry_delays_the_first_boarding() {
    // Reaching A at 08:00 with a 4-minute station entry: on the platform at 08:04, so T1
    // (08:02) is missed and T2 (08:06) is taken.
    assert_eq!(earliest(&toy4(0), A, "08:00", C), Some(t("08:12")));
    assert_eq!(earliest(&toy4(240), A, "08:00", C), Some(t("08:16")));
    assert_eq!(earliest(&toy4(240), A, "08:00", A), Some(t("08:04")));
}

/// T1 A 08:00 -> B 08:10; footpath B -> X (120 s); T2 X 08:15 -> C 08:25. X is stop 3.
fn walk_in(setup: impl FnOnce(&mut glacies_raptor::TimetableBuilder)) -> Timetable {
    let x = StopIdx(3);
    let mut b = builder(
        4,
        vec![trip(1, &[(A, "08:00"), (B, "08:10")]), trip(2, &[(x, "08:15"), (C, "08:25")])],
    );
    b.add_footpath(B, x, 120).unwrap();
    setup(&mut b);
    b.build().0
}

#[test]
fn station_entry_applies_when_walking_in_from_outside() {
    // Off T1 at 08:10, walk to X by 08:12, enter: 180 s gives 08:15 (T2 caught), 181 s misses it.
    let x = StopIdx(3);
    let caught = walk_in(|b| b.set_station_entry(x, 7, 180).unwrap());
    let missed = walk_in(|b| b.set_station_entry(x, 7, 181).unwrap());

    assert_eq!(earliest(&caught, A, "08:00", C), Some(t("08:25")));
    assert_eq!(earliest(&missed, A, "08:00", C), None);
}

#[test]
fn changing_platforms_within_a_station_is_free() {
    // B and X are platforms of station 7: the walk takes 120 s and no entry time.
    let x = StopIdx(3);
    let tt = walk_in(|b| {
        b.set_station_entry(B, 7, 600).unwrap();
        b.set_station_entry(x, 7, 600).unwrap();
    });

    let profile = search(&tt, &PARAMS, &from(A), t("08:00"), &[]);
    assert_eq!(profile.earliest_arrival(x), Some(t("08:12")));
    assert_eq!(profile.earliest_arrival(C), Some(t("08:25")));
}

#[test]
fn station_entry_does_not_apply_to_alighting_or_staying_at_a_stop() {
    // Toy 2 with a 10-minute entry at B and C: arriving by vehicle costs nothing, and the
    // transfer at B needs only the 60 s minimum transfer time.
    let mut b = toy2();
    b.set_station_entry(B, 1, 600).unwrap();
    b.set_station_entry(C, 2, 600).unwrap();
    let (tt, _) = b.build();

    let profile = search(&tt, &PARAMS, &from(A), t("08:00"), &[]);
    assert_eq!(profile.earliest_arrival(B), Some(t("08:10")));
    assert_eq!(profile.earliest_arrival(C), Some(t("08:25")));
}
