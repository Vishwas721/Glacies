//! Route-choice bundles for crowding-aware assignment (Phase 6 M3).
//!
//! For every OD pair, up to three alternatives are routed once: the fastest journey (as in
//! all-or-nothing), the fastest journey on buses only, and the fastest with at most one
//! transfer. Each alternative is a *bundle*: over the departures of the window that it serves,
//! the share of its trips on each ride `(trip, board, alight)` and the departure-weighted mean
//! of the parts of its generalised cost that crowding does not change (walking, waiting, riding
//! to a station, transfers, fares). Alternatives that ride exactly the same vehicles are merged.
//!
//! The crowding loop then only needs arithmetic: in-vehicle time times a crowding multiplier
//! per trip segment (passed as a running sum per trip), a logit split between a pair's
//! alternatives, and the loads those shares put on each ride. Nothing is routed again.

use std::collections::BTreeMap;

use rayon::prelude::*;

use crate::assign::{DepartureProfile, JourneyTotals};
use crate::choice::{choose, Choice};
use crate::matrix::{MatrixError, ZoneEgress, NOT_REACHED};
use crate::paths::{MetroNetwork, NO_STATION};
use crate::range::range_search_each;
use crate::{Access, Journey, Leg, Params, StopIdx, Timetable};

/// Alternatives in the order they are routed (and their `kind` codes).
pub const FASTEST: u8 = 0;
pub const BUS_ONLY: u8 = 1;
pub const ONE_TRANSFER: u8 = 2;

/// Weights and money that turn a journey into generalised minutes. All Assumed.
#[derive(Debug, Clone, PartialEq)]
pub struct CostParams {
    pub walk_weight: f64,
    pub wait_weight: f64,
    /// Riding to a station (auto, two-wheeler): weight per minute.
    pub ride_weight: f64,
    pub transfer_penalty_min: f64,
    pub fares: Option<Fares>,
}

/// Fare rules, converted to minutes with the value of time.
#[derive(Debug, Clone, PartialEq)]
pub struct Fares {
    /// Minutes per unit of money: 60 / value of time per hour.
    pub minutes_per_unit: f64,
    /// Upper bound (inclusive, in station hops) and fare of each metro band.
    pub metro_band_hops: Vec<u32>,
    pub metro_band_fare: Vec<f64>,
    pub metro_above: f64,
    pub metro_discount: f64,
    pub bus_stage_km: f64,
    pub bus_fare_per_stage: f64,
    /// Share of bus riders who pay nothing (e.g. free travel schemes).
    pub bus_free_share: f64,
    pub ride_base: f64,
    pub ride_base_km: f64,
    pub ride_per_km: f64,
    /// The ride access cost model, to recover road km from ride seconds.
    pub ride_penalty_s: f64,
    pub ride_speed_kmh: f64,
}

/// Network facts the costs need beyond the timetable.
#[derive(Debug, Clone, PartialEq)]
pub struct CostNetwork {
    pub metro: MetroNetwork,
    /// By trip id: index of the trip's first stop in the stop-time arrays below.
    pub row_offset: Vec<u32>,
    /// By stop-time row: km from the trip's first stop (straight line, cumulative).
    pub row_km: Vec<f64>,
}

impl CostNetwork {
    fn row(&self, trip_id: u32, position: u32) -> usize {
        (self.row_offset[trip_id as usize] + position) as usize
    }

    fn ride_km(&self, trip_id: u32, board: u32, alight: u32) -> f64 {
        self.row_km[self.row(trip_id, alight)] - self.row_km[self.row(trip_id, board)]
    }
}

impl Fares {
    fn metro(&self, hops: u32) -> f64 {
        let fare = self
            .metro_band_hops
            .iter()
            .zip(&self.metro_band_fare)
            .find(|(&bound, _)| hops <= bound)
            .map_or(self.metro_above, |(_, &fare)| fare);
        fare * (1.0 - self.metro_discount)
    }

