"""Spot TikTok / Instagram links in the group and start reading them (issue #8).

- Any group message with a TikTok/IG link -> saved + read in the background.
- "/add <link>" does the same (for groups where the bot can't see all messages).
- "/add <place name>" or "@travelkakiibot add <place name>" -> text add.
Other messages are ignored: nothing is stored or logged.
"""

import logging
import re

from telegram import MessageEntity, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from travelkaki.bot.cards import NO_TRIP, error_text
from travelkaki.bot.results import post_pipeline, post_text_add, send
from travelkaki.db import queries
from travelkaki.ingest.urls import LinkError, canonical, needs_redirect, normalise

log = logging.getLogger(__name__)

MAX_LINKS = 5  # per message
ADD_USAGE = "Use /add &lt;TikTok or IG link&gt; or /add &lt;place name&gt;"
_URL_TYPES = [MessageEntity.URL, MessageEntity.TEXT_LINK]


def find_links(message) -> list[str]:
    """Links in the text or caption: plain URLs and hidden 'text links'."""
    if message.text:
        entities = message.parse_entities(_URL_TYPES)
    else:
        entities = message.parse_caption_entities(_URL_TYPES)
    found = [e.url if e.type == MessageEntity.TEXT_LINK else text for e, text in entities.items()]
    return found[:MAX_LINKS]


def parse_mention_add(text: str, bot_username: str) -> str | None:
    """'@travelkakiibot add Ichiran' -> 'Ichiran' (any letter case). Else None."""
    match = re.search(rf"@{re.escape(bot_username)}\s+add\s+(.+)", text or "", re.I | re.S)
    return match[1].strip() if match else None


def _is_link(text: str) -> bool:
    return needs_redirect(text) or canonical(text) is not None


async def handle_link(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Save one link and start reading it. Returns False if there's no trip (stop)."""
    deps, chat_id = context.bot_data["deps"], update.effective_chat.id
    message = update.effective_message
    try:
        found = await normalise(url, deps.http)
    except LinkError:
        await send(
            context.bot, chat_id, error_text("link_error", context.bot.username), message.message_id
        )
        return True
    if found is None:
        return True  # not a TikTok/IG post: ignore quietly
    canonical_url, platform = found
    with deps.sessions() as s:
        trip = queries.get_trip(s, chat_id)
        if trip is None:
            await send(context.bot, chat_id, NO_TRIP, message.message_id)
            return False
        source = queries.add_source(s, trip.id, canonical_url, platform, update.effective_user.id)
    if source is None:
        await send(context.bot, chat_id, "Already saved ✅", message.message_id)
        return True
    log.info("link chat=%s platform=%s", chat_id, platform)  # never the URL or message text
    try:
        await context.bot.set_message_reaction(chat_id, message.message_id, "👀")
    except TelegramError:
        pass  # some groups restrict reactions; the cards still follow
    poster = update.effective_user.first_name
    context.application.create_task(
        post_pipeline(context.bot, chat_id, message.message_id, source.id, poster, platform, deps)
    )
    return True


async def handle_text_add(name: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    deps, chat_id = context.bot_data["deps"], update.effective_chat.id
    message_id = update.effective_message.message_id
    with deps.sessions() as s:
        trip = queries.get_trip(s, chat_id)
    if trip is None:
        await send(context.bot, chat_id, NO_TRIP, message_id)
        return
    log.info("text add chat=%s", chat_id)
    context.application.create_task(
        post_text_add(context.bot, chat_id, message_id, trip.id, name, deps)
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Every new group message (not commands, not edits)."""
    message = update.effective_message
    name = parse_mention_add(message.text or message.caption, context.bot.username)
    if name:
        await handle_text_add(name, update, context)
        return
    for url in find_links(message):
        if not await handle_link(url, update, context):
            break  # no trip: one reply is enough


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/add <link> or /add <place name>."""
    text = " ".join(context.args or []).strip()
    log.info("add chat=%s", update.effective_chat.id)
    if not text:
        await send(context.bot, update.effective_chat.id, ADD_USAGE)
    elif _is_link(text.split()[0]):
        await handle_link(text.split()[0], update, context)
    else:
        await handle_text_add(text, update, context)
