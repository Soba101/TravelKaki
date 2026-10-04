"""Spot the same place posted twice (issue #13).

Same name (ignoring case, punctuation and extra spaces) = same place, unless both
have map pins more than 100 m apart (e.g. two branches of a chain).
If either has no pin (geocoder miss, or "Wrong place" was tapped), the name decides.
"""

import re

from travelkaki.db.models import Place
from travelkaki.geo.distance import distance_m

SAME_PLACE_M = 100


def normalise_name(name: str) -> str:
    """'Ichiran, Shibuya!' -> 'ichiran shibuya'. Letters of any language are kept."""
    return re.sub(r"[\W_]+", " ", name.casefold()).strip()


def find_duplicate(
    name: str, lat: float | None, lng: float | None, places: list[Place]
) -> Place | None:
    """The saved place that is the same as this one, or None."""
    key = normalise_name(name)
    for place in places:
        if normalise_name(place.name) != key:
            continue
        both_pinned = None not in (lat, lng, place.lat, place.lng)
        if not both_pinned or distance_m((lat, lng), (place.lat, place.lng)) <= SAME_PLACE_M:
            return place
    return None