    /// Money for one journey: a ride to the station, metro fare per gate segment (by station
    /// hops), bus fare per ride (by 2 km stages of straight-line distance).
    fn journey(&self, journey: &Journey, rides: &[(StopIdx, u32)], net: &CostNetwork) -> f64 {
        let mut total = 0.0;
        if let Some(&Leg::Access { to, duration }) = journey.legs.first() {
            if rides.contains(&(to, duration)) {
                let road_km = (f64::from(duration) - self.ride_penalty_s).max(0.0) / 3600.0
                    * self.ride_speed_kmh;
                total += self.ride_base + self.ride_per_km * (road_km - self.ride_base_km).max(0.0);
            }
        }
        let metro = &net.metro;
        let mut open: Option<u32> = None; // station hops of the metro segment being ridden
        for leg in &journey.legs {
            match *leg {
                Leg::Ride { trip_id, board_pos, alight_pos, .. } if metro.is_metro(trip_id) => {
                    open = Some(open.unwrap_or(0) + (alight_pos - board_pos));
                }
                Leg::Ride { trip_id, board_pos, alight_pos, .. } => {
                    if let Some(hops) = open.take() {
                        total += self.metro(hops);
                    }
                    let km = net.ride_km(trip_id, board_pos, alight_pos);
                    let stages = (km / self.bus_stage_km).ceil().max(1.0);
                    total += stages * self.bus_fare_per_stage * (1.0 - self.bus_free_share);
                }
                Leg::Transfer { from, to, .. } => {
                    let station = metro.station_of(from);
                    if station == NO_STATION || station != metro.station_of(to) {
                        if let Some(hops) = open.take() {
                            total += self.metro(hops);
                        }
                    }
                }
                Leg::Access { .. } | Leg::Egress { .. } => {}
            }
        }
        if let Some(hops) = open {
            total += self.metro(hops);
        }
        total
    }
}

impl CostParams {
    /// Generalised minutes of everything but in-vehicle time (which crowding scales).
    fn fixed(&self, t: &JourneyTotals, money: f64) -> f64 {
        self.walk_weight * t.walking_s / 60.0
            + self.wait_weight * t.waiting_s / 60.0
            + self.ride_weight * t.riding_s / 60.0
            + self.transfer_penalty_min * (t.vehicles - 1.0).max(0.0)
            + self.fares.as_ref().map_or(0.0, |f| money * f.minutes_per_unit)
    }
}

/// One alternative of one pair, normalised per trip.
#[derive(Debug, Clone, PartialEq)]
pub struct Bundle {
    pub target: u32,
    pub kind: u8,
    /// Mean generalised minutes besides in-vehicle time.
    pub fixed_min: f64,
    /// Mean time components per trip (seconds; vehicles; share riding to a station).
    pub totals: JourneyTotals,
    /// `(trip_id, board_pos, alight_pos, share of the bundle's trips)`, sorted.
    pub rides: Vec<(u32, u32, u32, f64)>,
    /// `(entry station, exit station, share of the bundle's trips)`, sorted.
    pub gates: Vec<(u32, u32, f64)>,
}

/// One origin's pairs: how many trips go by transit, and their alternatives.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct OriginBundles {
    pub zones: Vec<u32>,
    pub transit: Vec<f64>,
    pub walked: Vec<f64>,
    pub unreached: Vec<f64>,
    /// Sorted by target position, then kind.
    pub bundles: Vec<Bundle>,
}

#[derive(Default)]
struct Accumulator {
    reached: f64,
    fixed: f64,
    totals: JourneyTotals,
    rides: BTreeMap<(u32, u32, u32), f64>,
    gates: BTreeMap<(u32, u32), f64>,
}

impl Accumulator {
    fn into_bundle(self, target: u32, kind: u8) -> Option<Bundle> {
        if self.reached <= 0.0 {
            return None;
        }
        let per = 1.0 / self.reached;
        let mut totals = JourneyTotals::default();
        totals.add(&self.totals, per);
        Some(Bundle {
            target,
            kind,
            fixed_min: self.fixed * per,
            totals,
            rides: self.rides.into_iter().map(|((t, b, a), w)| (t, b, a, w * per)).collect(),
            gates: self.gates.into_iter().map(|((e, x), w)| (e, x, w * per)).collect(),
        })
    }
}

/// Same vehicles in the same proportions: the logit would count one journey twice.
fn same_rides(a: &Bundle, b: &Bundle) -> bool {
    a.rides.len() == b.rides.len()
        && a.rides.iter().zip(&b.rides).all(|(x, y)| {
            (x.0, x.1, x.2) == (y.0, y.1, y.2) && (x.3 - y.3).abs() <= 1e-9 * x.3.max(y.3)
        })
}

