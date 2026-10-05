"""The /plan command: args, lock, progress message, posted plan (M2 Task 13, #22)."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from tests.fakes import GOOD_RUN, FakeToolLlm, make_deps
from travelkaki.bot.plan import parse_window, plan_command
from travelkaki.db import place_queries as pq
from travelkaki.db import queries
from travelkaki.db.models import Itinerary
from travelkaki.planner.types import Window


class NoGeo:
    """Geocoder that finds nothing (hotel -> city centre, hours stay unknown)."""

    async def locate(self, *a):
        return None, "none"

    async def search(self, *a, **kw):
        return None


def _ctx(sessions, args=(), llm=None):
    tasks = []
    deps = make_deps(sessions, llm=llm or FakeToolLlm(GOOD_RUN))
    deps.geo = NoGeo()
    bot = SimpleNamespace(
        send_message=AsyncMock(), edit_message_text=AsyncMock(), delete_message=AsyncMock()
    )
    ctx = SimpleNamespace(
        bot=bot, args=list(args), bot_data={"deps": deps},
        application=SimpleNamespace(create_task=tasks.append),
    )  # fmt: skip
    message = SimpleNamespace(reply_text=AsyncMock(return_value=SimpleNamespace(message_id=77)))
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), effective_message=message)
    return update, ctx, tasks


def _trip(sessions, dates=True):
    start, end = (date(2026, 12, 15), date(2026, 12, 16)) if dates else (None, None)
    with sessions() as s:
        trip = queries.upsert_trip(s, 1, "Tokyo", start, end, None, 35.69, 139.70)
        for i, name in enumerate(["Ichiran", "teamLab"]):
            p = pq.add_place(s, trip.id, name=name, category="museum", video_note="",
                             lat=35.69 + i * 0.002, lng=139.70, opening_hours="24/7")  # fmt: skip
            pq.vote(s, p.id, 5, "must")


def _edits(ctx):
    return [
        c.args[0] if c.args else c.kwargs["text"] for c in ctx.bot.edit_message_text.await_args_list
    ]


def _sent(ctx):
    return [
        c.args[1] if len(c.args) > 1 else c.kwargs["text"]
        for c in ctx.bot.send_message.await_args_list
    ]


def test_parse_window():
    assert parse_window([]) == Window()
    assert parse_window(["10-22"]) == Window(600, 1320, fixed=True)
    assert parse_window(["18-2"]) == Window(1080, 1560, fixed=True)
    for bad in (["tomorrow"], ["10-22", "x"], ["25-3"], ["10-10"]):
        with pytest.raises(ValueError):
            parse_window(bad)


async def test_bad_args_usage(sessions):
    update, ctx, tasks = _ctx(sessions, ["soon"])
    await plan_command(update, ctx)
    assert "Usage: /plan" in update.effective_message.reply_text.await_args.args[0]
    assert tasks == []


async def test_no_trip_reply(sessions):
    update, ctx, tasks = _ctx(sessions)
    await plan_command(update, ctx)
    await tasks[0]
    assert "/newtrip" in _edits(ctx)[-1]


async def test_no_dates_reply(sessions):
    _trip(sessions, dates=False)
    update, ctx, tasks = _ctx(sessions)
    await plan_command(update, ctx)
    await tasks[0]
    assert "Add dates" in _edits(ctx)[-1]


async def test_double_plan_is_refused(sessions):
    """Review Focus 2: /plan twice quickly -> one run."""
    _trip(sessions)
    update, ctx, tasks = _ctx(sessions)
    await plan_command(update, ctx)
    await plan_command(update, ctx)
    assert len(tasks) == 1
    replies = [c.args[0] for c in update.effective_message.reply_text.await_args_list]
    assert replies[-1] == "Already planning, hang on ⏳"
    await tasks[0]
    await plan_command(update, ctx)  # lock released after the run
    assert len(tasks) == 2
    tasks[1].close()


async def test_full_run_posts_plan_and_saves_itinerary(sessions):
    _trip(sessions)
    update, ctx, tasks = _ctx(sessions, ["10-22"])
    await plan_command(update, ctx)
    assert update.effective_message.reply_text.await_args.args[0] == "Planning… 🗺"
    await tasks[0]
    text = "\n".join(_sent(ctx))
    assert "Tokyo plan" in text and "Ichiran" in text and "Trade-offs: Everything fits." in text
    ctx.bot.delete_message.assert_awaited_once_with(1, 77)
    with sessions() as s:
        it = s.scalar(select(Itinerary))
        assert (it.version, it.used_ai, it.window) == (1, True, "10-22")
        assert s.scalar(select(func.count()).select_from(Itinerary)) == 1


async def test_crash_is_not_silent(sessions, monkeypatch):
    import travelkaki.bot.plan as plan_module

    async def boom(*a, **kw):
        raise RuntimeError("bug")

    monkeypatch.setattr(plan_module, "prepare", boom)
    update, ctx, tasks = _ctx(sessions)
    await plan_command(update, ctx)
    await tasks[0]
    assert _edits(ctx)[-1] == "Planning failed, please try /plan again."
    assert ctx.bot_data["planning"] == set()


def test_application_registers_plan():
    from telegram.ext import CommandHandler

    from travelkaki.bot.app import COMMANDS, build_application

    handlers = build_application("123:fake-token").handlers[0]
    assert any(isinstance(h, CommandHandler) and "plan" in h.commands for h in handlers)
    assert "plan" in [c.command for c in COMMANDS]


async def test_failed_send_is_not_silent(sessions):
    """PR2 review #3: if the plan can't be posted, the progress message says so."""
    from telegram.error import TimedOut

    _trip(sessions)
    update, ctx, tasks = _ctx(sessions)
    ctx.bot.send_message.side_effect = TimedOut()
    await plan_command(update, ctx)
    await tasks[0]
    assert _edits(ctx)[-1] == "Planning failed, please try /plan again."
    ctx.bot.delete_message.assert_not_awaited()


async def test_failed_edit_falls_back_to_a_new_message(sessions):
    """PR2 review #3: if the progress message is gone, the error is sent as a new message."""
    from telegram.error import BadRequest

    update, ctx, tasks = _ctx(sessions)  # no trip
    ctx.bot.edit_message_text.side_effect = BadRequest("message to edit not found")
    await plan_command(update, ctx)
    await tasks[0]
    assert "/newtrip" in _sent(ctx)[-1]


async def test_plan_offers_ask_group(sessions):
    """M2 PR3: /plan gives the agent the poll tool."""
    _trip(sessions)
    llm = FakeToolLlm(GOOD_RUN)
    update, ctx, tasks = _ctx(sessions, llm=llm)
    await plan_command(update, ctx)
    await tasks[0]
    assert "ask_group" in llm.seen[0][1]
    assert ctx.bot_data["polls"] == {}


async def test_plan_posts_map_button_when_set_up(sessions):
    # M3 (#26): after the plan, an "Open map" button, if MINI_APP_URL is set.
    _trip(sessions)
    update, ctx, tasks = _ctx(sessions)
    ctx.bot_data["deps"].mini_app_url = "https://t.me/Bot/map"
    await plan_command(update, ctx)
    await tasks[0]
    last = ctx.bot.send_message.await_args_list[-1].kwargs["reply_markup"]
    assert last.inline_keyboard[0][0].url.startswith("https://t.me/Bot/map?startapp=")


async def test_plan_without_map_url_has_no_button(sessions):
    _trip(sessions)
    update, ctx, tasks = _ctx(sessions)
    await plan_command(update, ctx)
    await tasks[0]
    assert "See the days on the map:" not in _sent(ctx)
