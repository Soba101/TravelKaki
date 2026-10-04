"""Tests for pulling places out of a caption with the LLM (issue #10). Fake LLM only."""

from unittest.mock import Mock

import pytest

from travelkaki.ingest.extract import SCHEMA, build_messages, extract_places
from travelkaki.llm.client import LlmUnavailable


class FakeLlm:
    """Returns a fixed answer and remembers what it was asked."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    async def extract_json(self, messages, schema, on_call):
        on_call()
        self.calls.append((messages, schema))
        return self.answer


def test_build_messages_includes_city_and_cuts_long_captions():
    messages = build_messages("Tokyo", "a" * 5000)
    system, user = messages[0]["content"], messages[1]["content"]
    assert "Tokyo" in system
    assert len(user) == 2000  # very long captions are cut (Review Focus 5)


async def test_extract_places_trims_notes_and_drops_empty_names():
    note20 = " ".join(["word"] * 20)
    llm = FakeLlm(
        {
            "places": [
                {"name": "Ichiran", "category": "ramen", "city": "Tokyo", "video_note": note20},
                {
                    "name": "Shibuya Sky",
                    "category": "view",
                    "city": "Tokyo",
                    "video_note": "sunset",
                },
                {"name": "  ", "category": "x", "city": "Tokyo", "video_note": ""},
            ]
        }
    )
    on_call = Mock()
    places = await extract_places(llm, "Tokyo", "caption", on_call)

    assert [p.name for p in places] == ["Ichiran", "Shibuya Sky"]
    assert len(places[0].video_note.split()) == 15
    assert llm.calls[0][1] == SCHEMA
    on_call.assert_called_once()


async def test_extract_places_bad_shape_is_unavailable():
    with pytest.raises(LlmUnavailable):
        await extract_places(FakeLlm({"wrong": 1}), "Tokyo", "caption", Mock())