/// The timetables and searches behind the alternatives.
#[derive(Debug, Clone, Copy)]
pub struct Alternatives<'a> {
    pub all: &'a Timetable,
    pub bus_only: &'a Timetable,
    pub params: Params,
}

/// Bundles from `origin` to each of `targets` (with `trips[k]` trips each).
///
/// `origin` is the full access (walks and board-only rides); the bus-only alternative uses
/// its walks only, since rides go to metro platforms.
///
/// # Errors
/// If a `walk_only` zone or a target is unknown, or paired arrays differ in length.
///
/// # Panics
/// If there are more than `u32::MAX` targets.
#[allow(clippy::too_many_arguments)] // the inputs of one matrix row, plus demand and costs
pub fn origin_bundles(
    alternatives: Alternatives<'_>,
    origin: &[Access],
    profile: DepartureProfile<'_>,
    egress: &ZoneEgress,
    walk_only: &[(u32, u32)],
    targets: &[u32],
    trips: &[f64],
    net: &CostNetwork,
    cost: &CostParams,
    max_travel_time: u32,
) -> Result<OriginBundles, MatrixError> {
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
    let rides: Vec<(StopIdx, u32)> =
        origin.iter().filter(|a| a.board_only).map(|a| (a.stop, a.duration)).collect();
    let walks: Vec<Access> = origin.iter().filter(|a| !a.board_only).copied().collect();
    let one_transfer =
        Params { max_rounds: alternatives.params.max_rounds.min(2), ..alternatives.params };
    let no_walk = vec![NOT_REACHED; zones];
    let mut fastest_walked = vec![0.0_f64; targets.len()];
    let mut fastest_reached = vec![0.0_f64; targets.len()];
    let mut per_kind: Vec<Vec<Accumulator>> = Vec::with_capacity(3);
    let searches: [(u8, &Timetable, Params, &[Access]); 3] = [
        (FASTEST, alternatives.all, alternatives.params, origin),
        (BUS_ONLY, alternatives.bus_only, alternatives.params, &walks),
        (ONE_TRANSFER, alternatives.all, one_transfer, origin),
    ];
    for (kind, tt, params, access) in searches {
        let mut acc: Vec<Accumulator> =
            (0..targets.len()).map(|_| Accumulator::default()).collect();
        // Walking all the way is judged once, on the fastest search; the other alternatives
        // describe only how the transit trips could travel.
        let on_foot = if kind == FASTEST { &walk } else { &no_walk };
        range_search_each(tt, &params, access, profile.times, |i, rounds, best| {
            let (departure, weight) = (profile.times[i], profile.weights[i]);
            for (pos, &zone) in targets.iter().enumerate() {
                let journey = match choose(
                    tt,
                    departure,
                    rounds,
                    best,
                    egress.of(zone as usize),
                    on_foot[zone as usize],
                    max_travel_time,
                ) {
                    Choice::NotReached => continue,
                    Choice::Walked => {
                        fastest_reached[pos] += weight;
                        fastest_walked[pos] += weight;
                        continue;
                    }
                    Choice::Transit(journey) => journey,
                };
                if kind == FASTEST {
                    fastest_reached[pos] += weight;
                }
                let totals = JourneyTotals::of(&journey, &rides);
                let money = cost.fares.as_ref().map_or(0.0, |f| f.journey(&journey, &rides, net));
                let a = &mut acc[pos];
                a.reached += weight;
                a.fixed += weight * cost.fixed(&totals, money);
                a.totals.add(&totals, weight);
                for leg in &journey.legs {
                    if let Leg::Ride { trip_id, board_pos, alight_pos, .. } = *leg {
                        *a.rides.entry((trip_id, board_pos, alight_pos)).or_insert(0.0) += weight;
                    }
                }
                for gate in net.metro.segments(&journey.legs) {
                    *a.gates.entry(gate).or_insert(0.0) += weight;
                }
            }
        });
        per_kind.push(acc);
    }
    let mut result = OriginBundles { zones: targets.to_vec(), ..OriginBundles::default() };
    let mut kinds: Vec<std::vec::IntoIter<Accumulator>> =
        per_kind.into_iter().map(Vec::into_iter).collect();
    for (pos, &n) in trips.iter().enumerate() {
        let reached = fastest_reached[pos];
        let transit_share =
            if reached > 0.0 { (reached - fastest_walked[pos]) / reached } else { 0.0 };
        result.transit.push(n * transit_share);
        result.walked.push(if reached > 0.0 { n - n * transit_share } else { 0.0 });
        result.unreached.push(if reached > 0.0 { 0.0 } else { n });
        let target = u32::try_from(pos).expect("fits u32");
        let mut kept: Vec<Bundle> = Vec::new();
        for (kind, accumulators) in (0_u8..).zip(kinds.iter_mut()) {
            let acc = accumulators.next().expect("one accumulator per target");
            if transit_share <= 0.0 {
                continue;
            }
            if let Some(bundle) = acc.into_bundle(target, kind) {
                if !kept.iter().any(|k| same_rides(k, &bundle)) {
                    kept.push(bundle);
                }
            }
        }
        result.bundles.extend(kept);
    }
    Ok(result)
}

