"""Pull places out of a caption with the LLM (issue #10).

The LLM must answer in a fixed JSON shape (SCHEMA). pydantic then checks it,
so the rest of the code can trust the result.
"""

from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from travelkaki.llm.client import LlmUnavailable

MAX_CAPTION = 2000  # characters sent to the LLM (TikTok captions can be ~4000)
MAX_NOTE_WORDS = 15


class ExtractedPlace(BaseModel):
    name: str  # e.g. "Ichiran Shibuya"
    category: str  # e.g. "restaurant", "viewpoint"
    city: str  # where the LLM thinks it is
    video_note: str  # what the post says about it


class Extraction(BaseModel):
    places: list[ExtractedPlace]


SCHEMA = Extraction.model_json_schema()

# Tested on qwen3:4b-instruct before M1 (3/3 places from a sample Tokyo caption).
SYSTEM = (
    "Extract real, visitable places (restaurants, cafes, bars, shops, sights, markets, "
    "viewpoints) from a travel video caption. The group's trip city is {city}. "
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
    """Ask the LLM for the places in `caption`. Raises LlmUnavailable on a bad answer."""
    raw = await llm.extract_json(build_messages(city, caption), SCHEMA, on_call)
    try:
        places = Extraction.model_validate(raw).places
    except ValidationError as e:
        raise LlmUnavailable("answer didn't match the schema") from e
    cleaned = []
    for place in places:
        place.name = place.name.strip()
        if not place.name:
            continue  # an empty name is useless
        place.video_note = " ".join(place.video_note.split()[:MAX_NOTE_WORDS])
        cleaned.append(place)
    return cleaned
