//! Bounded shortest walks over the pedestrian network (built in Phase 1 M4).
//!
//! Stops and arbitrary points sit *on* an edge: at `fraction` of the way from the edge's
//! `from` node, `offset_m` metres away from it (the snap distance). Distances are measured
//! along the network between those points, including both offsets.

use std::cmp::Ordering;
use std::collections::BinaryHeap;
use std::fmt;

use rayon::prelude::*;

use crate::StopIdx;

/// Where a stop or point joins the walk network.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Attachment {
    pub edge: u32,
    /// Position along the edge, 0 at its `from` node, 1 at its `to` node.
    pub fraction: f64,
    /// Straight-line metres from the stop or point to the edge.
    pub offset_m: f64,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum WalkGraphError {
    UnknownNode { edge: u32, node: u32 },
    BadLength { edge: u32 },
    UnknownEdge { edge: u32 },
    BadAttachment { edge: u32 },
}

impl fmt::Display for WalkGraphError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownNode { edge, node } => write!(f, "edge {edge} uses unknown node {node}"),
            Self::BadLength { edge } => {
                write!(f, "edge {edge} has a negative or non-finite length")
            }
            Self::UnknownEdge { edge } => write!(f, "attachment to unknown edge {edge}"),
            Self::BadAttachment { edge } => {
                write!(f, "attachment to edge {edge} has fraction outside 0..1 or a bad offset")
            }
        }
    }
}

impl std::error::Error for WalkGraphError {}

/// Undirected walk network with stops attached to its edges.
#[derive(Debug, Clone)]
pub struct WalkGraph {
    edge_from: Vec<u32>,
    edge_to: Vec<u32>,
    edge_len: Vec<f64>,
    /// CSR adjacency: `(neighbour, edge)` per node.
    adj_start: Vec<u32>,
    adj: Vec<(u32, u32)>,
    /// CSR: stops attached to each edge.
    edge_stops_start: Vec<u32>,
    edge_stops: Vec<(StopIdx, Attachment)>,
    stops: Vec<(StopIdx, Attachment)>,
}

/// Heap entry ordered by distance (smallest first), then node, for deterministic ties.
#[derive(Debug, Clone, Copy, PartialEq)]
struct Entry(f64, u32);

impl Eq for Entry {}

impl Ord for Entry {
    fn cmp(&self, other: &Self) -> Ordering {
        other.0.total_cmp(&self.0).then_with(|| other.1.cmp(&self.1))
    }
}

impl PartialOrd for Entry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

/// Reusable per-search buffers (reset via the touched lists, not reallocated).
struct Scratch {
    node_dist: Vec<f64>,
    touched_nodes: Vec<u32>,
    stop_dist: Vec<f64>,
    touched_stops: Vec<usize>,
    heap: BinaryHeap<Entry>,
}

impl WalkGraph {
    /// # Errors
    /// If an edge references a node `>= node_count` or has a negative or non-finite length.
    ///
    /// # Panics
    /// If there are more than `u32::MAX` edges.
    pub fn new(node_count: u32, edges: &[(u32, u32, f64)]) -> Result<Self, WalkGraphError> {
        let mut degree = vec![0u32; node_count as usize + 1];
        for (e, &(a, b, len)) in edges.iter().enumerate() {
            let edge = to_u32(e);
            for node in [a, b] {
                if node >= node_count {
                    return Err(WalkGraphError::UnknownNode { edge, node });
                }
            }
            if !(len.is_finite() && len >= 0.0) {
                return Err(WalkGraphError::BadLength { edge });
            }
            degree[a as usize + 1] += 1;
            degree[b as usize + 1] += 1;
        }
        let mut adj_start = degree;
        for i in 1..adj_start.len() {
            adj_start[i] += adj_start[i - 1];
        }
        let mut fill = adj_start.clone();
        let mut adj = vec![(0, 0); adj_start[node_count as usize] as usize];
        for (e, &(a, b, _)) in edges.iter().enumerate() {
            for (from, to) in [(a, b), (b, a)] {
                adj[fill[from as usize] as usize] = (to, to_u32(e));
                fill[from as usize] += 1;
            }
        }
        Ok(Self {
            edge_from: edges.iter().map(|e| e.0).collect(),
            edge_to: edges.iter().map(|e| e.1).collect(),
            edge_len: edges.iter().map(|e| e.2).collect(),
            adj_start,
            adj,
            edge_stops_start: vec![0; edges.len() + 1],
            edge_stops: Vec::new(),
            stops: Vec::new(),
        })
    }

    /// Attach stops to edges (replacing any attached before).
    ///
    /// # Errors
    /// If an attachment references an unknown edge or has a fraction outside `0..=1` or a
    /// negative or non-finite offset.
    pub fn attach_stops(&mut self, stops: &[(StopIdx, Attachment)]) -> Result<(), WalkGraphError> {
        let edge_count = self.edge_len.len();
        let mut per_edge: Vec<Vec<(StopIdx, Attachment)>> = vec![Vec::new(); edge_count];
        for &(stop, at) in stops {
            self.check(&at)?;
            per_edge[at.edge as usize].push((stop, at));
        }
        self.edge_stops_start.clear();
        self.edge_stops.clear();
        self.edge_stops_start.push(0);
        for list in per_edge {
            self.edge_stops.extend(list);
            self.edge_stops_start.push(to_u32(self.edge_stops.len()));
        }
        self.stops = stops.to_vec();
        self.stops.sort_by_key(|(stop, _)| *stop);
        Ok(())
    }

