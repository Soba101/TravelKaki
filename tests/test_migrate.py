"""The tiny migration step: new nullable columns are added to an old DB (M2 spec)."""

from sqlalchemy import inspect, text

from travelkaki.db.base import init_db, make_engine
from travelkaki.db.migrate import add_missing_columns

# The M1 `trip` table, before M2 added hotel_lat / hotel_lng.
OLD_TRIP = """CREATE TABLE trip (
    id INTEGER PRIMARY KEY, chat_id BIGINT UNIQUE, city VARCHAR(100),
    city_lat FLOAT, city_lng FLOAT, start_date DATE, end_date DATE,
    hotel VARCHAR(200), created_at DATETIME)"""


def _old_db():
    engine = make_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text(OLD_TRIP))
        c.execute(text("INSERT INTO trip (id, chat_id, city) VALUES (1, 5, 'Tokyo')"))
    return engine


def test_adds_missing_columns_and_keeps_rows():
    engine = _old_db()
    init_db(engine)  # create_all skips the old table, then the migrate step adds columns
    cols = {c["name"] for c in inspect(engine).get_columns("trip")}
    assert {"hotel_lat", "hotel_lng"} <= cols
    with engine.connect() as c:
        assert c.execute(text("SELECT city FROM trip")).scalar() == "Tokyo"


def test_returns_what_it_added():
    engine = _old_db()
    from travelkaki.db import models  # noqa: F401
    from travelkaki.db.base import Base

    Base.metadata.create_all(engine)
    assert "trip.hotel_lat" in add_missing_columns(engine)


def test_second_run_adds_nothing():
    engine = _old_db()
    init_db(engine)
    assert add_missing_columns(engine) == []
