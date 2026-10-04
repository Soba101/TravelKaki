"""Tests for vote buttons and /places (issue #14). Fake Telegram objects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.fakes import make_deps, make_source
from travelkaki.bot import votes
from travelkaki.db import place_queries as pq


def _query(data, user_id=7, chat_id=1, place_ids=()):
    """A button tap. `place_ids` = the places listed on the tapped message (#49)."""
    from travelkaki.bot.cards import list_keyboard

    markup = list_keyboard([SimpleNamespace(id=i, confidence="none") for i in place_ids], {})
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(
            chat=SimpleNamespace(id=chat_id), text_html="card", reply_markup=markup
        ),
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
        edit_message_text=AsyncMock(),
    )


def _ctx(sessions):
    bot = SimpleNamespace(username="travelkakiibot", send_message=AsyncMock())
    tasks = []
    return SimpleNamespace(
        bot=bot,
        bot_data={"deps": make_deps(sessions)},
        application=SimpleNamespace(create_task=tasks.append),
    ), tasks


def _place(sessions, name="Ichiran"):
    trip, _ = make_source(sessions)
    with sessions() as s:
        return pq.add_place(s, trip.id, name=name, category="ramen", video_note="")


def _must_label(query):
    markup = query.edit_message_reply_markup.await_args.args[0]
    return markup.inline_keyboard[0][0].text


async def test_vote_updates_counts_and_toggles(sessions):
    place = _place(sessions)
    ctx, _ = _ctx(sessions)

    q1 = _query(f"v:{place.id}:m", place_ids=[place.id])
    await votes.on_callback(SimpleNamespace(callback_query=q1, effective_chat=q1.message.chat), ctx)
    assert _must_label(q1) == "1 ✅1"
    q1.answer.assert_awaited_once_with("Voted Must-go")

    q2 = _query(f"v:{place.id}:m", place_ids=[place.id])  # same tap again
    await votes.on_callback(SimpleNamespace(callback_query=q2, effective_chat=q2.message.chat), ctx)
    assert _must_label(q2) == "1 ✅0"
    q2.answer.assert_awaited_once_with("Vote removed")


async def test_stale_or_bad_callback_is_answered_safely(sessions):
    # Review Focus 4: deleted place or junk data -> toast, no crash, no edit.
    _place(sessions)
    ctx, _ = _ctx(sessions)
    for data in ["v:999:m", "garbage"]:
        q = _query(data)
        await votes.on_callback(
            SimpleNamespace(callback_query=q, effective_chat=q.message.chat), ctx
        )
        q.answer.assert_awaited_once_with("This place no longer exists.")
        q.edit_message_reply_markup.assert_not_awaited()


async def test_vote_from_another_chat_is_refused(sessions):
    place = _place(sessions)
    ctx, _ = _ctx(sessions)
    q = _query(f"v:{place.id}:m", chat_id=2)  # chat 2 has no such place
    await votes.on_callback(SimpleNamespace(callback_query=q, effective_chat=q.message.chat), ctx)
    q.answer.assert_awaited_once_with("This place no longer exists.")


async def test_places_command_lists_places(sessions):
    place = _place(sessions)
    with sessions() as s:
        pq.add_place(s, place.trip_id, name="Shibuya Sky", category="view", video_note="")
    ctx, _ = _ctx(sessions)
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1), effective_message=SimpleNamespace(message_id=5)
    )
    await votes.places_command(update, ctx)
    text = ctx.bot.send_message.await_args.args[1]
    assert "Ichiran" in text and "Shibuya Sky" in text


async def test_places_without_trip(sessions):
    ctx, _ = _ctx(sessions)
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1), effective_message=SimpleNamespace(message_id=5)
    )
    await votes.places_command(update, ctx)
    assert "/newtrip" in ctx.bot.send_message.await_args.args[1]


async def test_wrong_place_clears_the_pin(sessions):
    trip, _ = make_source(sessions)
    with sessions() as s:
        place = pq.add_place(
            s,
            trip.id,
            name="Ichiran",
            category="ramen",
            video_note="",
            lat=35.6,
            lng=139.7,
            address="x",
            confidence="low",
        )
    ctx, _ = _ctx(sessions)
    q = _query(f"w:{place.id}", place_ids=[place.id])
    await votes.on_callback(SimpleNamespace(callback_query=q, effective_chat=q.message.chat), ctx)
    q.answer.assert_awaited_once_with("Pin removed")
    with sessions() as s:
        saved = pq.get_place(s, place.id)
    assert (saved.lat, saved.lng, saved.confidence) == (None, None, "none")
    markup = q.edit_message_reply_markup.await_args.args[0]
    assert len(markup.inline_keyboard[0]) == 3  # the 👎📍 button is gone from that row


def _failed_source(sessions, status="failed"):
    from travelkaki.db import queries as q

    _, source = make_source(sessions)
    with sessions() as s:
        q.set_source(s, source.id, status=status, error="llm_unavailable")
    return source


async def test_retry_restarts_a_failed_link(sessions):
    from travelkaki.db import queries as q

    source = _failed_source(sessions)
    ctx, tasks = _ctx(sessions)
    query = _query(f"r:{source.id}")
    await votes.on_callback(
        SimpleNamespace(callback_query=query, effective_chat=query.message.chat), ctx
    )
    query.answer.assert_awaited_once_with("Retrying…")
    query.edit_message_reply_markup.assert_awaited_once_with(None)  # Retry button removed
    assert len(tasks) == 1
    with sessions() as s:
        assert q.get_source(s, source.id).status == "pending"
    tasks[0].close()


async def test_retry_on_finished_link_does_nothing(sessions):
    source = _failed_source(sessions, status="done")
    ctx, tasks = _ctx(sessions)
    query = _query(f"r:{source.id}")
    await votes.on_callback(
        SimpleNamespace(callback_query=query, effective_chat=query.message.chat), ctx
    )
    query.answer.assert_awaited_once_with("Nothing to retry.")
    assert tasks == []


async def test_vote_keeps_every_place_on_the_message(sessions):
    # One message lists several places: a vote must redraw all rows, in order (#49).
    first = _place(sessions)
    with sessions() as s:
        second = pq.add_place(s, first.trip_id, name="Butagumi", category="x", video_note="")
    ctx, _ = _ctx(sessions)
    q = _query(f"v:{second.id}:s", place_ids=[first.id, second.id])
    await votes.on_callback(SimpleNamespace(callback_query=q, effective_chat=q.message.chat), ctx)
    rows = q.edit_message_reply_markup.await_args.args[0].inline_keyboard
    assert [r[0].text for r in rows] == ["1 ✅0", "2 ✅0"]
    assert rows[1][2].text == "❌1"
