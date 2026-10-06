//! Journey reconstruction, Pareto sets, and access/egress walks.

mod common;

use common::{builder, t, toy1, toy2, toy3, trip, A, B, C, D};
use glacies_raptor::{plan, Access, Journey, Leg, Params, RouteIdx, StopIdx, Time, Timetable};

const PARAMS: Params = Params {
    max_rounds: 4,
    min_transfer_time: 60,
};

fn at(stop: StopIdx) -> Vec<Access> {
    vec![Access { stop, duration: 0 }]
}

fn only(journeys: Vec<Journey>) -> Journey {
    assert_eq!(
        journeys.len(),
        1,
        "expected exactly one journey: {journeys:#?}"
    );
    journeys.into_iter().next().unwrap()
}

fn rides(journey: &Journey) -> Vec<(u32, StopIdx, StopIdx)> {
    journey
        .legs
        .iter()
        .filter_map(|leg| match *leg {
            Leg::Ride {
                trip_id, from, to, ..
            } => Some((trip_id, from, to)),
            _ => None,
        })
        .collect()
}

fn plan_toy(tt: &Timetable, to: StopIdx) -> Vec<Journey> {
    plan(tt, &PARAMS, &at(A), t("08:00"), &at(to))
}

// --- the hand-computed expectations ---------------------------------------------------------

#[test]
fn toy1_direct_trip() {
    let (tt, _) = toy1().build();
    let journey = only(plan_toy(&tt, C));

    assert_eq!(journey.arrival, t("08:20"));
    assert_eq!(journey.travel_time(), 20 * 60);
    assert_eq!(journey.transfers(), 0);
    assert_eq!(
        journey.legs,
        [Leg::Ride {
            route: RouteIdx(0),
            trip_id: 1,
            from: A,
            to: C,
            board: t("08:00"),
            alight: t("08:20"),
        }]
    );
    assert_eq!((journey.waiting_time(), journey.walking_time()), (0, 0));
}

#[test]
fn toy2_one_transfer_with_five_minutes_waiting() {
    let (tt, _) = toy2().build();
    let journey = only(plan_toy(&tt, C));

    assert_eq!(journey.arrival, t("08:25"));
    assert_eq!(journey.travel_time(), 25 * 60);
    assert_eq!(journey.transfers(), 1);
    assert_eq!(journey.waiting_time(), 5 * 60);
    assert_eq!(journey.in_vehicle_time(), 20 * 60);
    assert_eq!(rides(&journey), [(1, A, B), (2, B, C)]);
}

#[test]
fn toy3_diamond_goes_via_b() {
    let (tt, _) = toy3().build();
    let journey = only(plan_toy(&tt, D));

    assert_eq!(journey.arrival, t("08:15"));
    assert_eq!(journey.travel_time(), 15 * 60);
    assert_eq!(journey.transfers(), 0);
    assert_eq!(rides(&journey), [(1, A, D)]);
}

// --- Pareto set -----------------------------------------------------------------------------

#[test]
fn faster_journeys_with_more_transfers_are_kept_alongside_direct_ones() {
    let (tt, _) = builder(
        3,
        vec![
            trip(1, &[(A, "08:00"), (C, "09:00")]), // direct but slow
            trip(2, &[(A, "08:00"), (B, "08:10")]),
            trip(3, &[(B, "08:15"), (C, "08:30")]),
        ],
    )
    .build();

    let journeys = plan_toy(&tt, C);

    assert_eq!(journeys.len(), 2);
    assert_eq!(
        (journeys[0].transfers(), journeys[0].arrival),
        (0, t("09:00"))
    );
    assert_eq!(
        (journeys[1].transfers(), journeys[1].arrival),
        (1, t("08:30"))
    );
}

#[test]
fn slower_journeys_with_more_transfers_are_dropped() {
    let (tt, _) = builder(
        3,
        vec![
            trip(1, &[(A, "08:00"), (C, "08:20")]),
            trip(2, &[(A, "08:00"), (B, "08:10")]),
            trip(3, &[(B, "08:15"), (C, "08:40")]),
        ],
    )
    .build();

    let journey = only(plan_toy(&tt, C));
    assert_eq!(rides(&journey), [(1, A, C)]);
}

#[test]
fn unreachable_destinations_give_no_journeys() {
    let (tt, _) = toy1().build();

    assert!(plan(&tt, &PARAMS, &at(C), t("08:00"), &at(A)).is_empty());
}

// --- walking --------------------------------------------------------------------------------

