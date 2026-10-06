//! Round-based search (Delling, Pajor, Werneck 2012, §3).
//!
//! Round `k` finds the earliest arrivals using at most `k` vehicles. Two arrival labels are kept
//! per stop and round, because the minimum transfer time applies only after riding:
//!
//! * `ride` — reached by alighting from a vehicle; boarding again needs `min_transfer_time`.
//! * `walk` — reached on foot (access walk or a footpath); boarding needs no extra time.
//!
//! Keeping only the earlier of the two would be wrong: a stop reached by vehicle at 08:10 and
//! on foot at 08:10:30 is ready for boarding at 08:10:30, not 08:11. Footpaths are relaxed only
//! from `ride` arrivals, so a journey never has two walking legs in a row.

use crate::{RouteIdx, StopIdx, Time, Timetable};

/// Search parameters (Assumed values come from `city.toml [routing]`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Params {
    /// Maximum number of vehicles per journey.
    pub max_rounds: usize,
    /// Seconds needed between alighting and boarding another vehicle at the same stop.
    pub min_transfer_time: u32,
}

/// A walk between the origin (or destination) and a stop, in seconds.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Access {
    pub stop: StopIdx,
    pub duration: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Via {
    Ride,
    Walk,
}

/// How a label was set; enough to walk a journey backwards.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Label {
    /// Not improved in this round (the arrival is inherited from an earlier round).
    None,
    Access {
        duration: u32,
    },
    Ride {
        route: RouteIdx,
        trip: u32,
        board_pos: u32,
        alight_pos: u32,
        boarded_via: Via,
    },
    Walk {
        from: StopIdx,
        duration: u32,
    },
}

#[derive(Debug, Clone)]
pub(crate) struct Round {
    pub(crate) ride: Vec<Time>,
    pub(crate) walk: Vec<Time>,
    pub(crate) ride_label: Vec<Label>,
    pub(crate) walk_label: Vec<Label>,
}

impl Round {
    pub(crate) fn unreached(stops: usize) -> Self {
        Self {
            ride: vec![Time::UNREACHED; stops],
            walk: vec![Time::UNREACHED; stops],
            ride_label: vec![Label::None; stops],
            walk_label: vec![Label::None; stops],
        }
    }

    /// Next round starts from this round's arrivals; labels record only new improvements.
    fn inherit(&self) -> Self {
        let stops = self.ride.len();
        Self {
            ride: self.ride.clone(),
            walk: self.walk.clone(),
            ride_label: vec![Label::None; stops],
            walk_label: vec![Label::None; stops],
        }
    }
}

/// All rounds of one search from one departure time.
#[derive(Debug, Clone)]
pub struct Profile<'a> {
    pub(crate) tt: &'a Timetable,
    pub(crate) departure: Time,
    pub(crate) rounds: Vec<Round>,
}

impl Profile<'_> {
    /// Earliest arrival at `stop` with any number of vehicles (up to `max_rounds`).
    #[must_use]
    pub fn earliest_arrival(&self, stop: StopIdx) -> Option<Time> {
        let last = self.rounds.last()?;
        let s = stop.0 as usize;
        let best = last.ride[s].min(last.walk[s]);
        (best != Time::UNREACHED).then_some(best)
    }

    /// Earliest arrival at `stop` using at most `vehicles` vehicles.
    #[must_use]
    pub fn arrival_with(&self, vehicles: usize, stop: StopIdx) -> Option<Time> {
        let round = self.rounds.get(vehicles.min(self.rounds.len() - 1))?;
        let s = stop.0 as usize;
        let best = round.ride[s].min(round.walk[s]);
        (best != Time::UNREACHED).then_some(best)
    }

    /// Number of rounds actually run, including round 0 (walking only).
    #[must_use]
    pub fn rounds_run(&self) -> usize {
        self.rounds.len()
    }

    #[must_use]
    pub fn departure(&self) -> Time {
        self.departure
    }

    #[must_use]
    pub fn timetable(&self) -> &Timetable {
        self.tt
    }
}

/// Run the round-based search from `origins` (access walks) leaving at `departure`.
///
/// `egress` (possibly empty) enables target pruning: once some destination is reachable by a
/// given time, no label at or after that time is kept.
///
/// # Panics
/// If the timetable has more than `u32::MAX` stops or routes.
#[must_use]
pub fn search<'a>(
    tt: &'a Timetable,
    params: &Params,
    origins: &[Access],
    departure: Time,
    egress: &[Access],
) -> Profile<'a> {
    let mut state = Search::new(tt, *params, egress);
    let mut rounds = vec![state.initial_round(origins, departure)];
    for _ in 1..=params.max_rounds {
        state.collect_routes();
        if state.queued.is_empty() {
            break;
        }
        let prev = rounds.last().expect("round 0 exists");
        let mut cur = prev.inherit();
        let rode = state.scan_routes(prev, &mut cur);
        state.relax_footpaths(&mut cur, rode);
        rounds.push(cur);
        if !state.marked.iter().any(|&m| m) {
            break;
        }
    }
    Profile { tt, departure, rounds }
}

