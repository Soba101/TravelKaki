"""A tiny migration step: add new columns to tables that already exist (M2 spec).

`create_all` only creates MISSING TABLES. It never changes a table that is
already in the live database. So when a new version adds a column, the old
DB would not have it and every query would crash.

This step compares each table with models.py and runs
`ALTER TABLE ... ADD COLUMN` for any missing column. That keeps all rows.
Only nullable columns can be added this way (old rows get NULL).
We still don't use Alembic; this is enough until we go public.
"""

from sqlalchemy import Engine, inspect, text

from travelkaki.db.base import Base


def add_missing_columns(engine: Engine) -> list[str]:
    """Add every column that models.py has but the DB table lacks.

    Returns the added columns as "table.column" (empty list = nothing to do).
    Raises RuntimeError for a missing NOT NULL column (old rows would break it).
    """
    found = inspect(engine)
    added = []
    for table in Base.metadata.sorted_tables:
        if not found.has_table(table.name):
            continue  # create_all makes brand-new tables; nothing to add here
        existing = {c["name"] for c in found.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            if not col.nullable:
                raise RuntimeError(f"can't add NOT NULL column {table.name}.{col.name}")
            col_type = col.type.compile(engine.dialect)
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}"))
            added.append(f"{table.name}.{col.name}")
    return added
