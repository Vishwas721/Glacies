//! Range RAPTOR (Delling, Pajor, Werneck 2012, §4): earliest arrivals for many departure
//! times from the same origin.
//!
//! Departures are processed from latest to earliest and labels are kept between them: anything
//! reachable leaving at 08:01 is reachable leaving at 08:00 by waiting a minute, so later
//! departures' labels are valid upper bounds and each earlier departure only has to find
//! improvements.

use crate::raptor::{Label, Round, Search};
use crate::{Access, Params, StopIdx, Time, Timetable};

/// Earliest arrival at every stop for every departure time of a range search.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RangeProfile {
    departures: Vec<Time>,
    stop_count: usize,
    /// Departure-major: `arrivals[i * stop_count + s]`.
    arrivals: Vec<Time>,
}

impl RangeProfile {
    /// Departure times in the order they were requested.
    #[must_use]
    pub fn departures(&self) -> &[Time] {
        &self.departures
    }

    /// Earliest arrival at `stop` when leaving at the `i`-th requested departure time.
    #[must_use]
    pub fn arrival(&self, i: usize, stop: StopIdx) -> Option<Time> {
        let arrival = self.arrivals[i * self.stop_count + stop.0 as usize];
        (arrival != Time::UNREACHED).then_some(arrival)
    }

    /// Seconds from the `i`-th departure to arrival at `stop`.
    #[must_use]
    pub fn travel_time(&self, i: usize, stop: StopIdx) -> Option<u32> {
        self.arrival(i, stop).map(|arrival| arrival.0 - self.departures[i].0)
    }

    /// Earliest arrivals at every stop for the `i`-th departure (`Time::UNREACHED` if none).
    #[must_use]
    pub fn arrivals(&self, i: usize) -> &[Time] {
        &self.arrivals[i * self.stop_count..(i + 1) * self.stop_count]
    }
}

/// Earliest arrivals from `origins` for each time in `departures` (any order, duplicates
/// allowed); results are identical to running [`crate::search`] once per departure.
///
/// # Panics
/// If the timetable has more than `u32::MAX` stops or routes.
#[must_use]
pub fn range_search(
    tt: &Timetable,
    params: &Params,
    origins: &[Access],
    departures: &[Time],
) -> RangeProfile {
    let n = tt.stop_count();
    let mut arrivals = vec![Time::UNREACHED; departures.len() * n];
    range_search_each(tt, params, origins, departures, |i, _, best| {
        arrivals[i * n..(i + 1) * n].copy_from_slice(best);
    });
    RangeProfile { departures: departures.to_vec(), stop_count: n, arrivals }
}

/// The range search, calling `visit(i, rounds, best)` after the `i`-th departure is done
/// (latest departure first). `best` is the earliest arrival per stop; `rounds` hold labels
/// that rebuild a journey achieving it (labels kept from later departures are journeys that
/// wait at the origin, so they are valid for this departure too).
pub(crate) fn range_search_each(
    tt: &Timetable,
    params: &Params,
    origins: &[Access],
    departures: &[Time],
    mut visit: impl FnMut(usize, &[Round], &[Time]),
) {
    let n = tt.stop_count();
    let mut order: Vec<usize> = (0..departures.len()).collect();
    order.sort_by(|&a, &b| departures[b].cmp(&departures[a]).then(a.cmp(&b))); // latest first

    let mut state = Search::new(tt, *params, &[]);
    let mut rounds: Vec<Round> = (0..=params.max_rounds).map(|_| Round::unreached(n)).collect();
    for &i in &order {
        let departure = departures[i];
        // Walks first: a stop that can be walked to is reached on foot, and a board-only
        // access to it is ignored (so `best` always comes from some round's label).
        for o in origins.iter().filter(|o| !o.board_only) {
            let s = o.stop.0 as usize;
            let arrival =
                departure.saturating_add(o.duration.saturating_add(tt.entry_time(o.stop)));
            if arrival < rounds[0].walk[s] {
                rounds[0].walk[s] = arrival;
                rounds[0].walk_label[s] = Label::Access { duration: o.duration, board_only: false };
                state.reached(s, arrival);
            }
        }
        for o in origins.iter().filter(|o| o.board_only) {
            let s = o.stop.0 as usize;
            if matches!(rounds[0].walk_label[s], Label::Access { board_only: false, .. }) {
                continue;
            }
            let arrival =
                departure.saturating_add(o.duration.saturating_add(tt.entry_time(o.stop)));
            if arrival < rounds[0].walk[s] {
                rounds[0].walk[s] = arrival;
                rounds[0].walk_label[s] = Label::Access { duration: o.duration, board_only: true };
                state.marked[s] = true; // board here in round 1, but not "reached"
            }
        }
        // Round labels are not copied upwards between rounds: every stored arrival is
        // achievable, and boarding reads the previous round, so results are exact either way
        // (verified against per-departure searches); copying only tightened pruning, with no
        // measurable speed-up.
        for k in 1..=params.max_rounds {
            state.collect_routes();
            if state.queued.is_empty() {
                break;
            }
            let (lower, upper) = rounds.split_at_mut(k);
            let rode = state.scan_routes(&lower[k - 1], &mut upper[0]);
            state.relax_footpaths(&mut upper[0], rode);
            if !state.marked.iter().any(|&m| m) {
                break;
            }
        }
        state.marked.fill(false);
        visit(i, &rounds, &state.best);
    }
}
