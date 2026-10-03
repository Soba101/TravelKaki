"""Tests for the web API. RUN_BOT=false so no Telegram connection is made."""

from fastapi.testclient import TestClient

from travelkaki.config import get_settings
from travelkaki.main import app


def test_health_ok_without_bot(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake-token")
    monkeypatch.setenv("RUN_BOT", "false")
    get_settings.cache_clear()  # settings are cached; reload with the env vars above

    # Using TestClient in a `with` block runs the app's startup + shutdown (lifespan).
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    get_settings.cache_clear()
