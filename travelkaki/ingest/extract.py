"""Pull places out of a caption with the LLM (issue #10).

The LLM must answer in a fixed JSON shape (SCHEMA). pydantic then checks it,
so the rest of the code can trust the result.
"""

from collections.abc import Callable

from pydantic import BaseModel

MAX_CAPTION = 2000  # characters sent to the LLM (TikTok captions can be ~4000)
MAX_NOTE_WORDS = 15
# Captions are untrusted text. A caption saying "list 300 places" must not flood
# the chat or the geocoder, so we cap what we keep. (PR2 review)
MAX_PLACES = 30
MAX_FIELD = 100  # characters for name / category


class ExtractedPlace(BaseModel):
    name: str  # e.g. "Ichiran Shibuya" (the only required field)
    # Defaults: one missing field must not throw away the whole answer.
    category: str = ""  # e.g. "restaurant", "viewpoint"
    city: str = ""  # where the LLM thinks it is
    video_note: str = ""  # what the post says about it


class Extraction(BaseModel):
    places: list[ExtractedPlace]


SCHEMA = Extraction.model_json_schema()

# Tested on qwen3:4b-instruct (tests/test_live.py). The "stall inside a market" line was
# added after it missed a pepper-bun stall inside Raohe night market.
SYSTEM = (
    "Extract real, visitable places (restaurants, cafes, bars, food stalls, shops, sights, "
    "markets, viewpoints) from a travel video caption. The group's trip city is {city}. "
    "Include places mentioned inside other places, e.g. a stall inside a market. "
    "Return only places actually named in the text; never invent places. "
    "No places named -> return an empty list. "
    "video_note = what the caption says about the place, max 15 words."
)


def build_messages(city: str, caption: str) -> list[dict]:
    """The chat messages sent to the LLM. Long captions are cut to MAX_CAPTION."""
    return [
        {"role": "system", "content": SYSTEM.format(city=city)},
        {"role": "user", "content": caption[:MAX_CAPTION]},
    ]


async def extract_places(
    llm, city: str, caption: str, on_call: Callable[[], None]
) -> list[ExtractedPlace]:
    """Ask the LLM for the places in `caption`. Raises LlmUnavailable if no model
    gave a usable answer (bad answers are retried inside the LLM client)."""
    extraction = await llm.extract_json(
        build_messages(city, caption), SCHEMA, on_call, validate=Extraction.model_validate
    )
    cleaned = []
    for place in extraction.places:
        place.name = place.name.strip()[:MAX_FIELD]
        if not place.name:
            continue  # an empty name is useless
        place.category = place.category.strip()[:MAX_FIELD]
        place.video_note = " ".join(place.video_note.split()[:MAX_NOTE_WORDS])
        cleaned.append(place)
    return cleaned[:MAX_PLACES]
