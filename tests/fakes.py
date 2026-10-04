"""Fakes shared by the pipeline and bot tests. No network, no real LLM."""

from travelkaki.db import queries
from travelkaki.deps import Deps
from travelkaki.ingest.captions import Caption
from travelkaki.llm.client import LlmUnavailable


class FakeLlm:
    """Acts like LlmClient.extract_json: counts the call, runs `validate`."""

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer, error, 0

    async def extract_json(self, messages, schema, on_call, validate=None):
        on_call()  # may raise CapReached, like the real client
        self.calls += 1
        if self.error:
            raise self.error
        try:
            return validate(self.answer) if validate else self.answer
        except Exception as e:
            raise LlmUnavailable() from e


def places_answer(*names):
    return {"places": [{"name": n, "category": "food", "city": "Tokyo"} for n in names]}


def caption_fetcher(text="caption", author="foodie"):
    """fetch_caption(url, platform, http) that returns a fixed caption (None if text is None)."""

    async def fetch(url, platform, http):
        return Caption(text, author) if text is not None else None

    return fetch


def make_deps(sessions, llm=None, fetch=None, daily_cap=100):
    return Deps(
        sessions=sessions, llm=llm, fetch_caption=fetch or caption_fetcher(), daily_cap=daily_cap
    )


def make_source(sessions, chat_id=1, url="https://www.tiktok.com/@a/video/1"):
    """A trip + one pending TikTok source. Returns (trip, source)."""
    with sessions() as s:
        trip = queries.upsert_trip(s, chat_id, "Tokyo", None, None, None)
        return trip, queries.add_source(s, trip.id, url, "tiktok", added_by=7)
