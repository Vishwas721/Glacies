//! Route-choice bundles on a hand-checkable toy (Phase 6 M3).

mod common;

use common::{builder, t, trip, A, B, C};
use glacies_raptor::{
    origin_bundles, Access, Alternatives, ChoiceSet, CostNetwork, CostParams, DepartureProfile,
    Fares, MetroNetwork, Params, Timetable, ZoneEgress, BUS_ONLY, FASTEST, NO_STATION,
};

const PARAMS: Params = Params { max_rounds: 4, min_transfer_time: 60 };

/// Metro trip 1: A 08:00 -> C 08:10. Bus trip 2: A 08:00 -> B 08:10 -> C 08:20.
fn toy() -> Timetable {
    builder(
        3,
        vec![
            trip(1, &[(A, "08:00"), (C, "08:10")]),
            trip(2, &[(A, "08:00"), (B, "08:10"), (C, "08:20")]),
        ],
    )
    .build()
    .0
}

/// Stop-time rows: trip 1 at rows 0-1 (5 km), trip 2 at rows 2-4 (3 km, then 3 more).
fn network() -> CostNetwork {
    CostNetwork {
        metro: MetroNetwork {
            metro_trip: vec![false, true, false],
            station: vec![10, NO_STATION, 11],
        },
        row_offset: vec![0, 0, 2],
        row_km: vec![0.0, 5.0, 0.0, 3.0, 6.0],
    }
}

fn fares() -> Fares {
    Fares {
        minutes_per_unit: 60.0 / 100.0, // value of time 100 per hour
        metro_band_hops: vec![2, 4],
        metro_band_fare: vec![10.0, 20.0],
        metro_above: 30.0,
        metro_discount: 0.0,
        bus_stage_km: 2.0,
        bus_fare_per_stage: 5.0,
        bus_free_share: 0.5,
        ride_base: 30.0,
        ride_base_km: 2.0,
        ride_per_km: 15.0,
        ride_penalty_s: 300.0,
        ride_speed_kmh: 15.0,
    }
}

fn cost(with_fares: bool) -> CostParams {
    CostParams {
        walk_weight: 2.0,
        wait_weight: 2.0,
        ride_weight: 1.0,
        transfer_penalty_min: 5.0,
        fares: with_fares.then(fares),
    }
}

fn choice_set(with_fares: bool) -> ChoiceSet {
    let tt = toy();
    let bus_only = tt.retain_trips(|id| id != 1);
    let net = network();
    let bundles = origin_bundles(
        Alternatives { all: &tt, bus_only: &bus_only, params: PARAMS },
        &[Access { stop: A, duration: 60, board_only: false }],
        DepartureProfile { times: &[t("07:59")], weights: &[1.0] },
        &ZoneEgress::new(1, &[(0, C, 60)]).unwrap(),
        &[],
        &[0],
        &[100.0],
        &net,
        &cost(with_fares),
        120 * 60,
    )
    .unwrap();
    let mut set = ChoiceSet::new();
    set.push(7, bundles);
    set
}

#[test]
fn alternatives_are_the_metro_and_the_bus_and_duplicates_merge() {
    // The fastest journey takes the metro; the bus-only search takes the bus; at most one
    // transfer finds the metro again, which is merged with the fastest.
    let set = choice_set(false);

    assert_eq!((set.pair_count(), set.alt_count()), (1, 2));
    assert_eq!(set.alt_kind, [FASTEST, BUS_ONLY]);
    assert_eq!((set.pair_origin[0], set.pair_dest[0], set.pair_transit[0]), (7, 0, 100.0));
    // Both walk 1 + 1 minutes (weight 2) and wait nothing: 4 generalised minutes.
    assert_eq!(set.alt_fixed_min, [4.0, 4.0]);
    assert_eq!((set.ride_trip.clone(), set.ride_board.clone()), (vec![1, 2], vec![0, 0]));
    assert_eq!(set.ride_alight, [1, 2]);
}

#[test]
fn fares_are_converted_with_the_value_of_time() {
    // Metro: 1 station hop, band <= 2: 10, 6 minutes at 100 per hour. Bus: 6 km, 3 stages of
    // 5, half the riders free: 7.5, 4.5 minutes.
    assert_eq!(choice_set(true).alt_fixed_min, [4.0 + 6.0, 4.0 + 4.5]);
}

#[test]
fn crowding_costs_logit_shares_loads_and_gates() {
    let set = choice_set(true);
    let row_offset = [0, 0, 2];
    // Crowding multiplier 1 on the metro, 1.5 on the bus's second segment.
    let crowded = [0.0, 600.0, 0.0, 600.0, 600.0 + 1.5 * 600.0];
    let costs = set.costs(&crowded, &row_offset);
    assert_eq!(costs, [10.0 + 10.0, 8.5 + 25.0]);

    let shares = set.shares(&costs, 0.1);
    let metro = 1.0 / (1.0 + (-0.1_f64 * 13.5).exp());
    assert!((shares[0] - metro).abs() < 1e-12);
    assert!((shares[0] + shares[1] - 1.0).abs() < 1e-12);

    let (boardings, alightings) = set.loads(&shares, &row_offset, 5);
    assert!((boardings[0] - 100.0 * metro).abs() < 1e-9);
    assert!((alightings[1] - 100.0 * metro).abs() < 1e-9);
    assert!((boardings[2] - 100.0 * (1.0 - metro)).abs() < 1e-9);
    assert!((alightings[4] - 100.0 * (1.0 - metro)).abs() < 1e-9);
    assert!(boardings[1].abs() < 1e-12 && boardings[3].abs() < 1e-12);

    let (totals, gates) = set.summary(&shares);
    // In vehicles: metro 600 s, bus 1,200 s, weighted by their trips.
    let in_vehicle = 100.0 * (metro * 600.0 + (1.0 - metro) * 1200.0);
    assert!((totals[0].in_vehicle_s - in_vehicle).abs() < 1e-6);
    assert_eq!(gates.len(), 1);
    assert_eq!((gates[0].0, gates[0].1), (10, 11));
    assert!((gates[0].2 - 100.0 * metro).abs() < 1e-4); // shares are stored as f32
}

#[test]
fn a_very_large_theta_picks_the_cheapest() {
    let set = choice_set(false);
    let shares = set.shares(&[20.0, 24.0], 50.0);
    assert!(shares[0] > 0.999_999 && shares[1] < 1e-6);
}
