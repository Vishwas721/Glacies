//! Timetable construction: route grouping, trip order, overtaking splits and input validation.

mod common;

use common::{builder, t, toy1, toy2, toy3, trip, A, B, C, D};
use glacies_raptor::{BuildError, RouteIdx, StopIdx, Time, TimetableBuilder, TripInput};

#[test]
fn toy1_is_one_route_with_one_trip() {
    let (tt, report) = toy1().build();

    assert_eq!((tt.stop_count(), tt.route_count(), tt.trip_count()), (3, 1, 1));
    let route = tt.route(RouteIdx(0));
    assert_eq!(route.stops(), &[A, B, C]);
    assert_eq!(route.trip_count(), 1);
    assert_eq!(route.trip_id(0), 1);
    assert_eq!(route.arrival(0, 2), t("08:20"));
    assert_eq!(route.departure(0, 1), t("08:10"));
    assert_eq!(report.overtaking_splits, 0);
}

#[test]
fn toy2_shares_stop_b_between_two_routes() {
    let (tt, _) = toy2().build();

    assert_eq!(tt.route_count(), 2);
    // Routes are ordered by stop sequence: [A, B] before [B, C].
    assert_eq!(tt.route(RouteIdx(0)).stops(), &[A, B]);
    assert_eq!(tt.route(RouteIdx(1)).stops(), &[B, C]);
    assert_eq!(tt.routes_serving(B), &[(RouteIdx(0), 1), (RouteIdx(1), 0)]);
    assert_eq!(tt.routes_serving(A), &[(RouteIdx(0), 0)]);
    assert_eq!(tt.routes_serving(C), &[(RouteIdx(1), 1)]);
}

#[test]
fn toy3_diamond_meets_at_d() {
    let (tt, _) = toy3().build();

    assert_eq!(tt.route_count(), 2);
    assert_eq!(tt.route(RouteIdx(0)).stops(), &[A, B, D]);
    assert_eq!(tt.route(RouteIdx(1)).stops(), &[A, C, D]);
    assert_eq!(tt.routes_serving(D), &[(RouteIdx(0), 2), (RouteIdx(1), 2)]);
    assert_eq!(tt.route(RouteIdx(0)).arrival(0, 2), t("08:15"));
    assert_eq!(tt.route(RouteIdx(1)).arrival(0, 2), t("08:30"));
}

#[test]
fn trips_of_a_route_are_ordered_by_departure_whatever_the_input_order() {
    let trips = || {
        vec![
            trip(30, &[(A, "09:00"), (B, "09:10")]),
            trip(10, &[(A, "07:00"), (B, "07:10")]),
            trip(20, &[(A, "08:00"), (B, "08:10")]),
        ]
    };
    let (forward, _) = builder(2, trips()).build();
    let (reversed, _) = builder(2, trips().into_iter().rev().collect()).build();

    let route = forward.route(RouteIdx(0));
    assert_eq!((0..3).map(|i| route.trip_id(i)).collect::<Vec<_>>(), [10, 20, 30]);
    assert_eq!(forward, reversed, "the build must not depend on input order");
}

#[test]
fn overtaking_trips_are_split_into_separate_routes() {
    // The express leaves later but arrives earlier: one route would break "earliest trip".
    let (tt, report) = builder(
        2,
        vec![trip(1, &[(A, "08:00"), (B, "09:00")]), trip(2, &[(A, "08:10"), (B, "08:30")])],
    )
    .build();

    assert_eq!(tt.route_count(), 2);
    assert_eq!(report.overtaking_splits, 1);
    for r in 0..2 {
        assert_eq!(tt.route(RouteIdx(r)).stops(), &[A, B]);
        assert_eq!(tt.route(RouteIdx(r)).trip_count(), 1);
    }
    assert_eq!(tt.routes_serving(A).len(), 2);
}

#[test]
fn every_route_is_fifo_after_splitting() {
    // Three trips where the middle one overtakes the first; the third follows the first.
    let (tt, report) = builder(
        3,
        vec![
            trip(1, &[(A, "08:00"), (B, "08:20"), (C, "08:40")]),
            trip(2, &[(A, "08:05"), (B, "08:15"), (C, "08:25")]),
            trip(3, &[(A, "08:30"), (B, "08:50"), (C, "09:10")]),
        ],
    )
    .build();

    assert_eq!(report.overtaking_splits, 1);
    for r in 0..tt.route_count() {
        let route = tt.route(RouteIdx(u32::try_from(r).unwrap()));
        for trip in 1..route.trip_count() {
            for pos in 0..route.stops().len() {
                assert!(route.departure(trip - 1, pos) <= route.departure(trip, pos));
                assert!(route.arrival(trip - 1, pos) <= route.arrival(trip, pos));
            }
        }
    }
    assert_eq!(tt.trip_count(), 3);
}

#[test]
fn identical_trips_stay_in_one_route() {
    let (tt, report) = builder(
        2,
        vec![trip(1, &[(A, "08:00"), (B, "08:10")]), trip(2, &[(A, "08:00"), (B, "08:10")])],
    )
    .build();

    assert_eq!((tt.route_count(), report.overtaking_splits), (1, 0));
    assert_eq!(tt.route(RouteIdx(0)).trip_count(), 2);
}

