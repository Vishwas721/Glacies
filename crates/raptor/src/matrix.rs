//! Zone-to-zone travel times over a departure window (Phase 3 M2).
//!
//! For one origin, a range search gives the earliest arrival at every stop for every departure.
//! A destination zone is reached from the stops near it (an egress walk) or on foot all the way;
//! its travel time for a departure is the earliest of those, minus the departure, so waiting
//! for the first vehicle counts. Percentiles over the window then say how reliably the zone is
//! reached, with "not reached" counted as infinitely long: if fewer than half the departures
//! reach a zone, its median is not reached either.

use std::fmt;

use crate::{range_search, Access, Params, StopIdx, Time, Timetable};

/// Marks a percentile above the travel-time limit (or never reached).
pub const NOT_REACHED: u32 = u32::MAX;

/// Why zone inputs were rejected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MatrixError {
    UnknownZone { zone: u32 },
    BadPercentile { percentile: u8 },
}

impl fmt::Display for MatrixError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownZone { zone } => write!(f, "unknown zone {zone}"),
            Self::BadPercentile { percentile } => {
                write!(f, "percentile {percentile} is not in 1..=100")
            }
        }
    }
}

impl std::error::Error for MatrixError {}

/// Egress walks from stops to each destination zone, grouped by zone (CSR).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ZoneEgress {
    starts: Vec<u32>,
    walks: Vec<(StopIdx, u32)>,
}

impl ZoneEgress {
    /// `walks` are `(zone, stop, seconds)`; any order.
    ///
    /// # Errors
    /// If a zone is `>= zone_count`.
    ///
    /// # Panics
    /// If there are more than `u32::MAX` walks.
    pub fn new(zone_count: usize, walks: &[(u32, StopIdx, u32)]) -> Result<Self, MatrixError> {
        let mut by_zone: Vec<Vec<(StopIdx, u32)>> = vec![Vec::new(); zone_count];
        for &(zone, stop, seconds) in walks {
            by_zone
                .get_mut(zone as usize)
                .ok_or(MatrixError::UnknownZone { zone })?
                .push((stop, seconds));
        }
        let mut starts = Vec::with_capacity(zone_count + 1);
        let mut flat = Vec::with_capacity(walks.len());
        starts.push(0);
        for mut list in by_zone {
            list.sort_unstable();
            flat.extend(list);
            starts.push(u32::try_from(flat.len()).expect("walk count fits u32"));
        }
        Ok(Self { starts, walks: flat })
    }

    #[must_use]
    pub fn zone_count(&self) -> usize {
        self.starts.len() - 1
    }

    pub(crate) fn of(&self, zone: usize) -> &[(StopIdx, u32)] {
        &self.walks[self.starts[zone] as usize..self.starts[zone + 1] as usize]
    }
}

/// Percentile travel times (seconds) from one origin to the zones it reaches.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ZoneTimes {
    /// Zones whose lowest requested percentile is within the limit, ascending.
    pub zones: Vec<u32>,
    /// Row-major, one row per zone, one column per requested percentile; [`NOT_REACHED`] above
    /// the limit.
    pub times: Vec<u32>,
}

/// Nearest-rank percentile of sorted values: the smallest value with at least `p` % of the
/// values at or below it.
fn nearest_rank(sorted: &[u32], percentile: u8) -> u32 {
    let n = sorted.len();
    let rank = (usize::from(percentile) * n).div_ceil(100).clamp(1, n);
    sorted[rank - 1]
}

/// Travel-time percentiles from one origin to every zone over `departures`.
///
/// `walk_only` gives zones reachable on foot from the origin, with seconds; they are reached at
/// that duration whatever the departure. Zones are kept only if their lowest requested
/// percentile is at most `max_travel_time` seconds.
///
/// # Errors
/// If a `walk_only` zone is unknown or a percentile is outside `1..=100`.
///
/// # Panics
/// If an egress stop is not in the timetable.
#[allow(clippy::too_many_arguments)] // the inputs of one matrix row
pub fn zone_travel_times(
    tt: &Timetable,
    params: &Params,
    origin: &[Access],
    departures: &[Time],
    egress: &ZoneEgress,
    walk_only: &[(u32, u32)],
    percentiles: &[u8],
    max_travel_time: u32,
) -> Result<ZoneTimes, MatrixError> {
    if let Some(&percentile) = percentiles.iter().find(|&&p| p == 0 || p > 100) {
        return Err(MatrixError::BadPercentile { percentile });
    }
    let zones = egress.zone_count();
    let mut walk = vec![NOT_REACHED; zones];
    for &(zone, seconds) in walk_only {
        let slot = walk.get_mut(zone as usize).ok_or(MatrixError::UnknownZone { zone })?;
        *slot = (*slot).min(seconds);
    }
    let profile = range_search(tt, params, origin, departures);

    let mut result = ZoneTimes { zones: Vec::new(), times: Vec::new() };
    let lowest = percentiles.iter().copied().min();
    let mut samples = vec![NOT_REACHED; departures.len()];
    for (zone, &on_foot) in walk.iter().enumerate() {
        let walks = egress.of(zone);
        if walks.is_empty() && on_foot == NOT_REACHED {
            continue;
        }
        for (i, departure) in departures.iter().enumerate() {
            let arrivals = profile.arrivals(i);
            let mut best = on_foot;
            for &(stop, seconds) in walks {
                let at = arrivals[stop.0 as usize];
                if at != Time::UNREACHED {
                    best = best.min(at.0 - departure.0 + seconds);
                }
            }
            samples[i] = best;
        }
        samples.sort_unstable();
        let row: Vec<u32> = percentiles
            .iter()
            .map(|&p| {
                let value = nearest_rank(&samples, p);
                if value <= max_travel_time {
                    value
                } else {
                    NOT_REACHED
                }
            })
            .collect();
        let kept = lowest.is_some_and(|p| nearest_rank(&samples, p) <= max_travel_time);
        if kept && !samples.is_empty() {
            result.zones.push(u32::try_from(zone).expect("zone fits u32"));
            result.times.extend(row);
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::nearest_rank;

    #[test]
    fn nearest_rank_percentiles() {
        let values = [10, 20, 30, 40];
        assert_eq!([25, 50, 75, 100].map(|p| nearest_rank(&values, p)), [10, 20, 30, 40]);
        assert_eq!(nearest_rank(&values, 1), 10);
        assert_eq!(nearest_rank(&values, 51), 30);
        assert_eq!(nearest_rank(&[7], 50), 7);
    }
}
