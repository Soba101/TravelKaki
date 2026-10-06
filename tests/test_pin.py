"""Tests for /pin: set a place's map pin by replying with a Telegram location."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.fakes import make_deps, make_source
from travelkaki.bot import pin
from travelkaki.bot.cards import parse_callback
from travelkaki.db import place_queries as pq
from travelkaki.db import queries


def _ctx(sessions):
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=55)))
    return SimpleNamespace(bot=bot, bot_data={"deps": make_deps(sessions)}, chat_data={}, args=[])


def _cmd(chat_id=1):
    message = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id), effective_message=message)


def _place(sessions, name="Tiny Shop", lat=None, hours=None):
    trip, _ = make_source(sessions)
    with sessions() as s:
        return pq.add_place(
            s,
            trip.id,
            name=name,
            category="shop",
            video_note="",
            lat=lat,
            lng=lat,
            opening_hours=hours,
        )


def _buttons(message):
    markup = message.reply_text.await_args.kwargs["reply_markup"]
    return [row[0] for row in markup.inline_keyboard]


def _tap(data, chat_id=1):
    q = SimpleNamespace(data=data, message=SimpleNamespace(chat=SimpleNamespace(id=chat_id)))
    q.answer = AsyncMock()
    return q


def _reply(to_id, location=None, venue=None, chat_id=1):
    msg = SimpleNamespace(
        reply_to_message=SimpleNamespace(message_id=to_id) if to_id else None,
        location=location,
        venue=venue,
        reply_text=AsyncMock(),
    )
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id), effective_message=msg), msg


def test_parse_pin_callback():
    assert parse_callback("p:12") == ("p", 12, None)


async def test_pin_lists_only_unpinned(sessions):
    place = _place(sessions)
    with sessions() as s:
        pq.add_place(s, place.trip_id, name="Pinned", category="x", video_note="", lat=1, lng=1)
    update, ctx = _cmd(), _ctx(sessions)
    await pin.pin_command(update, ctx)
    buttons = _buttons(update.effective_message)
    assert [b.text for b in buttons] == ["Tiny Shop"]
    assert buttons[0].callback_data == f"p:{place.id}"


async def test_pin_nothing_to_pin(sessions):
    _place(sessions, lat=1)
    update, ctx = _cmd(), _ctx(sessions)
    await pin.pin_command(update, ctx)
    assert "pin" in update.effective_message.reply_text.await_args.args[0].lower()
    assert "reply_markup" not in update.effective_message.reply_text.await_args.kwargs


async def test_pin_without_trip(sessions):
    update, ctx = _cmd(), _ctx(sessions)
    await pin.pin_command(update, ctx)
    update.effective_message.reply_text.assert_awaited_once()


async def test_pin_caps_the_list_at_ten(sessions):
    place = _place(sessions)
    with sessions() as s:
        for i in range(12):
            pq.add_place(s, place.trip_id, name=f"P{i}", category="x", video_note="")
    update, ctx = _cmd(), _ctx(sessions)
    await pin.pin_command(update, ctx)
    assert len(_buttons(update.effective_message)) == 10


async def test_pin_with_name_skips_the_list(sessions):
    place = _place(sessions)
    update, ctx = _cmd(), _ctx(sessions)
    ctx.args = ["tiny"]  # case-insensitive substring
    await pin.pin_command(update, ctx)
    assert ctx.chat_data["pin_prompts"] == {55: place.id}


async def test_pin_with_unknown_name(sessions):
    _place(sessions)
    update, ctx = _cmd(), _ctx(sessions)
    ctx.args = ["zzz"]
    await pin.pin_command(update, ctx)
    assert "zzz" in update.effective_message.reply_text.await_args.args[0]
    ctx.bot.send_message.assert_not_awaited()


async def test_tap_sends_force_reply_and_remembers(sessions):
    place = _place(sessions)
    ctx, q = _ctx(sessions), _tap(f"p:{place.id}")
    await pin.pick(q, 1, place.id, ctx, ctx.bot_data["deps"])
    kwargs = ctx.bot.send_message.await_args.kwargs
    assert kwargs["reply_markup"].force_reply is True
    assert "Tiny Shop" in ctx.bot.send_message.await_args.args[1]
    assert ctx.chat_data["pin_prompts"] == {55: place.id}


async def test_tap_for_other_chats_place_is_refused(sessions):
    place = _place(sessions)  # belongs to chat 1's trip
    with sessions() as s:
        queries.upsert_trip(s, 2, "Paris", None, None, None)
    ctx, q = _ctx(sessions), _tap(f"p:{place.id}", chat_id=2)
    await pin.pick(q, 2, place.id, ctx, ctx.bot_data["deps"])
    ctx.bot.send_message.assert_not_awaited()
    assert ctx.chat_data == {}


async def test_location_reply_saves_pin(sessions):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.chat_data["pin_prompts"] = {55: place.id}
    update, msg = _reply(55, location=SimpleNamespace(latitude=35.6, longitude=139.7))
    await pin.on_location(update, ctx)
    with sessions() as s:
        saved = pq.get_place(s, place.id)
        assert (saved.lat, saved.lng) == (35.6, 139.7)
        assert saved.opening_hours == ""  # "checked": backfill must not overwrite it
        assert saved.confidence == "high"
    assert "Pinned Tiny Shop" in msg.reply_text.await_args.args[0]
    assert ctx.chat_data["pin_prompts"] == {}  # one reply per prompt


async def test_venue_location_is_used(sessions):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.chat_data["pin_prompts"] = {55: place.id}
    venue = SimpleNamespace(location=SimpleNamespace(latitude=1.3, longitude=103.8))
    update, _ = _reply(55, venue=venue)
    await pin.on_location(update, ctx)
    with sessions() as s:
        assert pq.get_place(s, place.id).lat == 1.3


async def test_non_reply_and_other_replies_are_ignored(sessions):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.chat_data["pin_prompts"] = {55: place.id}
    loc = SimpleNamespace(latitude=1.0, longitude=2.0)
    for to_id in (None, 99):  # not a reply / reply to some other message
        update, msg = _reply(to_id, location=loc)
        await pin.on_location(update, ctx)
        msg.reply_text.assert_not_awaited()
    with sessions() as s:
        assert pq.get_place(s, place.id).lat is None


async def test_location_reply_in_wrong_chat_is_ignored(sessions):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.chat_data["pin_prompts"] = {55: place.id}
    update, msg = _reply(55, location=SimpleNamespace(latitude=1.0, longitude=2.0), chat_id=2)
    await pin.on_location(update, ctx)
    with sessions() as s:
        assert pq.get_place(s, place.id).lat is None
