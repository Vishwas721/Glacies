//! Property tests against an independent oracle.
//!
//! The oracle is the Connection Scan Algorithm (Dibbelt et al. 2013): a different, simpler way
//! to compute earliest arrivals. Hundreds of seeded random networks are built; for every stop,
//! RAPTOR with enough rounds must agree with it, and every journey RAPTOR reports must be
//! feasible against the timetable.

use glacies_raptor::{
    plan, search, Access, Journey, Leg, Params, StopIdx, Time, Timetable, TimetableBuilder,
    TripInput,
};

/// Small deterministic PRNG (`SplitMix64`); no external crates needed.
struct Rng(u64);

impl Rng {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    fn below(&mut self, n: u32) -> u32 {
        u32::try_from(self.next() % u64::from(n)).unwrap()
    }

    fn between(&mut self, lo: u32, hi: u32) -> u32 {
        lo + self.below(hi - lo + 1)
    }
}

struct Network {
    stops: u32,
    trips: Vec<TripInput>,
    footpaths: Vec<(StopIdx, StopIdx, u32)>,
    /// Per stop: station id (if any) and seconds to enter it on foot from outside the station.
    entry: Vec<(Option<u32>, u32)>,
}

impl Network {
    /// Same rule as the router: free within one stop or one station.
    fn entry_from(&self, from: StopIdx, to: StopIdx) -> u32 {
        let ((a, _), (b, seconds)) = (self.entry[from.0 as usize], self.entry[to.0 as usize]);
        if from == to || (a.is_some() && a == b) {
            0
        } else {
            seconds
        }
    }
}

fn random_network(rng: &mut Rng) -> Network {
    let stops = rng.between(4, 12);
    let trip_count = rng.between(5, 30);
    let mut trips = Vec::new();
    for trip_id in 0..trip_count {
        let len = rng.between(2, 6);
        let mut time = rng.between(7 * 3600, 8 * 3600); // dense: many trips interact
        let (mut path, mut arrivals, mut departures) = (Vec::new(), Vec::new(), Vec::new());
        for i in 0..len {
            if i > 0 {
                time += rng.between(60, 600);
            }
            let arrival = time;
            time += rng.between(0, 2) * 30; // occasional dwell
            path.push(StopIdx(rng.below(stops)));
            arrivals.push(Time(arrival));
            departures.push(Time(time));
        }
        trips.push(TripInput { trip_id, stops: path, arrivals, departures });
    }
    // Many short walks, so walking in often races alighting at the same stop.
    let footpaths = (0..rng.below(25))
        .map(|_| (StopIdx(rng.below(stops)), StopIdx(rng.below(stops)), rng.between(30, 240)))
        .collect();
    // About a third of the stops are platforms of one of three stations, with up to 5 minutes
    // of entry time; footpaths between platforms of a station exercise the in-station waiver.
    let entry =
        (0..stops)
            .map(|_| {
                if rng.below(3) == 0 {
                    (Some(rng.below(3)), rng.between(1, 300))
                } else {
                    (None, 0)
                }
            })
            .collect();
    Network { stops, trips, footpaths, entry }
}

fn timetable(network: &Network) -> Timetable {
    let mut builder = TimetableBuilder::new(network.stops);
    for trip in &network.trips {
        builder.add_trip(trip.clone()).unwrap();
    }
    for &(from, to, duration) in &network.footpaths {
        builder.add_footpath(from, to, duration).unwrap();
    }
    for (stop, &(station, seconds)) in network.entry.iter().enumerate() {
        if let Some(station) = station {
            builder
                .set_station_entry(StopIdx(u32::try_from(stop).unwrap()), station, seconds)
                .unwrap();
        }
    }
    builder.build().0
}

/// Connection Scan earliest arrival with the same rules as the router: the minimum transfer
/// time applies after riding, staying seated needs none, one footpath follows each ride, and
/// walking onto a stop from the origin or from outside its station adds its entry time.
fn oracle(network: &Network, origins: &[Access], departure: Time, mtt: u32) -> Vec<Time> {
    let n = network.stops as usize;
    let (mut ride, mut walk) = (vec![Time::UNREACHED; n], vec![Time::UNREACHED; n]);
    for o in origins {
        let s = o.stop.0 as usize;
        walk[s] = walk[s].min(departure.saturating_add(o.duration + network.entry[s].1));
    }
    let mut connections: Vec<(Time, u32, usize, usize, usize, Time)> = Vec::new();
    for (t, trip) in network.trips.iter().enumerate() {
        for i in 0..trip.stops.len() - 1 {
            let (from, to) = (trip.stops[i].0 as usize, trip.stops[i + 1].0 as usize);
            connections.push((trip.departures[i], trip.trip_id, i, from, to, trip.arrivals[i + 1]));
            let _ = t;
        }
    }
    connections.sort_unstable();
    let mut seated = vec![false; network.trips.len()];
    for (dep, trip_id, _, from, to, arr) in connections {
        let ready = walk[from].min(ride[from].saturating_add(mtt));
        let trip = trip_id as usize;
        if !(seated[trip] || ready <= dep) {
            continue;
        }
        seated[trip] = true;
        if arr < ride[to] {
            ride[to] = arr;
            for &(f, target, duration) in &network.footpaths {
                if f.0 as usize == to {
                    let t = target.0 as usize;
                    let entry = network.entry_from(StopIdx(u32::try_from(to).unwrap()), target);
                    walk[t] = walk[t].min(arr.saturating_add(duration + entry));
                }
            }
        }
    }
    ride.iter().zip(&walk).map(|(r, w)| *r.min(w)).collect()
}

