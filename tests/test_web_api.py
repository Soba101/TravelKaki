"""Tests for the mini app routes (M3, #23 + #24). RUN_BOT=false, in-memory DB."""

import pytest
from fastapi.testclient import TestClient

from tests.test_web_auth import NOW, TOKEN, good_fields, sign
from travelkaki.config import get_settings
from travelkaki.db.place_queries import add_place, vote
from travelkaki.db.queries import upsert_trip
from travelkaki.main import app

CHAT = -100


class FakeMembers:
    """Only user 42 is in the group."""

    async def ok(self, chat_id, user_id):
        return chat_id == CHAT and user_id == 42


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("RUN_BOT", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    # Pretend "now" is the time the test data was signed, so it isn't "too old".
    monkeypatch.setattr("travelkaki.web.auth.time.time", lambda: NOW)
    get_settings.cache_clear()
    with TestClient(app) as c:
        app.state.members = FakeMembers()
        with app.state.deps.sessions() as s:
            trip = upsert_trip(s, CHAT, "Tokyo", None, None, "Hotel X")
            trip.hotel_lat, trip.hotel_lng = 35.6, 139.7
            p = add_place(
                s, trip.id, name="Ichiran", category="ramen", video_note="", lat=35.7, lng=139.8
            )
            add_place(s, trip.id, name="Secret bar", category="bar", video_note="")  # no pin
            vote(s, p.id, 42, "must")
            c.trip_id = trip.id
        yield c
    get_settings.cache_clear()


def auth(fields=None):
    return {"Authorization": "tma " + sign(fields or good_fields())}


def test_trip_json_for_a_member(client):
    r = client.get(f"/api/trip/{client.trip_id}", headers=auth())
    assert r.status_code == 200
    body = r.json()
    assert body["city"] == "Tokyo"
    assert body["center"] is None  # this test trip has no city centre
    assert body["hotel"] == {"name": "Hotel X", "lat": 35.6, "lng": 139.7}
    ichiran, bar = body["places"]
    assert (ichiran["tier"], ichiran["must"], ichiran["lat"]) == ("must", 1, 35.7)
    assert ichiran["maps_url"].endswith("query=Ichiran%2C+Tokyo")
    assert (bar["tier"], bar["lat"]) == ("maybe", None)  # no votes = maybe, no pin


def test_no_or_bad_init_data_is_401(client):
    url = f"/api/trip/{client.trip_id}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "tma user=x&hash=y"}).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer abc"}).status_code == 401


def test_non_member_is_403(client):
    import json

    stranger = good_fields(user=json.dumps({"id": 7}))
    assert client.get(f"/api/trip/{client.trip_id}", headers=auth(stranger)).status_code == 403


def test_unknown_trip_is_404(client):
    assert client.get("/api/trip/999", headers=auth()).status_code == 404


def test_map_page_is_served(client):
    r = client.get("/app")
    assert r.status_code == 200
    assert "TravelKaki" in r.text


def test_map_script_is_served(client):
    r = client.get("/static/map.js")
    assert r.status_code == 200
    assert "/api/trip/" in r.text
