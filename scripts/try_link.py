"""Try the ingest steps on one real link, without the bot.

    uv run python scripts/try_link.py <tiktok-or-ig-link> <city>

Prints the caption and the places the LLM found, as JSON. Uses your .env
settings (set OLLAMA_BASE_URL=http://localhost:11434 when running outside Docker).
"""

import asyncio
import json
import sys

import httpx

from travelkaki.config import Settings
from travelkaki.ingest.captions import fetch_caption
from travelkaki.ingest.extract import extract_places
from travelkaki.ingest.urls import normalise
from travelkaki.llm.client import LlmClient


async def main(url: str, city: str) -> None:
    settings = Settings(telegram_bot_token="unused:by-this-script")
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 (TravelKaki bot)"}) as http:
        found = await normalise(url, http)
        if found is None:
            sys.exit("Not a TikTok/Instagram post link.")
        canonical, platform = found
        caption = await fetch_caption(canonical, platform, http)
        if caption is None:
            sys.exit(f"No caption for {canonical} (blocked or empty).")
        places = await extract_places(LlmClient(settings), city, caption.text, on_call=lambda: None)
    result = {
        "url": canonical,
        "author": caption.author,
        "caption": caption.text,
        "places": [p.model_dump() for p in places],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
