//! Journeys rebuilt from a search's labels, and the one-to-one query that returns them.

use crate::raptor::{search, to_u32, Label, Profile, Round, Via};
use crate::{Access, Params, RouteIdx, StopIdx, Time, Timetable};

/// One part of a journey.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Leg {
    /// Walk from the origin to the first stop.
    Access { to: StopIdx, duration: u32 },
    /// Ride one trip from `from` to `to`.
    Ride { route: RouteIdx, trip_id: u32, from: StopIdx, to: StopIdx, board: Time, alight: Time },
    /// Walk between two stops while changing vehicles.
    Transfer { from: StopIdx, to: StopIdx, duration: u32 },
    /// Walk from the last stop to the destination.
    Egress { from: StopIdx, duration: u32 },
}

/// A depart-at journey: leaves the origin at `departure`, reaches the destination at `arrival`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Journey {
    pub departure: Time,
    pub arrival: Time,
    pub legs: Vec<Leg>,
}

impl Journey {
    #[must_use]
    pub fn travel_time(&self) -> u32 {
        self.arrival.0 - self.departure.0
    }

    #[must_use]
    pub fn rides(&self) -> usize {
        self.legs.iter().filter(|l| matches!(l, Leg::Ride { .. })).count()
    }

    /// Changes of vehicle (0 for a direct trip or a walk-only journey).
    #[must_use]
    pub fn transfers(&self) -> usize {
        self.rides().saturating_sub(1)
    }

    #[must_use]
    pub fn walking_time(&self) -> u32 {
        self.legs
            .iter()
            .map(|leg| match *leg {
                Leg::Access { duration, .. }
                | Leg::Transfer { duration, .. }
                | Leg::Egress { duration, .. } => duration,
                Leg::Ride { .. } => 0,
            })
            .sum()
    }

    #[must_use]
    pub fn in_vehicle_time(&self) -> u32 {
        self.legs
            .iter()
            .map(|leg| match *leg {
                Leg::Ride { board, alight, .. } => alight.0 - board.0,
                _ => 0,
            })
            .sum()
    }

    /// Time spent neither walking nor riding: at the origin, at stops and while changing.
    #[must_use]
    pub fn waiting_time(&self) -> u32 {
        self.travel_time() - self.walking_time() - self.in_vehicle_time()
    }
}

/// Journeys from `origins` to `destinations` leaving at `departure`: the fastest journey for
/// each number of vehicles that beats every journey with fewer (a Pareto set on arrival time
/// and transfers), ordered by number of vehicles.
///
/// # Panics
/// If the timetable has more than `u32::MAX` stops or routes.
#[must_use]
pub fn plan(
    tt: &Timetable,
    params: &Params,
    origins: &[Access],
    departure: Time,
    destinations: &[Access],
) -> Vec<Journey> {
    let profile = search(tt, params, origins, departure, destinations);
    let mut journeys = Vec::new();
    let mut best = Time::UNREACHED;
    for round in 0..profile.rounds.len() {
        let Some((arrival, stop, egress)) = best_destination(&profile, round, destinations) else {
            continue;
        };
        if arrival >= best {
            continue;
        }
        best = arrival;
        journeys.push(profile.journey(round, stop, egress, arrival));
    }
    journeys
}

/// Earliest arrival at any destination using the labels of `round`; ties go to the lower stop.
fn best_destination(
    profile: &Profile<'_>,
    round: usize,
    destinations: &[Access],
) -> Option<(Time, StopIdx, u32)> {
    let labels = &profile.rounds[round];
    destinations
        .iter()
        .filter_map(|d| {
            let s = d.stop.0 as usize;
            let at_stop = labels.ride[s].min(labels.walk[s]);
            (at_stop != Time::UNREACHED)
                .then(|| (at_stop.saturating_add(d.duration), d.stop, d.duration))
        })
        .min_by_key(|&(arrival, stop, _)| (arrival, stop))
}

impl Profile<'_> {
    /// Rebuild the journey that reaches `stop` in `round`, then walks `egress` seconds.
    fn journey(&self, round: usize, stop: StopIdx, egress: u32, arrival: Time) -> Journey {
        rebuild(self.tt, self.departure, &self.rounds, round, stop, egress, arrival)
    }
}

/// Rebuild the journey that reaches `stop` in `round` of `rounds`, then walks `egress`
/// seconds to arrive at `arrival`.
pub(crate) fn rebuild(
    tt: &Timetable,
    departure: Time,
    rounds: &[Round],
    round: usize,
    stop: StopIdx,
    egress: u32,
    arrival: Time,
) -> Journey {
    let mut legs = Vec::new();
    if egress > 0 {
        legs.push(Leg::Egress { from: stop, duration: egress });
    }
    let s = stop.0 as usize;
    let last = &rounds[round];
    let mut via = if last.ride[s] <= last.walk[s] { Via::Ride } else { Via::Walk };
    let (mut round, mut stop) = (round, stop);
    loop {
        let (r, label) = label(rounds, round, stop, via);
        match label {
            Label::Access { duration } => {
                if duration > 0 {
                    legs.push(Leg::Access { to: stop, duration });
                }
                break;
            }
            Label::Ride { route, trip, board_pos, alight_pos, boarded_via } => {
                let view = tt.route(route);
                let (trip, board, alight) =
                    (trip as usize, board_pos as usize, alight_pos as usize);
                let from = view.stops()[board];
                legs.push(Leg::Ride {
                    route,
                    trip_id: view.trip_id(trip),
                    from,
                    to: stop,
                    board: view.departure(trip, board),
                    alight: view.arrival(trip, alight),
                });
                (round, stop, via) = (r - 1, from, boarded_via);
            }
            Label::Walk { from, duration } => {
                legs.push(Leg::Transfer { from, to: stop, duration });
                (round, stop, via) = (r, from, Via::Ride);
            }
            Label::None => unreachable!("labels on a reached stop lead back to an origin"),
        }
    }
    legs.reverse();
    Journey { departure, arrival, legs }
}

/// The label that set `stop`'s `via` arrival in `round` or, if inherited, the latest earlier
/// round that did.
fn label(rounds: &[Round], round: usize, stop: StopIdx, via: Via) -> (usize, Label) {
    let s = stop.0 as usize;
    for r in (0..=round).rev() {
        let label = match via {
            Via::Ride => rounds[r].ride_label[s],
            Via::Walk => rounds[r].walk_label[s],
        };
        if label != Label::None {
            return (r, label);
        }
    }
    unreachable!("stop {} has no {via:?} label up to round {round}", to_u32(s))
}