/// Working state shared by the steps of one search.
pub(crate) struct Search<'a> {
    tt: &'a Timetable,
    params: Params,
    egress_at: Vec<u32>,
    /// Earliest arrival at any destination so far (target pruning).
    bound: Time,
    pub(crate) marked: Vec<bool>,
    /// Earliest arrival per stop over all rounds (and, in range searches, later departures).
    pub(crate) best: Vec<Time>,
    /// Stops whose ride arrival improved in the current round (for footpath relaxation).
    rode: Vec<bool>,
    /// Per route: earliest marked position, or `u32::MAX` if not queued.
    queue: Vec<u32>,
    pub(crate) queued: Vec<usize>,
}

impl<'a> Search<'a> {
    pub(crate) fn new(tt: &'a Timetable, params: Params, egress: &[Access]) -> Self {
        let n = tt.stop_count();
        let mut egress_at = vec![u32::MAX; n];
        for e in egress {
            let slot = &mut egress_at[e.stop.0 as usize];
            *slot = (*slot).min(e.duration);
        }
        Self {
            tt,
            params,
            egress_at,
            bound: Time::UNREACHED,
            marked: vec![false; n],
            best: vec![Time::UNREACHED; n],
            rode: vec![false; n],
            queue: vec![u32::MAX; tt.route_count()],
            queued: Vec::new(),
        }
    }

    pub(crate) fn reached(&mut self, stop: usize, arrival: Time) {
        self.marked[stop] = true;
        self.best[stop] = self.best[stop].min(arrival);
        if self.egress_at[stop] != u32::MAX {
            self.bound = self.bound.min(arrival.saturating_add(self.egress_at[stop]));
        }
    }

    /// Round 0: walking from the origin to nearby stops.
    fn initial_round(&mut self, origins: &[Access], departure: Time) -> Round {
        let mut first = Round::unreached(self.tt.stop_count());
        for o in origins {
            let s = o.stop.0 as usize;
            let arrival = departure.saturating_add(o.duration);
            if arrival < first.walk[s] {
                first.walk[s] = arrival;
                first.walk_label[s] = Label::Access { duration: o.duration };
            }
        }
        for s in 0..first.walk.len() {
            if first.walk[s] != Time::UNREACHED {
                self.reached(s, first.walk[s]);
            }
        }
        first
    }

    /// Queue each route serving a marked stop, from the earliest marked position on it.
    pub(crate) fn collect_routes(&mut self) {
        for s in 0..self.marked.len() {
            if !self.marked[s] {
                continue;
            }
            self.marked[s] = false;
            for &(route, position) in self.tt.routes_serving(StopIdx(to_u32(s))) {
                let r = route.0 as usize;
                if self.queue[r] == u32::MAX {
                    self.queued.push(r);
                }
                self.queue[r] = self.queue[r].min(position);
            }
        }
        self.queued.sort_unstable(); // deterministic tie-breaking between routes
    }

    /// Ride every queued route; returns the stops whose ride arrival improved.
    pub(crate) fn scan_routes(&mut self, prev: &Round, cur: &mut Round) -> Vec<usize> {
        let mut rode = Vec::new();
        let queued = std::mem::take(&mut self.queued);
        for &r in &queued {
            let route = self.tt.route(RouteIdx(to_u32(r)));
            let start = self.queue[r] as usize;
            self.queue[r] = u32::MAX;
            let mut boarded: Option<(usize, usize, Via)> = None; // (trip, board_pos, via)
            for (pos, stop) in route.stops().iter().enumerate().skip(start) {
                let s = stop.0 as usize;
                if let Some((trip, board_pos, via)) = boarded {
                    let arrival = route.arrival(trip, pos);
                    if arrival < cur.ride[s] && arrival < self.bound {
                        if !self.rode[s] {
                            self.rode[s] = true;
                            rode.push(s);
                        }
                        cur.ride[s] = arrival;
                        cur.ride_label[s] = Label::Ride {
                            route: RouteIdx(to_u32(r)),
                            trip: to_u32(trip),
                            board_pos: to_u32(board_pos),
                            alight_pos: to_u32(pos),
                            boarded_via: via,
                        };
                        self.reached(s, arrival);
                    }
                }
                // Could we catch an earlier trip here, given the previous round's arrivals?
                let after_ride = prev.ride[s].saturating_add(self.params.min_transfer_time);
                let (ready, via) = if prev.walk[s] <= after_ride {
                    (prev.walk[s], Via::Walk)
                } else {
                    (after_ride, Via::Ride)
                };
                if ready == Time::UNREACHED {
                    continue;
                }
                let before = boarded.map_or(route.trip_count(), |(trip, _, _)| trip);
                if let Some(trip) = route.earliest_trip(pos, ready, before) {
                    boarded = Some((trip, pos, via));
                }
            }
        }
        self.queued = queued;
        self.queued.clear();
        rode
    }

    /// One walking leg after each ride (never after another walk).
    pub(crate) fn relax_footpaths(&mut self, cur: &mut Round, mut rode: Vec<usize>) {
        rode.sort_unstable();
        for s in rode {
            self.rode[s] = false;
            let arrival = cur.ride[s];
            for footpath in self.tt.footpaths(StopIdx(to_u32(s))) {
                let to = footpath.to.0 as usize;
                let walked = arrival.saturating_add(footpath.duration);
                if walked < cur.walk[to] && walked < self.bound {
                    cur.walk[to] = walked;
                    cur.walk_label[to] =
                        Label::Walk { from: StopIdx(to_u32(s)), duration: footpath.duration };
                    self.reached(to, walked);
                }
            }
        }
    }
}

pub(crate) fn to_u32(value: usize) -> u32 {
    u32::try_from(value).expect("index exceeds u32")
}
