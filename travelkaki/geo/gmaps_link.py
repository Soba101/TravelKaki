"""Read a lat/lng out of a Google Maps link (used by /pin).

Telegram's location search only finds places near the user, so people paste a
Google Maps link instead. Short links are expanded by following redirects first.
"""

import logging
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+")
# Priority 1: the actual place pin. Priority 2: the map viewport centre.
PLACE_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
AT_RE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
PAIR_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def _valid(lat: float, lng: float) -> tuple[float, float] | None:
    """The pair if it is a real coordinate, else None."""
    return (lat, lng) if -90 <= lat <= 90 and -180 <= lng <= 180 else None


def parse_coords(url: str) -> tuple[float, float] | None:
    """(lat, lng) from an expanded Google Maps URL, or None."""
    for regex in (PLACE_RE, AT_RE):  # in priority order
        m = regex.search(url)
        if m:
            return _valid(float(m.group(1)), float(m.group(2)))
    params = parse_qs(urlparse(url).query)
    for key in ("q", "query", "ll"):
        for value in params.get(key, []):  # parse_qs already decodes %2C
            m = PAIR_RE.match(unquote(value))
            if m:
                return _valid(float(m.group(1)), float(m.group(2)))
    return None


def is_short(url: str) -> bool:
    """True for maps.app.goo.gl/... and goo.gl/maps/... links."""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    return host == "maps.app.goo.gl" or (host == "goo.gl" and p.path.startswith("/maps"))


def _is_maps(url: str) -> bool:
    """Is this a Google Maps link (short or full)?"""
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if is_short(url):
        return True
    is_google = host == "maps.google.com" or host.endswith(("google.com", "google.co.jp"))
    return is_google and (host.startswith("maps.") or p.path.startswith("/maps"))


def find_url(text: str) -> str | None:
    """The first Google Maps link in a message, or None."""
    for raw in URL_RE.findall(text or ""):
        url = raw.rstrip(".,)>]")  # trailing punctuation isn't part of the link
        if _is_maps(url):
            return url
    return None


async def resolve(url: str, client: httpx.AsyncClient | None = None) -> str:
    """Follow redirects and return the final URL (the input if the request fails)."""
    own = client is None
    # No shared client by default: a fresh one has no cookies.
    client = client or httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 (TravelKaki bot)"})
    try:
        response = await client.get(url, follow_redirects=True, timeout=10)
        return str(response.url)
    except (httpx.HTTPError, httpx.InvalidURL) as e:
        log.warning("gmaps resolve failed: %s", e)
        return url
    finally:
        if own:
            await client.aclose()
