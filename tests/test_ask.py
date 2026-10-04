"""ask_group: a Telegram poll the planner can post, with early close (M2 Task 15, #20)."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.planner_helpers import make_input, place
from travelkaki.planner.ask import NO_PREFERENCE, ask_group, on_poll
from travelkaki.planner.tools import ToolState, run_tool


def _bot(counts=(2, 0, 0)):
    names = ["A", "B", NO_PREFERENCE]
    options = [SimpleNamespace(text=t, voter_count=c) for t, c in zip(names, counts, strict=True)]
    posted = SimpleNamespace(message_id=5, poll=SimpleNamespace(id="p1"))
    return SimpleNamespace(
        send_poll=AsyncMock(return_value=posted),
        stop_poll=AsyncMock(return_value=SimpleNamespace(options=options)),
    )


def _poll_update(total):
    return SimpleNamespace(poll=SimpleNamespace(id="p1", total_voter_count=total))


async def test_early_close():
    bot, waiters = _bot(), {}
    task = asyncio.create_task(ask_group(bot, 1, "Which?", ["A", "B"], 2, waiters, timeout=10))
    await asyncio.sleep(0)  # let it post the poll
    ctx = SimpleNamespace(bot_data={"polls": waiters})
    await on_poll(_poll_update(1), ctx)  # 1 of 2: keep waiting
    assert not task.done()
    await on_poll(_poll_update(2), ctx)
    result = await asyncio.wait_for(task, 1)
    assert result == {"A": 2, "B": 0, NO_PREFERENCE: 0}
    bot.send_poll.assert_awaited_once()
    assert bot.send_poll.await_args.args[2] == ["A", "B", NO_PREFERENCE]
    bot.stop_poll.assert_awaited_once_with(1, 5)
    assert waiters == {}


async def test_timeout_still_returns_counts():
    bot = _bot((0, 1, 0))
    assert await ask_group(bot, 1, "Which?", ["A", "B"], 3, {}, timeout=0.01) == {
        "A": 0, "B": 1, NO_PREFERENCE: 0,
    }  # fmt: skip


async def test_unknown_poll_update_is_ignored():
    await on_poll(_poll_update(5), SimpleNamespace(bot_data={}))  # no crash


def _state(answers):
    calls = []

    async def ask(question, options):
        calls.append((question, options))
        return answers

    st = ToolState(make_input([place(1)], days=1), ask=ask)
    return st, calls


async def test_tool_posts_and_returns_votes():
    st, calls = _state({"teamLab": 3, "Shibuya Sky": 1})
    out = await run_tool(
        "ask_group", '{"question": "Day 2?", "options": ["teamLab", "Shibuya Sky"]}', st
    )
    assert json.loads(out) == {"teamLab": 3, "Shibuya Sky": 1}
    assert calls == [("Day 2?", ["teamLab", "Shibuya Sky"])] and st.polls == 1


async def test_third_poll_refused():
    st, calls = _state({"a": 1})
    args = '{"question": "?", "options": ["a", "b"]}'
    for _ in range(2):
        await run_tool("ask_group", args, st)
    assert await run_tool("ask_group", args, st) == "limit reached, decide yourself"
    assert len(calls) == 2


async def test_bad_options_rejected():
    st, calls = _state({})
    for args in ['{"question": "?", "options": ["only one"]}',
                 '{"question": "?", "options": ["a", "b", "c", "d", "e"]}',
                 '{"question": "?", "options": "a,b"}',
                 '{"question": "", "options": ["a", "b"]}',
                 json.dumps({"question": "?", "options": ["x" * 101, "b"]})]:  # fmt: skip
        assert (await run_tool("ask_group", args, st)).startswith("error")
    assert calls == []


async def test_poll_failure_is_a_tool_error():
    async def broken(question, options):
        raise RuntimeError("telegram down")

    st = ToolState(make_input([place(1)], days=1), ask=broken)
    out = await run_tool("ask_group", '{"question": "?", "options": ["a", "b"]}', st)
    assert out.startswith("error: couldn't post the poll")


def test_application_registers_poll_handler():
    from telegram.ext import PollHandler

    from travelkaki.bot.app import build_application

    handlers = build_application("123:fake-token").handlers[0]
    assert any(isinstance(h, PollHandler) for h in handlers)
