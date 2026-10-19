//! Which journey a departure takes to a zone: the rule shared by the path table and assignment.
//!
//! The travel-time matrix, the path table and the assignment must agree on it, or flows would
//! follow journeys the matrix never timed: the earliest arrival over the zone's egress stops
//! (ties to the lower stop), unless walking all the way is at least as fast.

use crate::journey::{rebuild, Journey};
use crate::matrix::NOT_REACHED;
use crate::raptor::Round;
use crate::{StopIdx, Time, Timetable};

pub(crate) enum Choice {
    /// Neither walking nor transit arrives within the limit.
    NotReached,
    /// Walking all the way is at least as fast as transit.
    Walked,
    Transit(Journey),
}

/// The choice for one departure, given the range search's state after it.
pub(crate) fn choose(
    tt: &Timetable,
    departure: Time,
    rounds: &[Round],
    best: &[Time],
    egress: &[(StopIdx, u32)],
    on_foot: u32,
    max_travel_time: u32,
) -> Choice {
    let mut by_transit = NOT_REACHED;
    let mut via: Option<(StopIdx, u32)> = None;
    for &(stop, seconds) in egress {
        let at = best[stop.0 as usize];
        if at == Time::UNREACHED {
            continue;
        }
        let duration = at.0 - departure.0 + seconds;
        if duration < by_transit {
            by_transit = duration;
            via = Some((stop, seconds));
        }
    }
    if on_foot <= by_transit {
        return if on_foot <= max_travel_time { Choice::Walked } else { Choice::NotReached };
    }
    let Some((stop, seconds)) = via else { return Choice::NotReached };
    if by_transit > max_travel_time {
        return Choice::NotReached;
    }
    let s = stop.0 as usize;
    let arrival = best[s];
    let round = rounds
        .iter()
        .position(|r| r.ride[s].min(r.arrived_on_foot(s)) == arrival)
        .expect("the best arrival comes from some round");
    Choice::Transit(rebuild(
        tt,
        departure,
        rounds,
        round,
        stop,
        seconds,
        arrival.saturating_add(seconds),
    ))
}
