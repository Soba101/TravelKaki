"""Tests for distance maths and Nominatim geocoding (issue #12). No real network."""

import httpx
import pytest

from travelkaki.geo.distance import distance_m, viewbox
from travelkaki.geo.nominatim import GeoResult, Nominatim, clean_name

SHIBUYA = (35.6595, 139.7005)
SHINJUKU = (35.6896, 139.7006)
TOKYO = (35.6812, 139.7671)


def test_distance_shibuya_to_shinjuku():
    assert distance_m(SHIBUYA, SHINJUKU) == pytest.approx(3350, abs=50)


def test_viewbox_is_left_top_right_bottom():
    left, top, right, bottom = viewbox(TOKYO, km=50)
    assert left < TOKYO[1] < right and bottom < TOKYO[0] < top
    assert top - TOKYO[0] == pytest.approx(50 / 111, rel=0.01)


class FakeClock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.sleeps.append(seconds)


def _geo(handler, clock=None):
    clock = clock or FakeClock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Nominatim(client, email="me@x.com", clock=clock, sleep=clock.sleep), clock


def _hit(lat, lng, name="Somewhere"):
    return httpx.Response(200, json=[{"lat": str(lat), "lon": str(lng), "display_name": name}])


async def test_search_params_user_agent_and_cache():
    requests = []

    def handler(request):
        requests.append(request)
        return _hit(35.66, 139.70, "Ichiran, Shibuya")

    geo, _ = _geo(handler)
    box = viewbox(TOKYO)
    assert await geo.search("Ichiran, Tokyo", box) == GeoResult(35.66, 139.70, "Ichiran, Shibuya")
    assert await geo.search("Ichiran, Tokyo", box) is not None  # cached
    assert len(requests) == 1
    params = requests[0].url.params
    assert params["bounded"] == "1" and params["format"] == "jsonv2" and params["limit"] == "1"
    assert "TravelKaki" in requests[0].headers["user-agent"]
    assert "me@x.com" in requests[0].headers["user-agent"]
    assert requests[0].headers["accept-language"] == "en"  # English addresses on cards


async def test_search_waits_one_second_between_requests():
    geo, clock = _geo(lambda r: _hit(1, 2))
    await geo.search("A")
    await geo.search("B")  # clock didn't move: must wait ~1 s
    assert clock.sleeps == [pytest.approx(1.0)]


async def test_search_errors_and_empty_give_none():
    geo, _ = _geo(lambda r: httpx.Response(500))
    assert await geo.search("A") is None
    geo, _ = _geo(lambda r: httpx.Response(200, json=[]))
    assert await geo.search("A") is None


def _router(bounded, unbounded):
    def handler(request):
        is_bounded = request.url.params.get("bounded") == "1"
        point = bounded if is_bounded else unbounded
        return _hit(*point) if point else httpx.Response(200, json=[])

    return handler


@pytest.mark.parametrize(
    ("bounded", "unbounded", "confidence"),
    [
        ((35.66, 139.70), None, "high"),  # found inside the city box
        (None, (35.75, 139.70), "low"),  # only found by the wide search, ~10 km away
        (None, (34.69, 135.50), "far"),  # wide search found it in Osaka (~400 km)
        (None, None, "none"),  # nowhere
    ],
)
async def test_locate_confidence(bounded, unbounded, confidence):
    geo, _ = _geo(_router(bounded, unbounded))
    result, conf = await geo.locate("Ichiran", "Tokyo", TOKYO)
    assert conf == confidence
    assert (result is None) == (confidence == "none")


async def test_locate_without_city_center_is_low():
    geo, _ = _geo(_router(None, (35.66, 139.70)))
    _, conf = await geo.locate("Ichiran", "Tokyo", None)
    assert conf == "low"


async def test_search_reads_opening_hours():
    """M2: we ask Nominatim for extra tags and keep the OSM opening hours."""
    requests = []

    def handler(request):
        requests.append(request)
        hit = {"lat": "35.6", "lon": "139.7", "display_name": "X"}
        hit["extratags"] = {"opening_hours": "Mo-Su 10:00-20:00"}
        return httpx.Response(200, json=[hit])

    geo, _ = _geo(handler)
    result = await geo.search("teamLab, Tokyo")
    assert result.opening_hours == "Mo-Su 10:00-20:00"
    assert requests[0].url.params["extratags"] == "1"


async def test_missing_extratags_is_none():
    geo, _ = _geo(lambda request: _hit(35.6, 139.7))
    assert (await geo.search("Somewhere, Tokyo")).opening_hours is None


def test_clean_name_strips_brackets():
    assert clean_name("Shibuya Morimoto (Yakitori)") == "Shibuya Morimoto"
    assert clean_name("Udatsu  Sushi [Omakase] ") == "Udatsu Sushi"
    assert clean_name("Ichiran") == "Ichiran"


async def test_locate_query_excludes_bracket_text():
    requests = []

    def handler(request):
        requests.append(request)
        return _hit(35.66, 139.70)

    geo, _ = _geo(handler)
    await geo.locate("Shibuya Morimoto (Yakitori)", "Tokyo", TOKYO)
    assert requests[0].url.params["q"] == "Shibuya Morimoto, Tokyo"
