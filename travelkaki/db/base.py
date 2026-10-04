"""Database setup: the engine (connection) and sessions (units of work).

We use plain, synchronous SQLAlchemy with SQLite. SQLite is a local file,
so calls are fast enough to run directly inside the bot's async handlers.
"""

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """Parent class for all tables (see models.py)."""


def make_engine(url: str) -> Engine:
    """Create the database engine for this URL.

    - "sqlite://" (no path) = in-memory DB, used by tests. StaticPool keeps one
      shared connection, otherwise each connection would see an empty DB.
    - "sqlite:///data/x.db" = a file. We create its folder if it is missing.
    """
    if url == "sqlite://":
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the bot may use the DB from helper threads too.
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url)


def make_sessions(engine: Engine) -> sessionmaker[Session]:
    """Factory for sessions. Use as: `with sessions() as s: ...`.

    expire_on_commit=False: objects stay readable after commit, so we can
    pass a saved Place to the bot code that builds the card.
    """
    return sessionmaker(engine, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create any missing tables, then add any missing columns.

    (No Alembic until we go public. db/migrate.py adds new nullable columns,
    so the live database keeps its data when a new version adds fields. M2.)
    """
    from travelkaki.db import models  # noqa: F401  (import registers the tables)
    from travelkaki.db.migrate import add_missing_columns

    Base.metadata.create_all(engine)
    add_missing_columns(engine)