/// Every pair's alternatives in flat arrays, ready for the crowding loop.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ChoiceSet {
    pub pair_origin: Vec<u32>,
    pub pair_dest: Vec<u32>,
    pub pair_transit: Vec<f64>,
    pub pair_walked: Vec<f64>,
    pub pair_unreached: Vec<f64>,
    /// CSR: alternatives of pair `p` are `alt_start[p]..alt_start[p + 1]`.
    pub alt_start: Vec<u32>,
    pub alt_kind: Vec<u8>,
    pub alt_fixed_min: Vec<f64>,
    pub alt_totals: Vec<JourneyTotals>,
    /// CSR into the ride and gate arrays.
    pub alt_ride_start: Vec<u32>,
    pub alt_gate_start: Vec<u32>,
    pub ride_trip: Vec<u32>,
    pub ride_board: Vec<u16>,
    pub ride_alight: Vec<u16>,
    pub ride_share: Vec<f32>,
    pub gate_entry: Vec<u32>,
    pub gate_exit: Vec<u32>,
    pub gate_share: Vec<f32>,
}

fn index(n: usize) -> u32 {
    u32::try_from(n).expect("choice set exceeds u32 indices")
}

impl ChoiceSet {
    #[must_use]
    pub fn new() -> Self {
        Self {
            alt_start: vec![0],
            alt_ride_start: vec![0],
            alt_gate_start: vec![0],
            ..Self::default()
        }
    }

    /// Append one origin's pairs (call in a fixed origin order for deterministic sums).
    ///
    /// # Panics
    /// If the arrays outgrow `u32` indices or a stop position exceeds `u16`.
    pub fn push(&mut self, origin: u32, b: OriginBundles) {
        let mut bundles = b.bundles.into_iter().peekable();
        for (pos, &zone) in b.zones.iter().enumerate() {
            self.pair_origin.push(origin);
            self.pair_dest.push(zone);
            self.pair_transit.push(b.transit[pos]);
            self.pair_walked.push(b.walked[pos]);
            self.pair_unreached.push(b.unreached[pos]);
            while let Some(bundle) = bundles.next_if(|x| x.target as usize == pos) {
                self.alt_kind.push(bundle.kind);
                self.alt_fixed_min.push(bundle.fixed_min);
                self.alt_totals.push(bundle.totals);
                for (trip, board, alight, share) in bundle.rides {
                    self.ride_trip.push(trip);
                    self.ride_board.push(u16::try_from(board).expect("position fits u16"));
                    self.ride_alight.push(u16::try_from(alight).expect("position fits u16"));
                    #[allow(clippy::cast_possible_truncation)] // a share in [0, 1]
                    self.ride_share.push(share as f32);
                }
                for (entry, exit, share) in bundle.gates {
                    self.gate_entry.push(entry);
                    self.gate_exit.push(exit);
                    #[allow(clippy::cast_possible_truncation)] // a share in [0, 1]
                    self.gate_share.push(share as f32);
                }
                self.alt_ride_start.push(index(self.ride_trip.len()));
                self.alt_gate_start.push(index(self.gate_entry.len()));
            }
            self.alt_start.push(index(self.alt_kind.len()));
        }
    }

    #[must_use]
    pub fn pair_count(&self) -> usize {
        self.pair_origin.len()
    }

