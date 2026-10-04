"""Tests for how the bot app is wired: commands registered and the command menu."""

from telegram.ext import CommandHandler

from travelkaki.bot.app import COMMANDS, build_application


def test_command_menu_lists_m1_commands():
    assert {c.command for c in COMMANDS} == {"start", "newtrip", "add", "places"}


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
