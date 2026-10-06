"""The Rust core through its Python bindings, on the hand-computed toy networks."""

import glacies_raptor as gr
import numpy as np
import numpy.typing as npt
import pytest

U32 = np.uint32


def arr(*values: int) -> npt.NDArray[np.uint32]:
    return np.array(values, dtype=U32)


def hm(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 3600 + int(minutes) * 60


A, B, C, D = 0, 1, 2, 3
NONE = arr()


def build(stop_count: int, trips: list[tuple[int, list[tuple[int, str]]]]) -> gr.Timetable:
    """Trips as (trip_id, [(stop, HH:MM), ...]) without dwell time."""
    starts, stops, times = [0], [], []
    for _, calls in trips:
        stops += [s for s, _ in calls]
        times += [hm(t) for _, t in calls]
        starts.append(len(stops))
    t = arr(*times)
    return gr.Timetable.build(
        stop_count, arr(*(i for i, _ in trips)), arr(*starts), arr(*stops), t, t, NONE, NONE, NONE
    )


def plan(tt: gr.Timetable, origin: int, at: str, destination: int) -> list[gr.Journey]:
    return tt.plan(arr(origin), arr(0), hm(at), arr(destination), arr(0), 4, 60)


def test_toy1_direct() -> None:
    tt = build(3, [(1, [(A, "08:00"), (B, "08:10"), (C, "08:20")])])

    (journey,) = plan(tt, A, "08:00", C)

    assert (journey.arrival, journey.travel_time, journey.transfers) == (hm("08:20"), 1200, 0)
    (leg,) = journey.legs
    assert (leg.kind, leg.trip_id, leg.from_stop, leg.to_stop) == ("ride", 1, A, C)


def test_toy2_one_transfer() -> None:
    tt = build(3, [(1, [(A, "08:00"), (B, "08:10")]), (2, [(B, "08:15"), (C, "08:25")])])

    (journey,) = plan(tt, A, "08:00", C)

    assert (journey.arrival, journey.transfers, journey.waiting_time) == (hm("08:25"), 1, 300)
    assert [leg.trip_id for leg in journey.legs] == [1, 2]


def test_toy3_diamond() -> None:
    tt = build(
        4,
        [
            (1, [(A, "08:00"), (B, "08:05"), (D, "08:15")]),
            (2, [(A, "08:00"), (C, "08:10"), (D, "08:30")]),
        ],
    )

    (journey,) = plan(tt, A, "08:00", D)

    assert journey.arrival == hm("08:15")
    assert [leg.trip_id for leg in journey.legs] == [1]


def test_arrival_arrays() -> None:
    tt = build(3, [(1, [(A, "08:00"), (B, "08:10")]), (2, [(B, "08:15"), (C, "08:25")])])
    departures = arr(hm("07:55"), hm("08:00"), hm("08:05"))

    single = tt.earliest_arrivals(arr(A), arr(0), hm("08:00"), 4, 60)
    window = tt.range_arrivals(arr(A), arr(0), departures, 4, 60)
    many = tt.range_arrivals_many([(arr(A), arr(0)), (arr(B), arr(0))], departures, 4, 60)

    assert single.tolist() == [hm("08:00"), hm("08:10"), hm("08:25")]
    assert window.shape == (3, 3)
    assert window[:, C].tolist() == [hm("08:25"), hm("08:25"), gr.UNREACHED]
    assert np.array_equal(many[0], window)
    assert many[1][:, C].tolist() == [hm("08:25")] * 3  # from B, T2 at 08:15 for all three


def test_footpaths_and_overtaking_are_visible() -> None:
    t1, t2 = arr(hm("08:00"), hm("09:00")), arr(hm("08:10"), hm("08:30"))
    times = np.concatenate([t1, t2])
    tt = gr.Timetable.build(
        2, arr(1, 2), arr(0, 2, 4), arr(A, B, A, B), times, times, arr(A), arr(B), arr(600)
    )

    assert (tt.route_count, tt.overtaking_splits, tt.trip_count) == (2, 1, 2)


def test_build_errors_become_value_errors() -> None:
    with pytest.raises(ValueError, match="time goes backwards"):
        gr.Timetable.build(
            2, arr(7), arr(0, 2), arr(A, B), arr(100, 50), arr(100, 50), NONE, NONE, NONE
        )
    with pytest.raises(ValueError, match="trip_starts"):
        gr.Timetable.build(2, arr(7), arr(0), arr(A, B), arr(1, 2), arr(1, 2), NONE, NONE, NONE)


def test_walk_graph_through_python() -> None:
    graph = gr.WalkGraph(3, arr(0, 1), arr(1, 2), np.array([100.0, 100.0]))
    graph.attach_stops(arr(10, 11), arr(0, 1), np.array([0.5, 1.0]), np.array([5.0, 0.0]))

    stops, metres = graph.stops_within(0, 0.0, 0.0, 1000.0)
    a, b, d = graph.stop_to_stop(1000.0)

    assert stops.tolist() == [10, 11]
    assert metres.tolist() == pytest.approx([55.0, 200.0])
    assert list(zip(a.tolist(), b.tolist(), strict=True)) == [(10, 11), (11, 10)]
    assert d.tolist() == pytest.approx([155.0, 155.0])
    assert (graph.node_count, graph.edge_count) == (3, 2)
