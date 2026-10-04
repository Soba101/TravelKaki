"""Tests for how the bot app is wired: commands registered and the command menu."""

from telegram.ext import CommandHandler

from travelkaki.bot.app import COMMANDS, build_application


def test_command_menu_lists_m1_commands():
    # M2 added /plan to the menu.
    assert {c.command for c in COMMANDS} == {"start", "newtrip", "add", "places", "plan"}


def test_application_registers_newtrip():
    app = build_application("123:fake-token")
    handlers = app.handlers[0]
    assert any(isinstance(h, CommandHandler) and "newtrip" in h.commands for h in handlers)


def test_application_registers_add_places_and_buttons():
    from telegram.ext import CallbackQueryHandler

    handlers = build_application("123:fake-token").handlers[0]
    commands = {c for h in handlers if isinstance(h, CommandHandler) for c in h.commands}
    assert {"add", "places"} <= commands
    assert any(isinstance(h, CallbackQueryHandler) for h in handlers)


def test_edited_commands_are_not_run_again():
    # Editing "/add Ichiran" must not add a second place. (PR3 review)
    from datetime import UTC, datetime

    from telegram import Chat, Message, Update

    msg = Message(
        message_id=1, date=datetime.now(UTC), chat=Chat(id=1, type="group"), text="/add x"
    )
    edited = Update(update_id=1, edited_message=msg)
    handlers = build_application("123:fake-token").handlers[0]
    for h in handlers:
        if isinstance(h, CommandHandler):
            assert not h.filters.check_update(edited), h.commands


async def test_error_handler_replies():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from travelkaki.bot.handlers import on_error

    bot = SimpleNamespace(send_message=AsyncMock())
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=5))
    await on_error(update, SimpleNamespace(bot=bot, error=RuntimeError("bug")))
    assert "Something went wrong" in bot.send_message.await_args.args[1]


def test_telegram_timeouts_are_generous():
    # PR3 demo: a card send timed out at PTB's 5 s default while Ollama was busy.
    bot = build_application("123:fake-token").bot
    assert bot.request.read_timeout == 20
    assert bot.request._client.timeout.write == 20  # PTB has no public getter for this one
