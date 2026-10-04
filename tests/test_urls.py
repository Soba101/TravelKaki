"""Tests for the URL normaliser (issue #9). No real network: httpx.MockTransport fakes it."""

import httpx
import pytest

from travelkaki.ingest.urls import LinkError, canonical, needs_redirect, normalise

VIDEO = "https://www.tiktok.com/@a.b/video/7312345678901234567"
REEL = "https://www.instagram.com/reel/C1a2B3c4D5e/"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (VIDEO + "?is_from_webapp=1&sender_device=pc", (VIDEO, "tiktok")),
        ("https://tiktok.com/@a.b/video/7312345678901234567/", (VIDEO, "tiktok")),
        ("https://m.tiktok.com/@a.b/video/7312345678901234567#x", (VIDEO, "tiktok")),
        ("https://www.instagram.com/reel/C1a2B3c4D5e/?igsh=abc", (REEL, "instagram")),
        ("https://instagram.com/reels/C1a2B3c4D5e", (REEL, "instagram")),
        (
            "https://www.instagram.com/p/aye83DjauH/",
            ("https://www.instagram.com/p/aye83DjauH/", "instagram"),
        ),
        ("https://www.youtube.com/watch?v=x", None),
        ("https://www.tiktok.com/@a.b", None),  # a profile, not a post
        ("not a url", None),
        # Telegram often sends links typed without https:// (PR1 review).
        ("tiktok.com/@a.b/video/7312345678901234567", (VIDEO, "tiktok")),
        ("www.instagram.com/reel/C1a2B3c4D5e/", (REEL, "instagram")),
        # TikTok photo posts (slideshows) are common for travel lists.
        (
            "https://www.tiktok.com/@a.b/photo/7312345678901234567?x=1",
            ("https://www.tiktok.com/@a.b/photo/7312345678901234567", "tiktok"),
        ),
    ],
)
def test_canonical(url, expected):
    assert canonical(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://vm.tiktok.com/ZMabc123/", True),
        ("https://vt.tiktok.com/ZSabc123/", True),
        ("vm.tiktok.com/ZMabc123/", True),
        ("https://www.tiktok.com/t/ZTabc/", True),
        ("https://www.instagram.com/share/reel/BAxyz/", True),
        (VIDEO, False),
    ],
)
def test_needs_redirect(url, expected):
    assert needs_redirect(url) is expected


async def test_normalise_follows_short_link():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "vm.tiktok.com":
            return httpx.Response(301, headers={"location": VIDEO + "?_r=1"})
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await normalise("https://vm.tiktok.com/ZMabc123/", client) == (VIDEO, "tiktok")


async def test_normalise_canonical_link_needs_no_network():
    def handler(request):  # any request would be a bug
        raise AssertionError("should not fetch")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await normalise(VIDEO, client) == (VIDEO, "tiktok")


async def test_normalise_network_error_raises_link_error():
    def handler(request):
        raise httpx.ConnectError("down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(LinkError):
            await normalise("https://vm.tiktok.com/ZMabc123/", client)


async def test_invalid_redirect_target_raises_link_error():
    def handler(request):
        raise httpx.InvalidURL("bad")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(LinkError):
            await normalise("https://vm.tiktok.com/ZMabc123/", client)
