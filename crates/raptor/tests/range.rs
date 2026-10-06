//! Range RAPTOR: one search per departure window, identical to a search per departure.

mod common;

use common::{t, toy2, A, B, C};
use glacies_raptor::{
    range_search, search, Access, Params, StopIdx, Time, TimetableBuilder, TripInput,
};

const PARAMS: Params = Params { max_rounds: 4, min_transfer_time: 60 };

fn at(stop: StopIdx) -> Vec<Access> {
    vec![Access { stop, duration: 0 }]
}

fn every_five_minutes(from: &str, to: &str) -> Vec<Time> {
    (t(from).0..=t(to).0).step_by(300).map(Time).collect()
}

#[test]
fn toy2_over_a_window() {
    let (tt, _) = toy2().build();
    let departures = every_five_minutes("07:50", "08:10");

    let profile = range_search(&tt, &PARAMS, &at(A), &departures);

    // 07:50 and 07:55 wait for T1 at 08:00; 08:00 just catches it; later departures miss it.
    let to_c: Vec<_> = (0..departures.len()).map(|i| profile.arrival(i, C)).collect();
    assert_eq!(to_c, [Some(t("08:25")), Some(t("08:25")), Some(t("08:25")), None, None]);
    let minutes: Vec<_> =
        (0..departures.len()).map(|i| profile.travel_time(i, C).map(|s| s / 60)).collect();
    assert_eq!(minutes, [Some(35), Some(30), Some(25), None, None]);
    assert_eq!(profile.arrival(4, B), None);
}

#[test]
fn departures_can_be_given_in_any_order_with_duplicates() {
    let (tt, _) = toy2().build();
    let ordered = every_five_minutes("07:50", "08:10");
    let shuffled = vec![ordered[3], ordered[0], ordered[4], ordered[0], ordered[2], ordered[1]];

    let a = range_search(&tt, &PARAMS, &at(A), &ordered);
    let b = range_search(&tt, &PARAMS, &at(A), &shuffled);

    assert_eq!(b.departures(), shuffled.as_slice());
    for (j, &dep) in shuffled.iter().enumerate() {
        let i = ordered.iter().position(|&d| d == dep).unwrap();
        assert_eq!(a.arrivals(i), b.arrivals(j), "departure {dep:?}");
    }
}

/// Same `SplitMix64` generator as the oracle tests.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    fn between(&mut self, lo: u32, hi: u32) -> u32 {
        lo + u32::try_from(self.next() % u64::from(hi - lo + 1)).unwrap()
    }
}

#[test]
fn range_equals_one_search_per_departure_on_random_networks() {
    let mut rng = Rng(5);
    for case in 0..400 {
        let stops = rng.between(4, 12);
        let mut builder = TimetableBuilder::new(stops);
        for trip_id in 0..rng.between(5, 40) {
            let len = rng.between(2, 6);
            let mut time = rng.between(7 * 3600, 8 * 3600);
            let (mut path, mut arr, mut dep) = (Vec::new(), Vec::new(), Vec::new());
            for i in 0..len {
                if i > 0 {
                    time += rng.between(60, 600);
                }
                arr.push(Time(time));
                time += rng.between(0, 1) * 30;
                dep.push(Time(time));
                path.push(StopIdx(rng.between(0, stops - 1)));
            }
            builder
                .add_trip(TripInput { trip_id, stops: path, arrivals: arr, departures: dep })
                .unwrap();
        }
        for _ in 0..rng.between(0, 20) {
            let (a, b) = (rng.between(0, stops - 1), rng.between(0, stops - 1));
            builder.add_footpath(StopIdx(a), StopIdx(b), rng.between(30, 240)).unwrap();
        }
        let (tt, _) = builder.build();
        let params = Params {
            max_rounds: usize::try_from(rng.between(1, 5)).unwrap(),
            min_transfer_time: [0, 60, 300][usize::try_from(rng.between(0, 2)).unwrap()],
        };
        let origins: Vec<Access> = (0..rng.between(1, 2))
            .map(|_| Access {
                stop: StopIdx(rng.between(0, stops - 1)),
                duration: rng.between(0, 300),
            })
            .collect();
        let departures: Vec<Time> =
            (0..rng.between(1, 30)).map(|_| Time(rng.between(7 * 3600 - 600, 8 * 3600))).collect();

        let range = range_search(&tt, &params, &origins, &departures);
        for (i, &departure) in departures.iter().enumerate() {
            let single = search(&tt, &params, &origins, departure, &[]);
            for s in 0..stops {
                assert_eq!(
                    range.arrival(i, StopIdx(s)),
                    single.earliest_arrival(StopIdx(s)),
                    "case {case}, departure {i} ({departure:?}), stop {s}, {params:?}"
                );
            }
        }
    }
}
