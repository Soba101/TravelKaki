"""Tests for the 'is this person in the trip's group?' check (M3, #23)."""

from types import SimpleNamespace

from telegram.error import TelegramError

from travelkaki.web.members import MemberCheck


class FakeBot:
    """Stands in for telegram.Bot. Returns a fixed status and counts calls."""

    def __init__(self, status="member", is_member=True, fail=False):
        self.status, self.is_member, self.fail, self.calls = status, is_member, fail, 0

    async def get_chat_member(self, chat_id, user_id):
        self.calls += 1
        if self.fail:
            raise TelegramError("user not found")
        return SimpleNamespace(status=self.status, is_member=self.is_member)


async def test_member_and_admin_are_allowed():
    for status in ("member", "administrator", "creator"):
        assert await MemberCheck(FakeBot(status)).ok(-100, 42)


async def test_left_or_kicked_is_refused():
    for status in ("left", "kicked"):
        assert not await MemberCheck(FakeBot(status)).ok(-100, 42)


async def test_restricted_depends_on_is_member():
    assert await MemberCheck(FakeBot("restricted", is_member=True)).ok(-100, 42)
    assert not await MemberCheck(FakeBot("restricted", is_member=False)).ok(-100, 42)


async def test_telegram_error_means_no():
    assert not await MemberCheck(FakeBot(fail=True)).ok(-100, 42)


async def test_answer_is_cached_then_expires():
    bot, clock = FakeBot(), [0.0]
    check = MemberCheck(bot, clock=lambda: clock[0])
    await check.ok(-100, 42)
    await check.ok(-100, 42)
    assert bot.calls == 1  # second call came from the cache
    clock[0] = 601  # past the 10 min cache
    await check.ok(-100, 42)
    assert bot.calls == 2
