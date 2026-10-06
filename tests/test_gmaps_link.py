"""Tests for reading coordinates out of Google Maps links."""

import httpx
import pytest

from travelkaki.geo import gmaps_link as g

PLACE = (
    "https://www.google.com/maps/place/Name/@35.69,139.70,17z/data=!3m1!4b1!4m6!3m5"
    "!1s0x0:0x0!8m2!3d35.6938!4d139.7034"
)


def test_place_pin_beats_viewport():
    assert g.parse_coords(PLACE) == (35.6938, 139.7034)  # !3d/!4d wins over @


def test_at_viewport():
    assert g.parse_coords("https://www.google.com/maps/@-33.86,151.21,15z") == (-33.86, 151.21)


@pytest.mark.parametrize("key", ["q", "query", "ll"])
def test_query_params(key):
    url = f"https://maps.google.com/?{key}=35.1,139.2"
    assert g.parse_coords(url) == (35.1, 139.2)


def test_query_with_encoded_comma():
    assert g.parse_coords("https://www.google.com/maps?q=35.1%2C-139.2") == (35.1, -139.2)


def test_out_of_range_is_rejected():
    assert g.parse_coords("https://www.google.com/maps/@95.0,10.0,15z") is None
    assert g.parse_coords("https://www.google.com/maps/@10.0,190.0,15z") is None


def test_no_coords():
    assert g.parse_coords("https://www.google.com/maps/place/Some+Shop") is None
    assert g.parse_coords("https://example.com/?q=hello") is None
    assert g.parse_coords("not a url") is None


def test_is_maps_url():
    assert g.find_url("see https://maps.app.goo.gl/abc123 ok") == "https://maps.app.goo.gl/abc123"
    assert g.find_url("https://goo.gl/maps/xyz") == "https://goo.gl/maps/xyz"
    assert g.find_url(f"x {PLACE}") == PLACE
    assert g.find_url("https://www.google.com/search?q=maps") is None
    assert g.find_url("https://tiktok.com/@a/video/1") is None
    assert g.find_url("no link") is None


def test_is_short():
    assert g.is_short("https://maps.app.goo.gl/abc")
    assert g.is_short("https://goo.gl/maps/abc")
    assert not g.is_short(PLACE)


async def test_resolve_follows_redirects():
    def handler(request):
        if request.url.host == "maps.app.goo.gl":
            return httpx.Response(302, headers={"location": PLACE})
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await g.resolve("https://maps.app.goo.gl/abc", client) == PLACE


async def test_resolve_failure_returns_input():
    def handler(request):
        raise httpx.ConnectError("down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await g.resolve("https://maps.app.goo.gl/abc", client) == "https://maps.app.goo.gl/abc"
