"""ask_group: the planner asks the group with a Telegram poll (M2 spec, issue #20).

The agent uses this when two Must-go places compete and no plan fits both.
- Posts an anonymous poll with the options + "No preference".
- Waits up to 5 minutes, or less: as soon as as many people have answered as
  voted on places (`target`), the poll closes early.
- Then stops the poll and returns the votes, e.g. {"teamLab": 3, "Shibuya Sky": 1}.

How the early close works: Telegram sends the bot a "poll" update each time the
counts change. on_poll() checks the total and wakes up the waiting planner.
"""

import asyncio
import logging

log = logging.getLogger(__name__)

POLL_WAIT = 300  # seconds
NO_PREFERENCE = "No preference"
MAX_OPTION_CHARS = 100  # Telegram's poll limits
MAX_QUESTION_CHARS = 300


def poll_problem(question, options) -> str | None:
    """What's wrong with these poll arguments from the model, or None if they're fine."""
    if not isinstance(question, str) or not 0 < len(question.strip()) <= MAX_QUESTION_CHARS:
        return f"question must be 1-{MAX_QUESTION_CHARS} characters"
    if (
        not isinstance(options, list)
        or not 2 <= len(options) <= 4
        or not all(isinstance(o, str) and 0 < len(o.strip()) <= MAX_OPTION_CHARS for o in options)
    ):
        return f"options must be 2-4 short texts (max {MAX_OPTION_CHARS} characters)"
    return None


async def ask_group(
    bot, chat_id: int, question: str, options: list[str], target: int, waiters: dict,
    timeout: float = POLL_WAIT,
) -> dict[str, int]:  # fmt: skip
    """Post the poll, wait, stop it, and return the votes per option."""
    message = await bot.send_poll(chat_id, question, options + [NO_PREFERENCE], is_anonymous=True)
    poll_id = message.poll.id
    done = asyncio.Event()
    waiters[poll_id] = (target, done)  # on_poll() finds us here
    poll = None
    try:
        await asyncio.wait_for(done.wait(), timeout)
    except TimeoutError:
        pass  # 5 minutes passed: use the votes we have
    finally:
        waiters.pop(poll_id, None)
        # Always close the poll, even if the run was cancelled, so the group isn't
        # left voting on a question nobody reads. (PR3 review #1)
        try:
            poll = await asyncio.shield(bot.stop_poll(chat_id, message.message_id))
        except Exception as e:  # noqa: BLE001 - e.g. someone deleted the poll message
            log.warning("stop_poll failed chat=%s: %s", chat_id, type(e).__name__)
    return {o.text: o.voter_count for o in poll.options} if poll is not None else {}


async def on_poll(update, context) -> None:
    """A poll's counts changed. Wake the planner if enough people have answered."""
    poll = update.poll
    waiter = context.bot_data.get("polls", {}).get(poll.id)
    if waiter is None:
        return  # not one of our open polls
    target, done = waiter
    if poll.total_voter_count >= target:
        done.set()


def release_all(waiters: dict) -> None:
    """End every open poll wait now (used on shutdown, so polls get stopped). (PR3 review #4)"""
    for _, done in list(waiters.values()):
        done.set()
