//! All-or-nothing assignment of zone-to-zone demand to scheduled trips (Phase 6 M1).
//!
//! Each OD pair's trips are spread over the departures that reach the destination within the
//! limit, in proportion to the departure-time profile, and each departure follows its fastest
//! journey (the rule of the travel-time matrix and the path table, see [`crate::choice`]).
//! Flows are expected values rather than samples: an OD pair carries a fraction of a trip on
//! average, so sampling would mostly add noise, and the totals stay exact.

use std::collections::BTreeMap;

use crate::choice::{choose, Choice};
use crate::matrix::{MatrixError, ZoneEgress, NOT_REACHED};
use crate::range::range_search_each;
use crate::{Access, Leg, Params, Time, Timetable};

/// Departure times and the share of trips leaving at each (any positive scale).
#[derive(Debug, Clone, Copy)]
pub struct DepartureProfile<'a> {
    pub times: &'a [Time],
    pub weights: &'a [f64],
}

/// One origin's trips, split by how they travel, and the rides they make.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ZoneAssignment {
    /// Target zones in the order given.
    pub zones: Vec<u32>,
    /// Trips on a transit journey.
    pub transit: Vec<f64>,
    /// Trips for which walking all the way is at least as fast.
    pub walked: Vec<f64>,
    /// Trips no departure in the window delivers within the limit.
    pub unreached: Vec<f64>,
    /// `(trip_id, board_pos, alight_pos, passengers)`, sorted, summed over all targets.
    pub rides: Vec<(u32, u32, u32, f64)>,
}

/// Assign `trips[k]` trips from `origin` to `targets[k]` for every k.
///
/// # Errors
/// If a `walk_only` zone or a target is unknown, or the profile's arrays differ in length.
///
/// # Panics
/// If there are more than `u32::MAX` targets.
#[allow(clippy::too_many_arguments)] // the inputs of one matrix row, plus the demand
pub fn zone_assign(
    tt: &Timetable,
    params: &Params,
    origin: &[Access],
    profile: DepartureProfile<'_>,
    egress: &ZoneEgress,
    walk_only: &[(u32, u32)],
    targets: &[u32],
    trips: &[f64],
    max_travel_time: u32,
) -> Result<ZoneAssignment, MatrixError> {
    let zones = egress.zone_count();
    let mut walk = vec![NOT_REACHED; zones];
    for &(zone, seconds) in walk_only {
        let slot = walk.get_mut(zone as usize).ok_or(MatrixError::UnknownZone { zone })?;
        *slot = (*slot).min(seconds);
    }
    if let Some(&zone) = targets.iter().find(|&&z| z as usize >= zones) {
        return Err(MatrixError::UnknownZone { zone });
    }
    if targets.len() != trips.len() || profile.times.len() != profile.weights.len() {
        return Err(MatrixError::LengthMismatch);
    }
    // Profile weight of the departures that reach each target, walk all the way, and ride each
    // trip segment; scaled to trips once every departure has been seen.
    let mut reached = vec![0.0_f64; targets.len()];
    let mut walked = vec![0.0_f64; targets.len()];
    let mut weights: BTreeMap<(u32, u32, u32, u32), f64> = BTreeMap::new();
    range_search_each(tt, params, origin, profile.times, |i, rounds, best| {
        let (departure, weight) = (profile.times[i], profile.weights[i]);
        for (pos, &zone) in targets.iter().enumerate() {
            let journey = match choose(
                tt,
                departure,
                rounds,
                best,
                egress.of(zone as usize),
                walk[zone as usize],
                max_travel_time,
            ) {
                Choice::NotReached => continue,
                Choice::Walked => {
                    reached[pos] += weight;
                    walked[pos] += weight;
                    continue;
                }
                Choice::Transit(journey) => journey,
            };
            reached[pos] += weight;
            let target = u32::try_from(pos).expect("fits u32");
            for leg in &journey.legs {
                if let Leg::Ride { trip_id, board_pos, alight_pos, .. } = *leg {
                    *weights.entry((target, trip_id, board_pos, alight_pos)).or_insert(0.0) +=
                        weight;
                }
            }
        }
    });
    let scale: Vec<f64> =
        reached.iter().zip(trips).map(|(&r, &n)| if r > 0.0 { n / r } else { 0.0 }).collect();
    let mut rides: BTreeMap<(u32, u32, u32), f64> = BTreeMap::new();
    for ((target, trip_id, board, alight), weight) in weights {
        *rides.entry((trip_id, board, alight)).or_insert(0.0) += weight * scale[target as usize];
    }
    Ok(ZoneAssignment {
        zones: targets.to_vec(),
        transit: (0..targets.len()).map(|k| (reached[k] - walked[k]) * scale[k]).collect(),
        walked: (0..targets.len()).map(|k| walked[k] * scale[k]).collect(),
        unreached: (0..targets.len())
            .map(|k| if reached[k] > 0.0 { 0.0 } else { trips[k] })
            .collect(),
        rides: rides.into_iter().map(|((t, b, a), n)| (t, b, a, n)).collect(),
    })
}
