"""Alembic environment. The URL comes from `sqlalchemy.url` if a caller sets it (tests do),
else from app.config. Batch mode lets SQLite alter tables by copying them."""

from alembic import context
from sqlmodel import SQLModel

import app.models  # noqa: F401  (registers the tables on SQLModel.metadata)
from app.config import database_url
from app.db import make_engine

config = context.config
url = config.get_main_option("sqlalchemy.url") or database_url()
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with make_engine(url).connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
