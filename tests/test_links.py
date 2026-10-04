"""Tests for link detection, /add and @mention adds (issue #8). Fake Telegram objects."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import func, select
from telegram import Chat, Message, MessageEntity, Update, User
from telegram.error import BadRequest
from telegram.ext import MessageHandler

from tests.fakes import make_deps, make_source
from travelkaki.bot import links, results
from travelkaki.bot.app import build_application
from travelkaki.db import place_queries as pq
from travelkaki.db import queries
from travelkaki.db.models import Source
from travelkaki.ingest.pipeline import PipelineResult

TIKTOK = "https://www.tiktok.com/@a/video/1"


def _message(text, entities=(), caption=False):
    kw = (
        {"caption": text, "caption_entities": list(entities)}
        if caption
        else {"text": text, "entities": list(entities)}
    )
    return Message(
        message_id=50,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="group"),
        from_user=User(id=7, first_name="Alex", is_bot=False),
        **kw,
    )


def _url_message(url, prefix="look ", caption=False):
    entity = MessageEntity(type="url", offset=len(prefix), length=len(url))
    return _message(prefix + url, [entity], caption)


def _ctx(sessions, args=None):
    tasks = []
    bot = SimpleNamespace(
        username="travelkakiibot", send_message=AsyncMock(), set_message_reaction=AsyncMock()
    )
    ctx = SimpleNamespace(
        bot=bot,
        args=args,
        bot_data={"deps": make_deps(sessions)},
        application=SimpleNamespace(create_task=tasks.append),
    )
    return ctx, tasks


def _update(message):
    return SimpleNamespace(
        effective_message=message, effective_chat=message.chat, effective_user=message.from_user
    )


def _sources(sessions):
    with sessions() as s:
        return s.scalar(select(func.count()).select_from(Source))


def _sent(ctx):
    return [
        c.args[1] if len(c.args) > 1 else c.kwargs["text"]
        for c in ctx.bot.send_message.await_args_list
    ]


def _close(tasks):
    for t in tasks:
        t.close()  # we only check the task was started; don't run it


def test_find_links_reads_url_and_text_link_entities():
    hidden = MessageEntity(type="text_link", offset=0, length=4, url=TIKTOK)
    assert links.find_links(_message("here", [hidden])) == [TIKTOK]
    assert links.find_links(_url_message(TIKTOK, caption=True)) == [TIKTOK]
    many = _message(
        " ".join(["x"] * 7), [MessageEntity(type="url", offset=i * 2, length=1) for i in range(7)]
    )
    assert len(links.find_links(many)) == 5


def test_parse_mention_add():
    assert (
        links.parse_mention_add("@TravelKakiiBot add Ichiran Shibuya", "travelkakiibot")
        == "Ichiran Shibuya"
    )
    assert links.parse_mention_add("let's add Ichiran", "travelkakiibot") is None


async def test_link_with_trip_saves_reacts_and_starts_task(sessions):
    make_source(sessions, url="https://www.tiktok.com/@other/video/9")  # the trip
    ctx, tasks = _ctx(sessions)
    await links.on_message(_update(_url_message(TIKTOK)), ctx)
    assert _sources(sessions) == 2
    ctx.bot.set_message_reaction.assert_awaited_once()
    assert len(tasks) == 1
    _close(tasks)


async def test_link_without_trip_says_start_a_trip(sessions):
    ctx, tasks = _ctx(sessions)
    await links.on_message(_update(_url_message(TIKTOK)), ctx)
    assert "/newtrip Tokyo 12-15 Dec" in _sent(ctx)[0]
    assert _sources(sessions) == 0 and tasks == []


async def test_same_link_twice_is_already_saved(sessions):
    make_source(sessions, url=TIKTOK)
    ctx, tasks = _ctx(sessions)
    await links.on_message(_update(_url_message(TIKTOK + "?x=1")), ctx)
    assert _sent(ctx) == ["Already saved ✅"] and tasks == []


async def test_other_links_and_chat_are_ignored(sessions):
    make_source(sessions)
    ctx, tasks = _ctx(sessions)
    await links.on_message(_update(_url_message("https://www.youtube.com/watch?v=x")), ctx)
    await links.on_message(_update(_message("see you at 7, let's add snacks")), ctx)
    assert _sent(ctx) == [] and tasks == [] and _sources(sessions) == 1


async def test_reaction_failure_still_processes(sessions):
    make_source(sessions, url="https://www.tiktok.com/@other/video/9")
    ctx, tasks = _ctx(sessions)
    ctx.bot.set_message_reaction.side_effect = BadRequest("reactions off")
    await links.on_message(_update(_url_message(TIKTOK)), ctx)
    assert len(tasks) == 1
    _close(tasks)


async def test_mention_and_add_command_text_add(sessions):
    make_source(sessions)
    ctx, tasks = _ctx(sessions)
    await links.on_message(_update(_message("@travelkakiibot add Ichiran")), ctx)
    await links.add_command(
        _update(_message("/add Butagumi")), SimpleNamespace(**{**vars(ctx), "args": ["Butagumi"]})
    )
    assert len(tasks) == 2 and _sources(sessions) == 1  # text adds create no source
    _close(tasks)


async def test_add_command_with_link_and_without_args(sessions):
    make_source(sessions, url="https://www.tiktok.com/@other/video/9")
    ctx, tasks = _ctx(sessions, args=[TIKTOK])
    await links.add_command(_update(_message("/add " + TIKTOK)), ctx)
    assert _sources(sessions) == 2
    _close(tasks)
    ctx2, _ = _ctx(sessions, args=[])
    await links.add_command(_update(_message("/add")), ctx2)
    assert "/add" in _sent(ctx2)[0]


def test_edited_messages_are_not_handled():
    # Review Focus 1: an edit must not process the same link again.
    app = build_application("123:fake-token")
    handler = next(h for h in app.handlers[0] if isinstance(h, MessageHandler))
    msg = _url_message(TIKTOK)
    assert handler.check_update(Update(update_id=1, message=msg))
    assert not handler.check_update(Update(update_id=2, edited_message=msg))


async def test_post_pipeline_sends_cards(sessions, monkeypatch):
    trip, source = make_source(sessions)
    with sessions() as s:
        places = [
            pq.add_place(s, trip.id, name=n, category="food", video_note="") for n in ("A", "B")
        ]
    monkeypatch.setattr(
        results.pipeline, "run", AsyncMock(return_value=PipelineResult(places=places, extra=3))
    )
    ctx, _ = _ctx(sessions)
    await results.post_pipeline(ctx.bot, 1, 50, source.id, "Alex", "tiktok", make_deps(sessions))
    calls = ctx.bot.send_message.await_args_list
    assert len(calls) == 3  # 2 cards + "+3 more"
    assert all(c.kwargs["parse_mode"] == "HTML" for c in calls)
    assert calls[0].kwargs["reply_markup"] is not None
    assert "+3 more" in _sent(ctx)[2]


async def test_post_pipeline_error_has_retry(sessions, monkeypatch):
    _, source = make_source(sessions)
    monkeypatch.setattr(
        results.pipeline, "run", AsyncMock(return_value=PipelineResult(error="llm_unavailable"))
    )
    ctx, _ = _ctx(sessions)
    await results.post_pipeline(ctx.bot, 1, 50, source.id, "Alex", "tiktok", make_deps(sessions))
    call = ctx.bot.send_message.await_args
    assert "Ollama" in _sent(ctx)[0]
    assert call.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == f"r:{source.id}"
    with sessions() as s:
        assert queries.get_trip(s, 1) is not None
