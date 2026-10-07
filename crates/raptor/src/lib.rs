//! RAPTOR (Round-bAsed Public Transit Optimized Router) core for Glacies.
//!
//! See `docs/phases/02-routing-engine.md` for the implementation plan.

mod journey;
mod matrix;
mod range;
mod raptor;
mod timetable;
mod walkgraph;

pub use journey::{plan, Journey, Leg};
pub use matrix::{zone_travel_times, MatrixError, ZoneEgress, ZoneTimes, NOT_REACHED};
pub use range::{range_search, RangeProfile};
pub use raptor::{search, Access, Params, Profile};
pub use timetable::{
    BuildError, BuildReport, Footpath, RouteView, Timetable, TimetableBuilder, TripInput,
};
pub use walkgraph::{Attachment, WalkGraph, WalkGraphError};

/// Seconds since midnight of the service day. GTFS allows times past 24:00:00.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Time(pub u32);

impl Time {
    /// Sentinel for "not reached" in RAPTOR's arrival labels.
    pub const UNREACHED: Self = Self(u32::MAX);

    /// Adds a duration, saturating at [`Time::UNREACHED`] instead of overflowing.
    #[must_use]
    pub const fn saturating_add(self, seconds: u32) -> Self {
        Self(self.0.saturating_add(seconds))
    }

    /// Parses a GTFS `HH:MM:SS` time, allowing hours >= 24.
    #[must_use]
    pub fn parse_gtfs(value: &str) -> Option<Self> {
        let mut parts = value.trim().split(':');
        let hours: u32 = parts.next()?.parse().ok()?;
        let minutes: u32 = parts.next()?.parse().ok()?;
        let seconds: u32 = parts.next()?.parse().ok()?;
        if parts.next().is_some() || minutes >= 60 || seconds >= 60 {
            return None;
        }
        Some(Self(hours * 3600 + minutes * 60 + seconds))
    }
}

/// Dense index of a stop in the routing timetable.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct StopIdx(pub u32);

/// Dense index of a RAPTOR route (a set of trips sharing one stop sequence).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RouteIdx(pub u32);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_gtfs_times_including_after_midnight() {
        assert_eq!(Time::parse_gtfs("08:30:00"), Some(Time(30_600)));
        assert_eq!(Time::parse_gtfs("25:00:05"), Some(Time(90_005)));
    }

    #[test]
    fn rejects_malformed_gtfs_times() {
        for bad in ["8:61:00", "08:00", "08:00:00:00", "aa:bb:cc", ""] {
            assert_eq!(Time::parse_gtfs(bad), None, "{bad}");
        }
    }

    #[test]
    fn unreached_saturates() {
        assert_eq!(Time::UNREACHED.saturating_add(60), Time::UNREACHED);
        assert!(Time(0) < Time::UNREACHED);
    }
}
