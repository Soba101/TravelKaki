"""Tests for /map and the Open map button (M3, #26)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from travelkaki.bot.map import NOT_SET_UP, map_command, map_markup
from travelkaki.db import queries
from travelkaki.deps import Deps

URL = "https://t.me/TravelKakiBot/map"


def test_button_links_to_the_trip():
    button = map_markup(URL, 7).inline_keyboard[0][0]
    assert button.url == URL + "?startapp=7"


def test_no_url_no_button():
    assert map_markup(None, 7) is None


def _fake(sessions, url):
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), effective_message=message)
    context = SimpleNamespace(bot_data={"deps": Deps(sessions=sessions, mini_app_url=url)})
    return update, context, message


async def test_map_command_sends_button(sessions):
    with sessions() as s:
        trip_id = queries.upsert_trip(s, 1, "Tokyo", None, None, None).id
    update, context, message = _fake(sessions, URL)
    await map_command(update, context)
    markup = message.reply_text.await_args.kwargs["reply_markup"]
    assert markup.inline_keyboard[0][0].url.endswith(f"startapp={trip_id}")


async def test_map_command_without_trip(sessions):
    update, context, message = _fake(sessions, URL)
    await map_command(update, context)
    assert "/newtrip" in message.reply_text.await_args.args[0]


async def test_map_command_not_set_up(sessions):
    with sessions() as s:
        queries.upsert_trip(s, 1, "Tokyo", None, None, None)
    update, context, message = _fake(sessions, None)
    await map_command(update, context)
    assert message.reply_text.await_args.args[0] == NOT_SET_UP
