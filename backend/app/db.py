"""Database engine. The schema comes from Alembic migrations, never `create_all`."""

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event
from sqlmodel import create_engine

from app.config import database_url

_SQLITE_FILE_PREFIX = "sqlite:///"


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if url.startswith(_SQLITE_FILE_PREFIX):
        Path(url.removeprefix(_SQLITE_FILE_PREFIX)).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    # SQLite ignores foreign keys unless asked, per connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