    fn check(&self, at: &Attachment) -> Result<(), WalkGraphError> {
        let edge = at.edge;
        if edge as usize >= self.edge_len.len() {
            return Err(WalkGraphError::UnknownEdge { edge });
        }
        let fraction_ok = (0.0..=1.0).contains(&at.fraction);
        let offset_ok = at.offset_m.is_finite() && at.offset_m >= 0.0;
        if !(fraction_ok && offset_ok) {
            return Err(WalkGraphError::BadAttachment { edge });
        }
        Ok(())
    }

    #[must_use]
    pub fn node_count(&self) -> usize {
        self.adj_start.len() - 1
    }

    #[must_use]
    pub fn edge_count(&self) -> usize {
        self.edge_len.len()
    }

    fn scratch(&self) -> Scratch {
        let max_stop = self.stops.iter().map(|(s, _)| s.0 as usize + 1).max().unwrap_or(0);
        Scratch {
            node_dist: vec![f64::INFINITY; self.node_count()],
            touched_nodes: Vec::new(),
            stop_dist: vec![f64::INFINITY; max_stop],
            touched_stops: Vec::new(),
            heap: BinaryHeap::new(),
        }
    }

    /// Attached stops within `max_m` walking metres of `from`, ordered by stop.
    ///
    /// # Errors
    /// If `from` is not a valid attachment.
    pub fn stops_within(
        &self,
        from: &Attachment,
        max_m: f64,
    ) -> Result<Vec<(StopIdx, f64)>, WalkGraphError> {
        self.check(from)?;
        Ok(self.search(&mut self.scratch(), from, max_m))
    }

    /// Every pair of attached stops within `max_m` walking metres of each other (both
    /// directions, no self pairs), ordered by `(from, to)`. Sources run in parallel.
    #[must_use]
    pub fn stop_to_stop(&self, max_m: f64) -> Vec<(StopIdx, StopIdx, f64)> {
        let per_source: Vec<Vec<(StopIdx, StopIdx, f64)>> = self
            .stops
            .par_iter()
            .map_init(
                || self.scratch(),
                |scratch, &(from, at)| {
                    self.search(scratch, &at, max_m)
                        .into_iter()
                        .filter(|&(to, _)| to != from)
                        .map(|(to, metres)| (from, to, metres))
                        .collect()
                },
            )
            .collect();
        per_source.into_iter().flatten().collect()
    }

    fn search(&self, scratch: &mut Scratch, from: &Attachment, max_m: f64) -> Vec<(StopIdx, f64)> {
        let e = from.edge as usize;
        let len = self.edge_len[e];
        let (a, b) = self.endpoints(e);
        // Points on the same edge are reachable directly along it.
        for &(stop, at) in self.stops_on(e) {
            let direct = from.offset_m + (from.fraction - at.fraction).abs() * len + at.offset_m;
            Self::offer(scratch, stop, direct, max_m);
        }
        Self::push(scratch, a, from.offset_m + from.fraction * len, max_m);
        Self::push(scratch, b, from.offset_m + (1.0 - from.fraction) * len, max_m);

        while let Some(Entry(dist, node)) = scratch.heap.pop() {
            if dist > scratch.node_dist[node as usize] {
                continue; // stale entry
            }
            let range =
                self.adj_start[node as usize] as usize..self.adj_start[node as usize + 1] as usize;
            for &(next, edge) in &self.adj[range] {
                let edge = edge as usize;
                let len = self.edge_len[edge];
                for &(stop, at) in self.stops_on(edge) {
                    let along =
                        if self.edge_from[edge] == node { at.fraction } else { 1.0 - at.fraction };
                    Self::offer(scratch, stop, dist + along * len + at.offset_m, max_m);
                }
                Self::push(scratch, next, dist + len, max_m);
            }
        }

        let mut found: Vec<(StopIdx, f64)> = scratch
            .touched_stops
            .iter()
            .map(|&s| (StopIdx(to_u32(s)), scratch.stop_dist[s]))
            .collect();
        found.sort_unstable_by_key(|(stop, _)| *stop);
        for &s in &scratch.touched_stops {
            scratch.stop_dist[s] = f64::INFINITY;
        }
        scratch.touched_stops.clear();
        for &n in &scratch.touched_nodes {
            scratch.node_dist[n as usize] = f64::INFINITY;
        }
        scratch.touched_nodes.clear();
        found
    }

    fn endpoints(&self, edge: usize) -> (u32, u32) {
        (self.edge_from[edge], self.edge_to[edge])
    }

    fn stops_on(&self, edge: usize) -> &[(StopIdx, Attachment)] {
        &self.edge_stops
            [self.edge_stops_start[edge] as usize..self.edge_stops_start[edge + 1] as usize]
    }

    fn push(scratch: &mut Scratch, node: u32, dist: f64, max_m: f64) {
        let slot = &mut scratch.node_dist[node as usize];
        if dist <= max_m && dist < *slot {
            if slot.is_infinite() {
                scratch.touched_nodes.push(node);
            }
            *slot = dist;
            scratch.heap.push(Entry(dist, node));
        }
    }

    fn offer(scratch: &mut Scratch, stop: StopIdx, dist: f64, max_m: f64) {
        let s = stop.0 as usize;
        if dist <= max_m && dist < scratch.stop_dist[s] {
            if scratch.stop_dist[s].is_infinite() {
                scratch.touched_stops.push(s);
            }
            scratch.stop_dist[s] = dist;
        }
    }
}

fn to_u32(value: usize) -> u32 {
    u32::try_from(value).expect("walk graph exceeds u32 indices")
}