#[test]
fn transfer_walks_appear_as_legs_and_count_as_walking() {
    let x = StopIdx(3);
    let mut b = builder(
        4,
        vec![
            trip(1, &[(A, "08:00"), (B, "08:10")]),
            trip(2, &[(x, "08:15"), (C, "08:25")]),
        ],
    );
    b.add_footpath(B, x, 120).unwrap();
    let (tt, _) = b.build();

    let journey = only(plan_toy(&tt, C));

    assert_eq!(
        journey.legs[1],
        Leg::Transfer {
            from: B,
            to: x,
            duration: 120
        },
        "{journey:#?}"
    );
    assert_eq!(journey.walking_time(), 120);
    assert_eq!(journey.waiting_time(), 3 * 60); // 08:12 -> 08:15 at X
    assert_eq!(journey.transfers(), 1);
}

#[test]
fn the_best_access_stop_is_chosen_and_both_walks_are_legs() {
    // T1 leaves A at 08:00 and B at 08:10.
    let (tt, _) = toy1().build();
    let walk = |stop, duration| Access { stop, duration };
    let destinations = [walk(C, 180)];

    // Leaving at 07:50: A (10 min walk) catches T1; B (25 min walk) would miss it.
    let journey = only(plan(
        &tt,
        &PARAMS,
        &[walk(A, 600), walk(B, 1500)],
        t("07:50"),
        &destinations,
    ));
    assert_eq!(
        journey.legs.first(),
        Some(&Leg::Access {
            to: A,
            duration: 600
        })
    );
    assert_eq!(
        journey.legs.last(),
        Some(&Leg::Egress {
            from: C,
            duration: 180
        })
    );
    assert_eq!(journey.arrival, t("08:23"));
    assert_eq!(journey.walking_time(), 600 + 180);

    // Leaving at 07:55: walking to A arrives 08:05, after T1 has left; B (2 min) catches it.
    let journey = only(plan(
        &tt,
        &PARAMS,
        &[walk(A, 600), walk(B, 120)],
        t("07:55"),
        &destinations,
    ));
    assert_eq!(
        journey.legs.first(),
        Some(&Leg::Access {
            to: B,
            duration: 120
        })
    );
    assert_eq!(journey.arrival, t("08:23"));
}

#[test]
fn the_best_egress_stop_is_chosen() {
    // T1 passes B at 08:10 and C at 08:20; walking from B takes 15 min, from C 2 min.
    let (tt, _) = toy1().build();
    let destinations = [
        Access {
            stop: B,
            duration: 900,
        },
        Access {
            stop: C,
            duration: 120,
        },
    ];

    let journey = only(plan(&tt, &PARAMS, &at(A), t("08:00"), &destinations));

    assert_eq!(journey.arrival, t("08:22"));
    assert_eq!(
        journey.legs.last(),
        Some(&Leg::Egress {
            from: C,
            duration: 120
        })
    );
}

#[test]
fn walking_only_journeys_are_reported_without_rides() {
    let (tt, _) = toy1().build();
    let origins = [Access {
        stop: A,
        duration: 120,
    }];
    let destinations = [Access {
        stop: A,
        duration: 60,
    }];

    let journey = only(plan(&tt, &PARAMS, &origins, t("08:00"), &destinations));

    assert_eq!(journey.rides(), 0);
    assert_eq!(journey.arrival, Time(t("08:00").0 + 180));
    assert_eq!(journey.walking_time(), 180);
}

#[test]
fn target_pruning_does_not_change_the_answer() {
    // A wider network: the destination is reached early by one branch; later improvements on
    // other branches must not be lost or invented.
    let (tt, _) = builder(
        4,
        vec![
            trip(1, &[(A, "08:00"), (B, "08:05"), (D, "08:15")]),
            trip(2, &[(A, "08:00"), (C, "08:10"), (D, "08:30")]),
            trip(3, &[(B, "08:07"), (C, "08:08")]),
            trip(4, &[(C, "08:12"), (D, "08:13")]),
        ],
    )
    .build();

    let with_pruning = plan_toy(&tt, D);
    let reference = glacies_raptor::search(&tt, &PARAMS, &at(A), t("08:00"), &[]);

    assert_eq!(
        with_pruning.last().unwrap().arrival,
        reference.earliest_arrival(D).unwrap()
    );
    // 08:15 direct, then 08:13 with one change (Slow to C, T4 to D). The three-vehicle
    // route via B also reaches D at 08:13 and is correctly not reported: it is no faster.
    assert_eq!(with_pruning.len(), 2);
    assert_eq!(with_pruning[0].arrival, t("08:15"));
    assert_eq!(with_pruning[1].arrival, t("08:13"));
    assert_eq!(rides(&with_pruning[1]), [(2, A, C), (4, C, D)]);
}
