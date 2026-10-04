"""Tests for how the bot app is wired: commands registered and the command menu."""

from telegram.ext import CommandHandler

from travelkaki.bot.app import COMMANDS, build_application


def test_command_menu_lists_m1_commands():
    assert {c.command for c in COMMANDS} == {"start", "newtrip", "add", "places"}


def test_application_registers_newtrip():
    app = build_application("123:fake-token")
    handlers = app.handlers[0]
    assert any(isinstance(h, CommandHandler) and "newtrip" in h.commands for h in handlers)
