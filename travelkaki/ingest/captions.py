"""Fetch a post's public caption (issue #10). Metadata only: no video download.

- TikTok: the official oEmbed endpoint (no key needed).
- Instagram: yt-dlp reads the post's metadata. Instagram sometimes blocks this
  (rate limits / login wall); then we return None and the bot asks the user
  to add the place by name.
"""

import asyncio
import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

OEMBED = "https://www.tiktok.com/oembed"


@dataclass
class Caption:
    text: str
    author: str | None  # the post's creator, e.g. "foodie"


def _ytdlp_info(url: str) -> dict:
    """Ask yt-dlp for the post's metadata (blocking call, run in a thread)."""
    from yt_dlp import YoutubeDL  # imported here: only needed for Instagram

    with YoutubeDL({"quiet": True, "skip_download": True, "no_warnings": True}) as ydl:
        return ydl.extract_info(url, download=False) or {}


def _caption(text: str | None, author: str | None) -> Caption | None:
    """None when there is no usable text."""
    text = (text or "").strip()
    return Caption(text, author) if text else None


async def fetch_caption(url: str, platform: str, client: httpx.AsyncClient) -> Caption | None:
    """The post's caption + author, or None if we couldn't get any text."""
    try:
        if platform == "tiktok":
            response = await client.get(OEMBED, params={"url": url}, timeout=10)
            response.raise_for_status()
            data = response.json()
            return _caption(data.get("title"), data.get("author_name"))
        info = await asyncio.to_thread(_ytdlp_info, url)  # don't block the bot
        return _caption(info.get("description"), info.get("uploader"))
    except Exception as e:  # noqa: BLE001 - any failure = "no caption", the bot says what to do
        log.warning("caption fetch failed (%s): %s", platform, type(e).__name__)
        return None
