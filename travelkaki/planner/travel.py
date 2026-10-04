"""Travel time between two pins (M2 spec: "distance x speed factor" in v1).

Straight-line distance x 1.3 (streets aren't straight).
Under 1.5 km we walk at 4.5 km/h. Further, we take transit:
20 km/h on average, plus 10 minutes for waiting and walking to the station.
Over 15 km it's an "express" trip: express train, express bus or taxi,
40 km/h plus 15 minutes. (Donovan: far places like Disneyland are reachable
by express bus, and people may not use public transport at all.)
"""

from math import ceil

from travelkaki.geo.distance import distance_m

DETOUR = 1.3
WALK_LIMIT_M = 1500
WALK_M_PER_MIN = 4500 / 60
TRANSIT_M_PER_MIN = 20000 / 60
TRANSIT_EXTRA_MIN = 10
EXPRESS_FROM_M = 15000
EXPRESS_M_PER_MIN = 40000 / 60
EXPRESS_EXTRA_MIN = 15


def estimate(a: tuple[float, float], b: tuple[float, float]) -> tuple[int, str]:
    """(minutes, "walk" | "transit" | "express") from a to b. Minutes are rounded up."""
    metres = distance_m(a, b) * DETOUR
    if metres < WALK_LIMIT_M:
        return ceil(metres / WALK_M_PER_MIN), "walk"
    if metres >= EXPRESS_FROM_M:
        return ceil(metres / EXPRESS_M_PER_MIN) + EXPRESS_EXTRA_MIN, "express"
    return ceil(metres / TRANSIT_M_PER_MIN) + TRANSIT_EXTRA_MIN, "transit"
