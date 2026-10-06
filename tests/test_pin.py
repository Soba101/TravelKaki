"""Tests for /pin: set a place's map pin by replying with a Telegram location."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ApplicationHandlerStop

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


def _text_reply(to_id, text, chat_id=1):
    msg = SimpleNamespace(
        reply_to_message=SimpleNamespace(message_id=to_id) if to_id else None,
        text=text,
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


PLACE_URL = "https://www.google.com/maps/place/X/@35.69,139.70,17z/data=!3d35.6938!4d139.7034"


async def test_link_reply_saves_pin(sessions):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.chat_data["pin_prompts"] = {55: place.id}
    update, msg = _text_reply(55, f"here {PLACE_URL}")
    with pytest.raises(ApplicationHandlerStop):  # handled: on_message must not also run
        await pin.on_link(update, ctx)
    with sessions() as s:
        saved = pq.get_place(s, place.id)
        assert (saved.lat, saved.lng) == (35.6938, 139.7034)
    assert "Pinned Tiny Shop" in msg.reply_text.await_args.args[0]
    assert ctx.chat_data["pin_prompts"] == {}


async def test_short_link_is_resolved(sessions, monkeypatch):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.chat_data["pin_prompts"] = {55: place.id}
    resolve = AsyncMock(return_value=PLACE_URL)
    monkeypatch.setattr(pin.gmaps_link, "resolve", resolve)
    update, _ = _text_reply(55, "https://maps.app.goo.gl/abc123")
    with pytest.raises(ApplicationHandlerStop):
        await pin.on_link(update, ctx)
    resolve.assert_awaited_once()
    with sessions() as s:
        assert pq.get_place(s, place.id).lat == 35.6938


async def test_unreadable_link_keeps_prompt(sessions):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.chat_data["pin_prompts"] = {55: place.id}
    update, msg = _text_reply(55, "https://www.google.com/maps/place/Some+Shop")
    with pytest.raises(ApplicationHandlerStop):
        await pin.on_link(update, ctx)
    assert "Couldn't read a location" in msg.reply_text.await_args.args[0]
    assert ctx.chat_data["pin_prompts"] == {55: place.id}  # still usable
    with sessions() as s:
        assert pq.get_place(s, place.id).lat is None


async def test_text_without_link_or_other_reply_falls_through(sessions):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.chat_data["pin_prompts"] = {55: place.id}
    for to_id, text in ((55, "just chatting"), (99, PLACE_URL), (None, PLACE_URL)):
        update, msg = _text_reply(to_id, text)
        await pin.on_link(update, ctx)  # no ApplicationHandlerStop
        msg.reply_text.assert_not_awaited()
    with sessions() as s:
        assert pq.get_place(s, place.id).lat is None


async def test_link_reply_in_wrong_chat_falls_through(sessions):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.chat_data["pin_prompts"] = {55: place.id}
    update, _ = _text_reply(55, PLACE_URL, chat_id=2)
    await pin.on_link(update, ctx)
    with sessions() as s:
        assert pq.get_place(s, place.id).lat is None


async def test_prompt_text_mentions_links(sessions):
    place = _place(sessions)
    ctx, q = _ctx(sessions), _tap(f"p:{place.id}")
    await pin.pick(q, 1, place.id, ctx, ctx.bot_data["deps"])
    assert (
        "Google Maps link, coordinates (lat, lng), or a Telegram location for Tiny Shop"
        in (ctx.bot.send_message.await_args.args[1])
    )


RAMEN_URL = (
    "https://www.google.com/maps?q=Ramen+Afro+Beats+Shinjuku,+103+1+Chome-16-10+Shinjuku,"
    "+Shinjuku+City,+Tokyo+160-0022,+Japan&ftid=0x60188dac4c941cd3:0x37e3afb8ba57e79e&entry=gps"
)


class FakeGeo:
    """search() answers by query text; search_postcode() records its arguments."""

    def __init__(self, by_text=None, by_postcode=None):
        self.by_text, self.by_postcode, self.postcode_args = by_text, by_postcode, None

    async def search(self, query, box=None):
        return self.by_text

    async def search_postcode(self, postcode, country):
        self.postcode_args = (postcode, country)
        return self.by_postcode


async def _ramen(sessions, monkeypatch, geo):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.bot_data["deps"].geo = geo
    ctx.chat_data["pin_prompts"] = {55: place.id}
    monkeypatch.setattr(pin.gmaps_link, "resolve", AsyncMock(return_value=RAMEN_URL))
    update, msg = _text_reply(55, "https://maps.app.goo.gl/1YBXvucixP6gjGkD8")
    with pytest.raises(ApplicationHandlerStop):
        await pin.on_link(update, ctx)
    return place, ctx, msg


async def test_text_link_uses_geocoder_on_query(sessions, monkeypatch):
    hit = SimpleNamespace(lat=35.69, lng=139.70)
    geo = FakeGeo(by_text=hit)
    place, ctx, msg = await _ramen(sessions, monkeypatch, geo)
    with sessions() as s:
        assert pq.get_place(s, place.id).lat == 35.69
    assert "approximate" not in msg.reply_text.await_args.args[0]
    assert geo.postcode_args is None


async def test_text_link_falls_back_to_postcode(sessions, monkeypatch):
    geo = FakeGeo(by_postcode=SimpleNamespace(lat=35.6922, lng=139.7042))
    place, ctx, msg = await _ramen(sessions, monkeypatch, geo)
    assert geo.postcode_args == ("160-0022", "Japan")
    with sessions() as s:
        assert pq.get_place(s, place.id).lat == 35.6922
    text = msg.reply_text.await_args.args[0]
    assert "Pinned Tiny Shop (approximate, from the postcode)" in text
    assert "Wrong place" in text
    assert ctx.chat_data["pin_prompts"] == {}


async def test_text_link_nothing_found_keeps_prompt(sessions, monkeypatch):
    place, ctx, msg = await _ramen(sessions, monkeypatch, FakeGeo())
    assert "Couldn't read a location" in msg.reply_text.await_args.args[0]
    assert ctx.chat_data["pin_prompts"] == {55: place.id}


async def test_plain_coordinates_reply(sessions):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.chat_data["pin_prompts"] = {55: place.id}
    update, msg = _text_reply(55, "35.6905, 139.7066")
    with pytest.raises(ApplicationHandlerStop):
        await pin.on_link(update, ctx)
    with sessions() as s:
        saved = pq.get_place(s, place.id)
        assert (saved.lat, saved.lng) == (35.6905, 139.7066)
    assert "Pinned Tiny Shop" in msg.reply_text.await_args.args[0]


async def test_link_pin_saves_the_original_link(sessions, monkeypatch):
    place = _place(sessions)
    ctx = _ctx(sessions)
    ctx.chat_data["pin_prompts"] = {55: place.id}
    short = "https://maps.app.goo.gl/abc123"
    monkeypatch.setattr(pin.gmaps_link, "resolve", AsyncMock(return_value=PLACE_URL))
    update, _ = _text_reply(55, short)
    with pytest.raises(ApplicationHandlerStop):
        await pin.on_link(update, ctx)
    with sessions() as s:
        assert pq.get_place(s, place.id).maps_link == short


async def test_coordinate_and_location_pins_clear_the_link(sessions):
    place = _place(sessions)
    with sessions() as s:
        pq.set_pin(s, place.id, 1.0, 2.0, "https://maps.app.goo.gl/old")
        pq.set_pin(s, place.id, 3.0, 4.0)  # a later pin without a link
        assert pq.get_place(s, place.id).maps_link is None
