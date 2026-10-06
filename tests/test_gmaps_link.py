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


# A real app share link, after redirects: no coordinates, only the place text.
RAMEN = (
    "https://www.google.com/maps?q=Ramen+Afro+Beats+Shinjuku,+103+1+Chome-16-10+Shinjuku,"
    "+Shinjuku+City,+Tokyo+160-0022,+Japan&ftid=0x60188dac4c941cd3:0x37e3afb8ba57e79e"
    "&entry=gps&g_ep=abc&shh=1"
)


def test_text_query_has_no_coords():
    assert g.parse_coords(RAMEN) is None
    assert g.query_text(RAMEN).startswith("Ramen Afro Beats Shinjuku, 103 1 Chome-16-10")


def test_query_text_ignores_coordinates_and_missing():
    assert g.query_text("https://maps.google.com/?q=35.1,139.2") is None
    assert g.query_text(PLACE) is None


def test_postcode_and_country():
    assert g.postcode_and_country(g.query_text(RAMEN)) == ("160-0022", "Japan")
    assert g.postcode_and_country("Some Shop, Paris, France") is None


def test_parse_text_coords():
    assert g.parse_text_coords("35.6905, 139.7066") == (35.6905, 139.7066)
    assert g.parse_text_coords(" -33.86,151.21 ") == (-33.86, 151.21)
    assert g.parse_text_coords("95, 10") is None
    assert g.parse_text_coords("meet at 35.6, 139.7 ok") is None


def test_link_name():
    assert g.link_name(PLACE.replace("/Name/", "/Ramen+Afro%20Beats/")) == "Ramen Afro Beats"
    assert g.link_name(RAMEN) == "Ramen Afro Beats Shinjuku"
    assert g.link_name("https://maps.google.com/?q=35.1,139.2") is None
    assert g.link_name("https://maps.app.goo.gl/abc") is None


def test_names_match():
    ok = g.names_match
    assert not ok("Ramen Afro Beats Shinjuku", "Ramen Ushio", "Tokyo")
    assert ok("Ushio Shinjuku", "Ramen Ushio (Shinjuku)", "Tokyo")  # one shared word
    assert ok("Ramen", "Ramen Ushio", "Tokyo")  # nothing distinctive: can't judge
    assert ok("Ichiran Shibuya", "Ichiran Ramen", "Tokyo")
    assert ok("Tokyo Cafe", "Blue Bottle Coffee", "Tokyo")  # city + generic words dropped
    assert not ok("Blue Bottle", "Kiyosumi Coffee", "Tokyo")
