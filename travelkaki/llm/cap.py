"""Daily cap on LLM calls per trip (issue #11).

Stops a busy (or buggy) chat from running up a cloud LLM bill.
Every try counts: retries and fallback calls too.
"""

from collections.abc import Callable
from datetime import date

from sqlalchemy.orm import Session, sessionmaker

from travelkaki.db.models import LlmUsage


class CapReached(Exception):
    """This trip has used all its LLM calls for today."""


def make_counter(
    sessions: sessionmaker[Session],
    trip_id: int,
    cap: int,
    today: Callable[[], date] = date.today,
) -> Callable[[], None]:
    """Return a function to call before each LLM request.

    It adds 1 to today's count for this trip, or raises CapReached
    (without counting) when the cap is already used up.
    """

    def count() -> None:
        with sessions() as s:
            usage = s.get(LlmUsage, (trip_id, today())) or LlmUsage(
                trip_id=trip_id, day=today(), calls=0
            )
            if usage.calls >= cap:
                raise CapReached()
            usage.calls += 1
            s.add(usage)
            s.commit()

    return count