    #[must_use]
    pub fn alt_count(&self) -> usize {
        self.alt_kind.len()
    }

    fn rides_of(&self, alt: usize) -> std::ops::Range<usize> {
        self.alt_ride_start[alt] as usize..self.alt_ride_start[alt + 1] as usize
    }

    /// Generalised minutes of every alternative: fixed part plus in-vehicle minutes scaled by
    /// crowding. `crowded` is, per stop-time row, the running sum within its trip of segment
    /// seconds times the crowding multiplier (0 at a trip's first stop).
    #[must_use]
    pub fn costs(&self, crowded: &[f64], row_offset: &[u32]) -> Vec<f64> {
        (0..self.alt_count())
            .into_par_iter()
            .map(|alt| {
                let in_vehicle: f64 = self
                    .rides_of(alt)
                    .map(|r| {
                        let base = row_offset[self.ride_trip[r] as usize] as usize;
                        let seconds = crowded[base + usize::from(self.ride_alight[r])]
                            - crowded[base + usize::from(self.ride_board[r])];
                        f64::from(self.ride_share[r]) * seconds
                    })
                    .sum();
                self.alt_fixed_min[alt] + in_vehicle / 60.0
            })
            .collect()
    }

    /// Logit shares of each pair's alternatives: `exp(-theta x cost)`, normalised.
    #[must_use]
    pub fn shares(&self, costs: &[f64], theta: f64) -> Vec<f64> {
        let mut shares = vec![0.0; self.alt_count()];
        for p in 0..self.pair_count() {
            let alts = self.alt_start[p] as usize..self.alt_start[p + 1] as usize;
            let least = alts.clone().map(|a| costs[a]).fold(f64::INFINITY, f64::min);
            let total: f64 = alts.clone().map(|a| (-theta * (costs[a] - least)).exp()).sum();
            for a in alts {
                shares[a] = (-theta * (costs[a] - least)).exp() / total;
            }
        }
        shares
    }

    /// Boardings and alightings per stop-time row when each pair's transit trips split by
    /// `shares` (summed sequentially, so the result is the same on every run).
    #[allow(clippy::needless_range_loop)] // CSR offsets index several parallel arrays
    #[must_use]
    pub fn loads(&self, shares: &[f64], row_offset: &[u32], rows: usize) -> (Vec<f64>, Vec<f64>) {
        let (mut boardings, mut alightings) = (vec![0.0; rows], vec![0.0; rows]);
        for p in 0..self.pair_count() {
            for alt in self.alt_start[p] as usize..self.alt_start[p + 1] as usize {
                let trips = self.pair_transit[p] * shares[alt];
                if trips <= 0.0 {
                    continue;
                }
                for r in self.rides_of(alt) {
                    let base = row_offset[self.ride_trip[r] as usize] as usize;
                    let n = trips * f64::from(self.ride_share[r]);
                    boardings[base + usize::from(self.ride_board[r])] += n;
                    alightings[base + usize::from(self.ride_alight[r])] += n;
                }
            }
        }
        (boardings, alightings)
    }

    /// Per pair, trip-weighted sums of the time components under `shares`; and metro gate
    /// passes per `(entry, exit)`.
    #[allow(clippy::needless_range_loop)] // CSR offsets index several parallel arrays
    #[must_use]
    pub fn summary(&self, shares: &[f64]) -> (Vec<JourneyTotals>, Vec<(u32, u32, f64)>) {
        let mut totals = vec![JourneyTotals::default(); self.pair_count()];
        let mut gates: BTreeMap<(u32, u32), f64> = BTreeMap::new();
        for p in 0..self.pair_count() {
            for alt in self.alt_start[p] as usize..self.alt_start[p + 1] as usize {
                let trips = self.pair_transit[p] * shares[alt];
                totals[p].add(&self.alt_totals[alt], trips);
                let range =
                    self.alt_gate_start[alt] as usize..self.alt_gate_start[alt + 1] as usize;
                for g in range {
                    *gates.entry((self.gate_entry[g], self.gate_exit[g])).or_insert(0.0) +=
                        trips * f64::from(self.gate_share[g]);
                }
            }
        }
        (totals, gates.into_iter().map(|((e, x), n)| (e, x, n)).collect())
    }
}
