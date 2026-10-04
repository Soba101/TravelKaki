"""Tests for the /start command. No network: we use a fake Telegram update."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.ext import CommandHandler

from travelkaki.bot.app import build_application
from travelkaki.bot.handlers import WELCOME_TEXT, start


async def test_start_replies_with_welcome_and_privacy_notice():
    # Fake update: only the parts our handler touches.
    message = SimpleNamespace(reply_text=AsyncMock())
    update = SimpleNamespace(effective_message=message, effective_chat=SimpleNamespace(id=1))

    await start(update, context=None)

    message.reply_text.assert_awaited_once_with(WELCOME_TEXT)


def test_welcome_text_says_what_is_stored():
    text = WELCOME_TEXT.lower()
    # Issue #3: the welcome must state what is stored and how to delete it.
    for word in ["links", "places", "votes", "plans", "/forget"]:
        assert word in text


def test_application_registers_start_command():
    # Building the app does not contact Telegram; it only sets things up.
    app = build_application("123:fake-token")
    handlers = app.handlers[0]
    assert any(isinstance(h, CommandHandler) and "start" in h.commands for h in handlers)
