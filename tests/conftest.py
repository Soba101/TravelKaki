"""Shared test fixtures.

`sessions` gives each test a fresh, empty in-memory SQLite database.
Nothing touches the real ./data folder.
"""

import pytest

from travelkaki.db.base import init_db, make_engine, make_sessions


@pytest.fixture
def sessions():
    engine = make_engine("sqlite://")  # "sqlite://" = in-memory database
    init_db(engine)
    return make_sessions(engine)
