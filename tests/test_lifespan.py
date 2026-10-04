"""The bot must still boot if setting the command menu fails (PR1 review).

We swap in a fake bot app, so no Telegram connection is made.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from telegram.error import NetworkError

import travelkaki.web.app as web
from travelkaki.config import get_settings


def test_startup_survives_command_menu_error(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake-token")
    monkeypatch.setenv("RUN_BOT", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    get_settings.cache_clear()
    fake_bot = SimpleNamespace(
        initialize=AsyncMock(),
        start=AsyncMock(),
        stop=AsyncMock(),
        shutdown=AsyncMock(),
        updater=SimpleNamespace(start_polling=AsyncMock(), stop=AsyncMock()),
        bot=SimpleNamespace(username="travelkakiibot", send_message=AsyncMock()),
    )
    monkeypatch.setattr(web, "build_application", lambda token, deps: fake_bot)
    monkeypatch.setattr(web, "register_commands", AsyncMock(side_effect=NetworkError("down")))

    with TestClient(web.app) as client:
        assert client.get("/health").status_code == 200

    fake_bot.shutdown.assert_awaited_once()  # clean shutdown still happened
    get_settings.cache_clear()
