"""Distance maths for map pins (used by geocoding and dedupe)."""

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000
KM_PER_DEGREE_LAT = 111  # one degree of latitude is ~111 km everywhere


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line distance in metres between two (lat, lng) points (haversine)."""
    lat1, lng1, lat2, lng2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(h))


def viewbox(center: tuple[float, float], km: float = 50) -> tuple[float, float, float, float]:
    """A square ~`km` around `center`, as (left_lng, top_lat, right_lng, bottom_lat).

    That's the order OpenStreetMap Nominatim wants for its `viewbox` parameter.
    """
    lat, lng = center
    d_lat = km / KM_PER_DEGREE_LAT
    d_lng = km / (KM_PER_DEGREE_LAT * max(cos(radians(lat)), 0.01))  # degrees shrink near poles
    return (lng - d_lng, lat + d_lat, lng + d_lng, lat - d_lat)
