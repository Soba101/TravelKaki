"""Tests for fetching a post's caption (issue #10). No real network."""

import httpx

from travelkaki.ingest import captions
from travelkaki.ingest.captions import Caption, fetch_caption

TIKTOK = "https://www.tiktok.com/@foodie/video/123"
IG = "https://www.instagram.com/reel/Cabc/"


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_tiktok_caption_from_oembed():
    def handler(request):
        assert request.url.path == "/oembed"
        assert request.url.params["url"] == TIKTOK
        return httpx.Response(200, json={"title": "Ichiran 🍜", "author_name": "foodie"})

    async with _client(handler) as client:
        assert await fetch_caption(TIKTOK, "tiktok", client) == Caption("Ichiran 🍜", "foodie")


async def test_tiktok_error_or_empty_gives_none():
    async with _client(lambda r: httpx.Response(404)) as client:
        assert await fetch_caption(TIKTOK, "tiktok", client) is None
    async with _client(lambda r: httpx.Response(200, json={"title": "  "})) as client:
        assert await fetch_caption(TIKTOK, "tiktok", client) is None


async def test_instagram_caption_from_ytdlp(monkeypatch):
    monkeypatch.setattr(captions, "_ytdlp_info", lambda url: {"description": "x", "uploader": "y"})
    assert await fetch_caption(IG, "instagram", client=None) == Caption("x", "y")


async def test_instagram_error_gives_none(monkeypatch):
    def boom(url):
        raise RuntimeError("login required")

    monkeypatch.setattr(captions, "_ytdlp_info", boom)
    assert await fetch_caption(IG, "instagram", client=None) is None
