"""/plan: plan the trip's days with the agent (M2 spec, "/plan in the chat", issue #22).

1. Read optional hours: "/plan" (flexible days) or "/plan 10-22" (fixed hours).
2. One plan per chat at a time. A second /plan gets "Already planning".
3. Post "Planning… 🗺" and edit it as the steps go.
4. The slow work runs in the background, so the bot keeps answering.
5. Post the plan, then delete the progress message. Never silent on errors.
"""

import logging
import re
import uuid
from html import escape

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from travelkaki.bot.cards import NO_TRIP
from travelkaki.bot.plan_text import format_plan
from travelkaki.bot.results import send
from travelkaki.db import plan_queries as plq
from travelkaki.planner.ask import ask_group
from travelkaki.planner.loop import run_planner
from travelkaki.planner.prepare import PlanError, prepare
from travelkaki.planner.types import Window

log = logging.getLogger(__name__)

USAGE = "Usage: /plan or /plan 10-22 (fixed start and end hours)"
BUSY = "Already planning, hang on ⏳"
FAILED = "Planning failed, please try /plan again."
PLAN_ERRORS = {
    "no_trip": NO_TRIP,
    "no_dates": "Add dates first: /newtrip Tokyo 12-15 Dec",
    "too_many_days": "That trip is over 14 days. I can plan up to 14 days.",
    "no_places": "Nothing to plan yet. Post some TikTok/IG links first.",
}


def parse_window(args: list[str]) -> Window:
    """[] -> flexible days. ["10-22"] -> 10:00 to 22:00. ["18-2"] ends 02:00 next day."""
    if not args:
        return Window()
    match = re.fullmatch(r"(\d{1,2})-(\d{1,2})", args[0]) if len(args) == 1 else None
    if match is None:
        raise ValueError("bad hours")
    start, end = int(match[1]), int(match[2])
    if start > 24 or end > 24 or start == end:
        raise ValueError("bad hours")
    if end < start:
        end += 24  # past midnight
    return Window(start * 60, end * 60, fixed=True)


async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /plan [hours]."""
    chat_id = update.effective_chat.id
    log.info("plan chat=%s", chat_id)  # never log the message text
    message = update.effective_message
    try:
        window = parse_window(context.args or [])
    except ValueError:
        await message.reply_text(USAGE)
        return
    planning: set = context.bot_data.setdefault("planning", set())
    if chat_id in planning:
        await message.reply_text(BUSY)
        return
    planning.add(chat_id)
    try:
        progress = await message.reply_text("Planning… 🗺")
    except Exception:
        planning.discard(chat_id)  # don't leave the chat locked
        raise
    deps = context.bot_data["deps"]
    polls = context.bot_data.setdefault("polls", {})  # open ask_group polls (on_poll reads it)
    context.application.create_task(
        run_plan(context.bot, chat_id, window, deps, progress.message_id, planning, polls)
    )


async def run_plan(
    bot, chat_id: int, window: Window, deps, progress_id: int, planning, polls: dict | None = None
) -> None:
    """The background part: prepare -> agent -> save -> post. Always unlocks the chat.

    With `polls` (the bot's open-poll table), the agent may ask the group (#20).
    """
    run_id = str(uuid.uuid4())

    async def progress(text: str, final: bool = False) -> None:
        """Edit the progress message. For a final error, send a new message if that fails."""
        try:
            await bot.edit_message_text(text, chat_id, progress_id)
        except TelegramError as e:
            log.warning("progress edit failed chat=%s: %s", chat_id, e)
            if final:  # e.g. someone deleted the progress message (PR2 review #3)
                await send(bot, chat_id, escape(text))

    try:
        inp = await prepare(deps, chat_id, window, progress=progress)
        await progress("Planning the days… 🧠")

        async def ask(question: str, options: list[str]) -> dict[str, int]:
            """The agent's ask_group tool: a poll that closes once everyone who voted answered."""
            await progress("Waiting for the poll (up to 5 min)…")
            with deps.sessions() as s:
                target = max(1, plq.voter_count(s, inp.trip_id))
            votes = await ask_group(bot, chat_id, question, options, target, polls)
            await progress("Planning the days… 🧠")
            return votes

        result = await run_planner(deps, inp, run_id, ask=ask if polls is not None else None)
        with deps.sessions() as s:
            saved = plq.save_itinerary(
                s, inp.trip_id, run_id, result.plan,
                used_ai=result.used_ai, tradeoffs=result.tradeoffs, window=window.label(),
            )  # fmt: skip
        sent = [await send(bot, chat_id, part) for part in format_plan(inp, result, saved.version)]
        if not all(sent):  # never silent: keep the progress message and say so (review #3)
            await progress(FAILED, final=True)
            return
        try:
            await bot.delete_message(chat_id, progress_id)
        except TelegramError:
            pass  # the plan is posted; a leftover progress line is harmless
        log.info("plan chat=%s run=%s rounds=%s used_ai=%s", chat_id, run_id, result.rounds,
                 result.used_ai)  # fmt: skip
    except PlanError as e:
        await progress(PLAN_ERRORS[e.code], final=True)
    except Exception:
        log.exception("plan failed chat=%s run=%s", chat_id, run_id)
        await progress(FAILED, final=True)
    finally:
        planning.discard(chat_id)
