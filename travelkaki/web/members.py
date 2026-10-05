"""Is a Telegram user in the trip's group chat? (M3, #23)

A trip link can be forwarded to anyone. So a valid initData is not enough:
we also ask Telegram (getChatMember) if the user is in the group.
Answers are cached for 10 min, so one map visit = at most one Telegram call.
"""

import logging
import time
from collections.abc import Callable

from telegram.error import TelegramError

log = logging.getLogger(__name__)

CACHE_SECONDS = 600
IN_CHAT = ("creator", "administrator", "member")  # statuses that count as "in the group"


class MemberCheck:
    def __init__(self, bot, clock: Callable[[], float] = time.monotonic):
        self.bot = bot  # telegram.Bot (tests pass a fake)
        self.clock = clock  # tests pass a fake clock
        self.cache: dict[tuple[int, int], tuple[float, bool]] = {}  # key -> (time, answer)

    async def ok(self, chat_id: int, user_id: int) -> bool:
        key = (chat_id, user_id)
        hit = self.cache.get(key)
        if hit and self.clock() - hit[0] < CACHE_SECONDS:
            return hit[1]
        try:
            m = await self.bot.get_chat_member(chat_id, user_id)
        except TelegramError as e:
            # Unknown user, bot removed from the group, network hiccup: all mean "no".
            # Not cached (PR #55 review): a blip must not lock a member out for 10 min.
            log.info("getChatMember failed for chat %s: %s", chat_id, e)
            return False
        answer = self._in_chat(m)
        self.cache[key] = (self.clock(), answer)
        return answer

    @staticmethod
    def _in_chat(m) -> bool:
        # "restricted" users can still be in the group; Telegram says so with is_member.
        return m.status in IN_CHAT or (m.status == "restricted" and bool(m.is_member))
