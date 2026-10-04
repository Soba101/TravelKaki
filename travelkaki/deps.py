"""Everything the bot and pipeline need from the outside world, in one object.

Handlers read it from `context.bot_data["deps"]`. Tests build a Deps with
fakes (fake LLM, fake geocoder, in-memory DB), so no network is needed.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session, sessionmaker

from travelkaki.config import Settings
from travelkaki.db import queries
from travelkaki.db.base import init_db, make_engine, make_sessions


@dataclass
class Deps:
    sessions: sessionmaker[Session]  # database sessions
    http: httpx.AsyncClient | None = None  # shared HTTP client
    llm: object | None = None  # LlmClient (llm/client.py), from PR2
    geo: object | None = None  # Nominatim (geo/nominatim.py), from PR4
    # fetch_caption(url, platform, http) -> Caption | None (ingest/captions.py), from PR2
    fetch_caption: Callable | None = None
    daily_cap: int = 100  # max LLM calls per trip per day
    # (source_id, chat_id) of links cut off by the last restart; offered a Retry at startup.
    interrupted: list[tuple[int, int]] = field(default_factory=list)


def build_deps(settings: Settings) -> Deps:
    """Create the real dependencies: database (tables created) and HTTP client."""
    engine = make_engine(settings.database_url)
    init_db(engine)
    sessions = make_sessions(engine)
    with sessions() as s:
        interrupted = queries.mark_interrupted(s)
    return Deps(
        sessions=sessions,
        # A browser-like User-Agent: TikTok's oEmbed rejects some default client names.
        http=httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 (TravelKaki bot)"}),
        daily_cap=settings.llm_daily_cap,
        interrupted=interrupted,
    )


async def close_deps(deps: Deps) -> None:
    """Close open connections on shutdown."""
    if deps.http is not None:
        await deps.http.aclose()
