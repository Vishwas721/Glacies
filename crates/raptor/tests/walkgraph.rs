//! Bounded walking distances over a small hand-checked network.

use glacies_raptor::{Attachment, StopIdx, WalkGraph, WalkGraphError};

//   n0 --100 m-- n1 --100 m-- n2        n3 --50 m-- n4   (separate island)
//   e0           e1                     e2
fn graph() -> WalkGraph {
    let mut g = WalkGraph::new(5, &[(0, 1, 100.0), (1, 2, 100.0), (3, 4, 50.0)]).unwrap();
    g.attach_stops(&[
        (StopIdx(10), on(0, 0.5, 5.0)),  // middle of e0, 5 m off the street
        (StopIdx(11), on(1, 0.25, 0.0)), // a quarter along e1
        (StopIdx(12), on(1, 1.0, 10.0)), // at n2, 10 m off
        (StopIdx(13), on(2, 0.0, 0.0)),  // on the island
    ])
    .unwrap();
    g
}

fn on(edge: u32, fraction: f64, offset_m: f64) -> Attachment {
    Attachment { edge, fraction, offset_m }
}

/// Distance to `stop`, rounded to the millimetre (fractions are not exact in binary).
fn near(found: &[(StopIdx, f64)], stop: u32) -> Option<f64> {
    found.iter().find(|(s, _)| s.0 == stop).map(|&(_, d)| (d * 1000.0).round() / 1000.0)
}

#[test]
fn distances_include_offsets_and_positions_along_edges() {
    let g = graph();
    let found = g.stops_within(&on(0, 0.0, 0.0), 1_000.0).unwrap(); // standing on n0

    assert_eq!(near(&found, 10), Some(55.0)); // 50 along e0 + 5 off
    assert_eq!(near(&found, 11), Some(125.0)); // 100 + 25
    assert_eq!(near(&found, 12), Some(210.0)); // 200 + 10
    assert_eq!(near(&found, 13), None, "different island");
    assert_eq!(found.iter().map(|(s, _)| s.0).collect::<Vec<_>>(), [10, 11, 12]);
}

#[test]
fn the_limit_is_respected() {
    let found = graph().stops_within(&on(0, 0.0, 0.0), 125.0).unwrap();

    assert_eq!(found.iter().map(|(s, _)| s.0).collect::<Vec<_>>(), [10, 11]);
}

#[test]
fn points_on_the_same_edge_connect_directly() {
    let mut g = WalkGraph::new(2, &[(0, 1, 1_000.0)]).unwrap();
    g.attach_stops(&[(StopIdx(0), on(0, 0.40, 3.0)), (StopIdx(1), on(0, 0.45, 4.0))]).unwrap();

    let found = g.stops_within(&on(0, 0.40, 3.0), 400.0).unwrap();

    // 3 + 50 + 4 along the edge, not via the far-away end nodes.
    assert_eq!(near(&found, 1), Some(57.0));
    assert_eq!(near(&found, 0), Some(6.0)); // its own stop: off and back on
}

#[test]
fn stop_to_stop_is_symmetric_and_excludes_self_pairs() {
    let pairs = graph().stop_to_stop(1_000.0);

    for &(a, b, d) in &pairs {
        assert_ne!(a, b);
        let back = pairs.iter().find(|&&(x, y, _)| x == b && y == a).map(|&(_, _, d)| d);
        assert_eq!(back, Some(d), "{a:?} -> {b:?}");
    }
    let from_10: Vec<_> =
        pairs.iter().filter(|p| p.0 == StopIdx(10)).map(|p| (p.1 .0, p.2)).collect();
    assert_eq!(from_10, [(11, 80.0), (12, 165.0)]); // 5 + 50 + 25; 5 + 50 + 100 + 10
    assert!(pairs.windows(2).all(|w| (w[0].0, w[0].1) < (w[1].0, w[1].1)), "ordered");
}

#[test]
fn invalid_input_is_rejected() {
    assert_eq!(
        WalkGraph::new(2, &[(0, 5, 1.0)]).unwrap_err(),
        WalkGraphError::UnknownNode { edge: 0, node: 5 }
    );
    assert_eq!(
        WalkGraph::new(2, &[(0, 1, f64::NAN)]).unwrap_err(),
        WalkGraphError::BadLength { edge: 0 }
    );
    let mut g = WalkGraph::new(2, &[(0, 1, 1.0)]).unwrap();
    assert_eq!(
        g.attach_stops(&[(StopIdx(0), on(3, 0.5, 0.0))]).unwrap_err(),
        WalkGraphError::UnknownEdge { edge: 3 }
    );
    assert_eq!(
        g.stops_within(&on(0, 1.5, 0.0), 10.0).unwrap_err(),
        WalkGraphError::BadAttachment { edge: 0 }
    );
}
