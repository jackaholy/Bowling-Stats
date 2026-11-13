"""Ignore spaces in alias keys

Recomputes alias.key with the new matching rule ("Jack 1" matches "Jack1"). If two aliases now
share a key, the oldest is kept (with `confirm` set if either had it) and the other removed.
The key rules are copied here so this migration never changes when app code does.

Revision ID: c2c0c9240ffb
Revises: 9a8ab3afdd81
Create Date: 2026-11-13 10:40:28.004886

"""
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c2c0c9240ffb'
down_revision: str | Sequence[str] | None = '9a8ab3afdd81'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rekey(key_of: Callable[[str], str]) -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, name, confirm FROM alias ORDER BY id")).all()
    kept: dict[str, tuple[int, bool]] = {}
    for alias_id, name, confirm in rows:
        key = key_of(name)
        if key in kept:
            first_id, first_confirm = kept[key]
            connection.execute(sa.text("DELETE FROM alias WHERE id = :id"), {"id": alias_id})
            if confirm and not first_confirm:
                connection.execute(
                    sa.text("UPDATE alias SET confirm = 1 WHERE id = :id"), {"id": first_id}
                )
            continue
        kept[key] = (alias_id, bool(confirm))
    # Two passes so a key that moves onto another row's old key never collides mid-update.
    for alias_id, _ in kept.values():
        connection.execute(
            sa.text("UPDATE alias SET key = :tmp WHERE id = :id"),
            {"tmp": f"__rekey_{alias_id}", "id": alias_id},
        )
    for key, (alias_id, _) in kept.items():
        connection.execute(
            sa.text("UPDATE alias SET key = :key WHERE id = :id"), {"key": key, "id": alias_id}
        )


def upgrade() -> None:
    _rekey(lambda name: "".join(name.split()).casefold())


def downgrade() -> None:
    _rekey(lambda name: name.strip().casefold())
