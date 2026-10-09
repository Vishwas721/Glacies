//! Which metro stations journeys enter and leave, per zone pair (Phase 5 M3).
//!
//! Ridership is counted at fare gates, so a simulated journey is reduced to its metro
//! *segments*: consecutive metro rides joined only by changes inside one station (no new
//! gate) form one segment from the entry station to the exit station. Walking to another
//! station, or riding a bus in between, starts a new segment.
//!
//! For one origin, the range search gives the best journey at every departure; for each target
//! zone the journey chosen is the earliest arrival over its egress stops, unless walking all
//! the way is at least as fast (as in the travel-time matrix). The result counts, per target,
//! the departures that reach it within the limit, those reached on foot, and each metro
//! segment. Those counts do not depend on demand, so the same table maps any OD matrix to
//! station flows.

use std::collections::BTreeMap;

use crate::journey::rebuild;
use crate::matrix::{MatrixError, ZoneEgress, NOT_REACHED};
use crate::range::range_search_each;
use crate::{Access, Leg, Params, StopIdx, Time, Timetable};

/// Marks a stop that belongs to no metro station.
pub const NO_STATION: u32 = u32::MAX;

/// Which trips are metro and which station each stop belongs to.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MetroNetwork {
    /// Indexed by trip id (as given to the timetable builder).
    pub metro_trip: Vec<bool>,
    /// Indexed by stop; [`NO_STATION`] for stops outside the metro.
    pub station: Vec<u32>,
}

impl MetroNetwork {
    fn is_metro(&self, trip_id: u32) -> bool {
        self.metro_trip.get(trip_id as usize).copied().unwrap_or(false)
    }

    fn station_of(&self, stop: StopIdx) -> u32 {
        self.station.get(stop.0 as usize).copied().unwrap_or(NO_STATION)
    }

    /// `(entry station, exit station)` of each metro segment of `legs`, in order.
    #[must_use]
    pub fn segments(&self, legs: &[Leg]) -> Vec<(u32, u32)> {
        let mut segments = Vec::new();
        let mut open: Option<(u32, u32)> = None;
        for leg in legs {
            match *leg {
                Leg::Ride { trip_id, from, to, .. } if self.is_metro(trip_id) => {
                    let (entry, exit) = (self.station_of(from), self.station_of(to));
                    open = Some(open.map_or((entry, exit), |(first, _)| (first, exit)));
                }
                Leg::Transfer { from, to, .. } => {
                    let same = self.station_of(from) != NO_STATION
                        && self.station_of(from) == self.station_of(to);
                    if !same {
                        segments.extend(open.take());
                    }
                }
                Leg::Ride { .. } => segments.extend(open.take()),
                Leg::Access { .. } | Leg::Egress { .. } => {}
            }
        }
        segments.extend(open);
        segments
    }
}

/// Departure counts from one origin to each target zone.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ZonePaths {
    /// Target zones in the order given.
    pub zones: Vec<u32>,
    /// Departures reaching each target within the limit (on foot or by transit).
    pub reached: Vec<u32>,
    /// Of those, departures where walking all the way is at least as fast.
    pub walked: Vec<u32>,
    /// Of those, departures whose journey has at least one metro segment.
    pub metro: Vec<u32>,
    /// `(target position, entry station, exit station, departures)`, sorted.
    pub segments: Vec<(u32, u32, u32, u32)>,
}

/// Count, for every departure, how the best journey from `origin` reaches each of `targets`.
///
/// # Errors
/// If a `walk_only` zone or a target is unknown.
///
/// # Panics
/// If an egress stop is not in the timetable.
#[allow(clippy::too_many_arguments)] // the inputs of one matrix row, plus the metro
pub fn zone_paths(
    tt: &Timetable,
    params: &Params,
    origin: &[Access],
    departures: &[Time],
    egress: &ZoneEgress,
    walk_only: &[(u32, u32)],
    targets: &[u32],
    metro: &MetroNetwork,
    max_travel_time: u32,
) -> Result<ZonePaths, MatrixError> {
    let zones = egress.zone_count();
    let mut walk = vec![NOT_REACHED; zones];
    for &(zone, seconds) in walk_only {
        let slot = walk.get_mut(zone as usize).ok_or(MatrixError::UnknownZone { zone })?;
        *slot = (*slot).min(seconds);
    }
    if let Some(&zone) = targets.iter().find(|&&z| z as usize >= zones) {
        return Err(MatrixError::UnknownZone { zone });
    }
    let mut reached = vec![0_u32; targets.len()];
    let mut walked = vec![0_u32; targets.len()];
    let mut metro_used = vec![0_u32; targets.len()];
    let mut counts: BTreeMap<(u32, u32, u32), u32> = BTreeMap::new();
    range_search_each(tt, params, origin, departures, |i, rounds, best| {
        let departure = departures[i];
        for (pos, &zone) in targets.iter().enumerate() {
            let on_foot = walk[zone as usize];
            // Earliest arrival over the egress stops; ties go to the lower stop.
            let mut by_transit = NOT_REACHED;
            let mut via: Option<(StopIdx, u32)> = None;
            for &(stop, seconds) in egress.of(zone as usize) {
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
                if on_foot <= max_travel_time {
                    reached[pos] += 1;
                    walked[pos] += 1;
                }
                continue;
            }
            let Some((stop, seconds)) = via else { continue };
            if by_transit > max_travel_time {
                continue;
            }
            reached[pos] += 1;
            let s = stop.0 as usize;
            let arrival = best[s];
            let round = rounds
                .iter()
                .position(|r| r.ride[s].min(r.walk[s]) == arrival)
                .expect("the best arrival comes from some round");
            let journey = rebuild(
                tt,
                departure,
                rounds,
                round,
                stop,
                seconds,
                arrival.saturating_add(seconds),
            );
            let segments = metro.segments(&journey.legs);
            if !segments.is_empty() {
                metro_used[pos] += 1;
            }
            for (entry, exit) in segments {
                *counts.entry((u32::try_from(pos).expect("fits u32"), entry, exit)).or_insert(0) +=
                    1;
            }
        }
    });
    Ok(ZonePaths {
        zones: targets.to_vec(),
        reached,
        walked,
        metro: metro_used,
        segments: counts.into_iter().map(|((pos, entry, exit), n)| (pos, entry, exit, n)).collect(),
    })
}
