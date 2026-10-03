"""Command handlers for the Telegram bot.

A handler is an async function that Telegram calls when a matching
message arrives. Each one gets `update` (the message) and `context`.
"""

from telegram import Update
from telegram.ext import ContextTypes

# Shown on /start. Issue #3 asks that it clearly states what we store.
# Keep this in sync with the Privacy section of README.md.
WELCOME_TEXT = (
    "Hi! I'm TravelKaki 🧳 — your group's trip planner.\n"
    "\n"
    "Drop TikTok or Instagram links here. I'll pull out the places, "
    "let everyone vote, and plan the days on a map.\n"
    "\n"
    "Privacy: I only store links, the places found in them, votes and plans. "
    "All other messages are ignored. Use /forget to delete a trip's data."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to /start with the welcome + privacy notice."""
    # effective_message works for normal chats, groups and edited messages.
    await update.effective_message.reply_text(WELCOME_TEXT)