#[test]
fn times_past_midnight_are_kept() {
    let (tt, _) = builder(2, vec![trip(1, &[(A, "23:50"), (B, "24:10")])]).build();

    assert_eq!(tt.route(RouteIdx(0)).arrival(0, 1), Time(87_000));
}

#[test]
fn footpaths_are_stored_per_stop_in_order() {
    let mut b = toy2();
    b.add_footpath(C, A, 300).unwrap();
    b.add_footpath(A, C, 120).unwrap();
    b.add_footpath(A, B, 60).unwrap();
    let (tt, _) = b.build();

    let from_a: Vec<_> = tt.footpaths(A).iter().map(|f| (f.to, f.duration)).collect();
    assert_eq!(from_a, [(B, 60), (C, 120)]);
    assert_eq!(tt.footpaths(B), &[]);
    assert_eq!(tt.footpaths(C).len(), 1);
}

fn input(stops: &[u32], arrivals: &[&str], departures: &[&str]) -> TripInput {
    TripInput {
        trip_id: 7,
        stops: stops.iter().map(|&s| StopIdx(s)).collect(),
        arrivals: arrivals.iter().map(|h| t(h)).collect(),
        departures: departures.iter().map(|h| t(h)).collect(),
    }
}

#[test]
fn invalid_trips_are_rejected() {
    let mut b = TimetableBuilder::new(3);
    let ok = ["08:00", "08:10"];

    assert_eq!(
        b.add_trip(input(&[0], &["08:00"], &["08:00"])),
        Err(BuildError::TooFewStops { trip_id: 7 })
    );
    assert_eq!(
        b.add_trip(input(&[0, 1], &ok, &["08:00"])),
        Err(BuildError::LengthMismatch { trip_id: 7 })
    );
    assert_eq!(
        b.add_trip(input(&[0, 9], &ok, &ok)),
        Err(BuildError::UnknownStop { trip_id: 7, stop: StopIdx(9) })
    );
    assert_eq!(
        b.add_trip(input(&[0, 1], &["08:00", "08:20"], &["08:00", "08:10"])),
        Err(BuildError::ArrivalAfterDeparture { trip_id: 7, position: 1 })
    );
    assert_eq!(
        b.add_trip(input(&[0, 1], &["08:00", "07:59"], &["08:00", "07:59"])),
        Err(BuildError::TimeGoesBackwards { trip_id: 7, position: 1 })
    );
    b.add_trip(input(&[0, 1], &ok, &ok)).unwrap();
    assert_eq!(
        b.add_trip(input(&[1, 2], &ok, &ok)),
        Err(BuildError::DuplicateTripId { trip_id: 7 })
    );
    assert_eq!(
        b.add_footpath(StopIdx(0), StopIdx(5), 60),
        Err(BuildError::UnknownFootpathStop { stop: StopIdx(5) })
    );
    assert_eq!(
        b.set_boarding_time(StopIdx(3), 240),
        Err(BuildError::UnknownBoardingStop { stop: StopIdx(3) })
    );
}

#[test]
fn boarding_times_default_to_zero_and_the_last_setting_wins() {
    let mut b = toy1();
    b.set_boarding_time(B, 120).unwrap();
    b.set_boarding_time(B, 240).unwrap();
    let (tt, _) = b.build();

    assert_eq!([A, B, C].map(|s| tt.boarding_time(s)), [0, 240, 0]);
}

#[test]
fn circular_routes_list_every_position_of_a_repeated_stop() {
    // Circular services start and end at the same stop (common in the BMTC feed).
    let (tt, _) = builder(2, vec![trip(1, &[(A, "08:00"), (B, "08:10"), (A, "08:20")])]).build();

    assert_eq!(tt.route(RouteIdx(0)).stops(), &[A, B, A]);
    assert_eq!(tt.routes_serving(A), &[(RouteIdx(0), 0), (RouteIdx(0), 2)]);
}

#[test]
fn earliest_trip_finds_the_first_catchable_departure() {
    let (tt, _) = builder(
        2,
        vec![
            trip(1, &[(A, "08:00"), (B, "08:10")]),
            trip(2, &[(A, "08:15"), (B, "08:25")]),
            trip(3, &[(A, "08:30"), (B, "08:40")]),
        ],
    )
    .build();
    let route = tt.route(RouteIdx(0));
    let all = route.trip_count();

    assert_eq!(route.earliest_trip(0, t("07:00"), all), Some(0));
    assert_eq!(route.earliest_trip(0, t("08:00"), all), Some(0)); // departing exactly then
    assert_eq!(route.earliest_trip(0, t("08:01"), all), Some(1));
    assert_eq!(route.earliest_trip(1, t("08:26"), all), Some(2));
    assert_eq!(route.earliest_trip(0, t("08:31"), all), None);
    assert_eq!(route.earliest_trip(0, t("08:01"), 1), None); // only trips before index 1
}