/// Replay a journey against the timetable and the transfer rules.
fn check_feasible(network: &Network, journey: &Journey, mtt: u32) {
    let mut clock = journey.departure;
    let mut after_ride = false;
    // A zero-second access walk has no leg, but its stop's entry time is still paid.
    if let Some(Leg::Ride { from, .. } | Leg::Egress { from, .. }) = journey.legs.first() {
        clock = clock.saturating_add(network.entry[from.0 as usize].1);
    }
    for leg in &journey.legs {
        match *leg {
            Leg::Access { to, duration } => {
                clock = clock.saturating_add(duration + network.entry[to.0 as usize].1);
            }
            Leg::Egress { duration, .. } => clock = clock.saturating_add(duration),
            Leg::Transfer { from, to, duration } => {
                assert!(after_ride, "a transfer walk must follow a ride: {journey:#?}");
                clock = clock.saturating_add(duration + network.entry_from(from, to));
                after_ride = false;
            }
            Leg::Ride { trip_id, from, to, board, alight, .. } => {
                let ready = if after_ride { clock.saturating_add(mtt) } else { clock };
                assert!(board >= ready, "boarded before ready: {journey:#?}");
                let trip = network.trips.iter().find(|t| t.trip_id == trip_id).unwrap();
                let calls = |stop, times: &[Time], at: Time| {
                    trip.stops.iter().zip(times).any(|(s, &time)| *s == stop && time == at)
                };
                assert!(calls(from, &trip.departures, board), "no such boarding: {journey:#?}");
                assert!(calls(to, &trip.arrivals, alight), "no such alighting: {journey:#?}");
                assert!(alight > board, "ride goes nowhere: {journey:#?}");
                clock = alight;
                after_ride = true;
            }
        }
    }
    assert_eq!(clock, journey.arrival, "legs do not add up: {journey:#?}");
}

#[test]
fn raptor_matches_connection_scan_on_random_networks() {
    let mut rng = Rng(20_261_006);
    let mut compared = 0;
    for case in 0..3_000 {
        let network = random_network(&mut rng);
        let tt = timetable(&network);
        let mtt = [0, 60, 120, 300][rng.below(4) as usize];
        let params = Params { max_rounds: 40, min_transfer_time: mtt };
        let origins: Vec<Access> = (0..rng.between(1, 2))
            .map(|_| Access { stop: StopIdx(rng.below(network.stops)), duration: rng.below(300) })
            .collect();
        let departure = Time(rng.between(7 * 3600, 8 * 3600));

        let expected = oracle(&network, &origins, departure, mtt);
        let profile = search(&tt, &params, &origins, departure, &[]);
        for (s, &want) in expected.iter().enumerate() {
            let got = profile.earliest_arrival(StopIdx(u32::try_from(s).unwrap()));
            let want = (want != Time::UNREACHED).then_some(want);
            assert_eq!(got, want, "case {case}, stop {s}, mtt {mtt}");
            compared += 1;
        }

        // One-to-one plans: the last journey is the earliest; all are feasible and Pareto.
        let target = StopIdx(rng.below(network.stops));
        let egress = rng.below(200);
        let journeys =
            plan(&tt, &params, &origins, departure, &[Access { stop: target, duration: egress }]);
        let want = expected[target.0 as usize];
        match journeys.last() {
            None => assert_eq!(want, Time::UNREACHED, "case {case}: missed a journey"),
            Some(best) => assert_eq!(best.arrival, want.saturating_add(egress), "case {case}"),
        }
        for pair in journeys.windows(2) {
            assert!(pair[1].rides() > pair[0].rides() && pair[1].arrival < pair[0].arrival);
        }
        for journey in &journeys {
            check_feasible(&network, journey, mtt);
        }
    }
    assert!(compared > 2_000);
}

#[test]
fn more_rounds_never_make_arrivals_later() {
    let mut rng = Rng(7);
    for _ in 0..200 {
        let network = random_network(&mut rng);
        let tt = timetable(&network);
        let origins = [Access { stop: StopIdx(0), duration: 0 }];
        let departure = Time(7 * 3600);
        let mut previous: Option<Vec<Option<Time>>> = None;
        for rounds in 1..=5 {
            let params = Params { max_rounds: rounds, min_transfer_time: 60 };
            let profile = search(&tt, &params, &origins, departure, &[]);
            let arrivals: Vec<_> =
                (0..network.stops).map(|s| profile.earliest_arrival(StopIdx(s))).collect();
            if let Some(prev) = &previous {
                for (before, after) in prev.iter().zip(&arrivals) {
                    match (before, after) {
                        (Some(b), Some(a)) => assert!(a <= b),
                        (Some(_), None) => panic!("a stop became unreachable with more rounds"),
                        _ => {}
                    }
                }
            }
            previous = Some(arrivals);
        }
    }
}
