"""Run the pipeline in the background and post what it found (cards or an error).

Started with application.create_task(...) by bot/links.py, so the chat
handler returns at once while the (slower) LLM work happens here.
"""

import logging
from html import escape

from telegram import LinkPreviewOptions, ReplyParameters
from telegram.error import TelegramError

from travelkaki.bot.cards import card_keyboard, card_text, error_text, retry_keyboard
from travelkaki.db import queries
from travelkaki.db.place_queries import VoteCounts
from travelkaki.deps import Deps
from travelkaki.ingest import pipeline
from travelkaki.ingest.pipeline import PipelineResult

log = logging.getLogger(__name__)

# Errors where pressing Retry can help (the others need a different action).
RETRYABLE = {pipeline.LLM_UNAVAILABLE, pipeline.UNKNOWN, "interrupted"}


async def send(bot, chat_id: int, text: str, reply_to: int | None = None, markup=None) -> None:
    """Send one HTML message. A Telegram error is logged, never crashes the task."""
    try:
        await bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=markup,
            # Reply to the posted link when we can; still send if it was deleted.
            reply_parameters=ReplyParameters(reply_to, allow_sending_without_reply=True)
            if reply_to
            else None,
            link_preview_options=LinkPreviewOptions(is_disabled=True),  # no big map previews
        )
    except TelegramError as e:
        log.warning("send failed chat=%s: %s", chat_id, e)


async def _post(bot, chat_id, reply_to, result: PipelineResult, poster, platform, deps, source_id):
    if result.error:
        markup = retry_keyboard(source_id) if source_id and result.error in RETRYABLE else None
        await send(bot, chat_id, error_text(result.error, bot.username), reply_to, markup)
        return
    with deps.sessions() as s:
        city = queries.get_trip(s, chat_id).city
    for place in result.places:
        text = card_text(place, city, poster, platform)
        await send(bot, chat_id, text, reply_to, card_keyboard(place, VoteCounts()))
    for name in result.merged:
        await send(bot, chat_id, f"{escape(name)} already saved (+1 link)", reply_to)
    if result.extra:
        await send(bot, chat_id, f"+{result.extra} more, see /places", reply_to)


async def post_pipeline(bot, chat_id, reply_to, source_id, poster, platform, deps: Deps) -> None:
    """Background task for a posted link."""
    result = await pipeline.run(source_id, deps)
    await _post(bot, chat_id, reply_to, result, poster, platform, deps, source_id)


async def post_text_add(bot, chat_id, reply_to, trip_id, name, deps: Deps) -> None:
    """Background task for '@bot add <name>' and '/add <name>'."""
    result = await pipeline.add_by_name(trip_id, name, deps)
    await _post(bot, chat_id, reply_to, result, None, None, deps, None)
