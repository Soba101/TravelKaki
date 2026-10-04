"""Turn any TikTok / Instagram link into one standard ("canonical") form (issue #9).

Why: the same video can be shared as many different URLs (short links,
tracking params like ?igsh=...). We store the canonical form, so posting
the same video twice is spotted as a duplicate.
"""

import re
from typing import Literal
from urllib.parse import urlparse

import httpx

Platform = Literal["tiktok", "instagram"]

# Post paths we understand. Anything else (profiles, YouTube, ...) is ignored.
# TikTok has video posts and photo (slideshow) posts.
_TIKTOK_PATH = re.compile(r"^/@([^/]+)/(video|photo)/(\d+)")
_IG_PATH = re.compile(r"^/(reel|reels|p)/([A-Za-z0-9_-]+)")

# Short links that only redirect to the real post.
_SHORT_HOSTS = {"vm.tiktok.com", "vt.tiktok.com"}


class LinkError(Exception):
    """A short link could not be opened (network error, timeout, ...)."""


def _with_scheme(url: str) -> str:
    """Telegram often sends links typed without https://. Add it so parsing works."""
    url = url.strip()
    return url if "://" in url else "https://" + url


def _host(url: str) -> str:
    """Host without "www." / "m.", lowercase. "" if the URL can't be parsed."""
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.").removeprefix("m.")


def canonical(url: str) -> tuple[str, Platform] | None:
    """Return (canonical URL, platform), or None if this isn't a TikTok/IG post.

    Pure function: no network. Query strings and #fragments are dropped.
    """
    url = _with_scheme(url)
    host, path = _host(url), urlparse(url).path
    if host == "tiktok.com" and (m := _TIKTOK_PATH.match(path)):
        return f"https://www.tiktok.com/@{m[1]}/{m[2]}/{m[3]}", "tiktok"
    if host == "instagram.com" and (m := _IG_PATH.match(path)):
        kind = "p" if m[1] == "p" else "reel"  # /reels/ and /reel/ are the same thing
        return f"https://www.instagram.com/{kind}/{m[2]}/", "instagram"
    return None


def needs_redirect(url: str) -> bool:
    """True for short/share links that must be opened to find the real post."""
    url = _with_scheme(url)
    host, path = _host(url), urlparse(url).path
    return (
        host in _SHORT_HOSTS
        or (host == "tiktok.com" and path.startswith("/t/"))
        or (host == "instagram.com" and path.startswith("/share/"))
    )


async def resolve(url: str, client: httpx.AsyncClient) -> str:
    """Follow redirects and return the final URL. Raises LinkError on failure."""
    try:
        response = await client.get(url, follow_redirects=True, timeout=10)
    except httpx.HTTPError as e:
        raise LinkError(str(e)) from e
    return str(response.url)


async def normalise(url: str, client: httpx.AsyncClient) -> tuple[str, Platform] | None:
    """Canonical (URL, platform) for any TikTok/IG link, short links included."""
    url = _with_scheme(url)
    if needs_redirect(url):
        url = await resolve(url, client)
    return canonical(url)
