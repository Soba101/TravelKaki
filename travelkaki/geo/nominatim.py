"""Geocoding with OpenStreetMap Nominatim (issue #12). Free, no key.

Their usage policy: at most 1 request per second, and a real User-Agent.
We keep both with one shared lock + a short sleep, and cache answers in memory.

Confidence rule (spec):
- found inside a ~50 km box around the trip city      -> "high"
- else found by a wider search, <= 50 km from the city -> "low"  (card asks "Is this right?")
- else found, but > 50 km away                         -> "far"  (card warns)
- not found                                            -> "none" (no pin)
"""

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from travelkaki.db.models import Confidence
from travelkaki.geo.distance import distance_m, viewbox

log = logging.getLogger(__name__)

URL = "https://nominatim.openstreetmap.org/search"
NEAR_M = 50_000  # 50 km


@dataclass
class GeoResult:
    lat: float
    lng: float
    address: str
    # M2: raw OSM opening hours ("Mo-Fr 10:00-22:00"), when OSM has them.
    opening_hours: str | None = None


class Nominatim:
    def __init__(
        self, client, email=None, min_interval=1.0, clock=time.monotonic, sleep=asyncio.sleep
    ):
        # `clock` and `sleep` can be faked in tests.
        self._client, self._min_interval = client, min_interval
        self._clock, self._sleep = clock, sleep
        self._lock = asyncio.Lock()  # one request at a time, for every trip
        self._last = None  # when the last request was sent
        self._cache: dict = {}
        contact = f"; {email}" if email else ""
        self._headers = {
            "User-Agent": f"TravelKaki/0.1 (+https://github.com/Soba101/TravelKaki{contact})",
            "Accept-Language": "en",  # English addresses on the cards
        }

    async def search(self, query: str, box: tuple | None = None) -> GeoResult | None:
        """First match for `query` (inside `box` when given), or None."""
        key = (query, box)
        if key in self._cache:
            return self._cache[key]
        # extratags=1 also returns OSM tags like opening_hours (M2 planner).
        params = {"q": query, "format": "jsonv2", "limit": 1, "extratags": 1}
        if box:
            params |= {"viewbox": ",".join(str(x) for x in box), "bounded": 1}
        async with self._lock:
            if self._last is not None:
                wait = self._min_interval - (self._clock() - self._last)
                if wait > 0:
                    await self._sleep(wait)
            try:
                response = await self._client.get(
                    URL, params=params, headers=self._headers, timeout=10
                )
                response.raise_for_status()
                hits = response.json()
            except (httpx.HTTPError, ValueError) as e:
                log.warning("nominatim failed: %s", type(e).__name__)
                return None  # not cached: a later try may work
            finally:
                self._last = self._clock()
        result = None
        if hits:
            top = hits[0]
            tags = top.get("extratags") or {}  # can be null in Nominatim's answer
            result = GeoResult(
                float(top["lat"]), float(top["lon"]), top["display_name"], tags.get("opening_hours")
            )
        self._cache[key] = result
        return result

    async def locate(self, name: str, city: str, center: tuple | None):
        """Find a place in the trip city. Returns (GeoResult or None, Confidence)."""
        query = f"{name}, {city}"
        if center is not None:
            hit = await self.search(query, viewbox(center, NEAR_M / 1000))
            if hit:
                return hit, Confidence.high
        hit = await self.search(query)
        if hit is None:
            return None, Confidence.none
        if center is None or distance_m(center, (hit.lat, hit.lng)) <= NEAR_M:
            return hit, Confidence.low
        return hit, Confidence.far
