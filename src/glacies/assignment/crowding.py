"""In-vehicle time multipliers from segment loads (Phase 6 M3).

The curve (``[crowding]`` in ``assignment.toml``, UK DfT TAG M3.2 Table 3) depends on the
standee density D = standees / standing area. Seated riders weigh in-vehicle time by
``seated_base + seated_per_m2 x D`` and standing riders by ``standing_base + standing_per_m2 x
D``; a segment's multiplier is the passenger-weighted mean, so it is 1 until the seats are full.
The density is held at crush: beyond it, more people only add standing riders at the crush
weight. A vehicle with no standing area counts as at crush as soon as anyone stands.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from glacies.cities import CrowdingCurve

F64 = npt.NDArray[np.float64]


def multipliers(
    load: F64,
    seats: F64,
    standing_area_m2: F64,
    curve: CrowdingCurve,
    crush_standing_per_m2: float,
) -> F64:
    """Multiplier per segment (1 where nobody stands)."""
    standees = np.maximum(load - seats, 0.0)
    density = np.divide(
        standees,
        standing_area_m2,
        out=np.where(standees > 0, crush_standing_per_m2, 0.0),
        where=standing_area_m2 > 0,
    )
    density = np.minimum(density, crush_standing_per_m2)
    seated = curve.seated_base + curve.seated_per_m2 * density
    standing = curve.standing_base + curve.standing_per_m2 * density
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = (np.minimum(load, seats) * seated + standees * standing) / load
    return np.where(standees > 0, mean, 1.0)
