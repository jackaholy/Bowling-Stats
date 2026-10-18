"""Database tables. Scores and stats are never stored: they are computed from `Game.frames`.

JSON columns aren't change-tracked in place: assign a new list instead of mutating one.
Our own timestamps are aware UTC (SQLModel requires it); EXIF capture times are naive.
"""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from pydantic import NaiveDatetime
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


def alias_key(name: str) -> str:
    """How names on the board are matched against aliases: trimmed, case-insensitive."""
    return name.strip().casefold()


class GameStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"
    SKIPPED = "skipped"
    MANUAL = "manual"


class Alias(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    key: str = Field(unique=True)

    @classmethod
    def of(cls, name: str) -> "Alias":
        return cls(name=name.strip(), key=alias_key(name))


class Photo(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    sha256: str = Field(unique=True)  # of the original file, to skip exact duplicates
    original_name: str
    stored_path: str  # relative to DATA_DIR
    captured_at: NaiveDatetime | None = None  # EXIF capture time, which has no time zone
    imported_at: datetime = Field(default_factory=utc_now)


class Extraction(SQLModel, table=True):
    """One Claude reading of a photo, kept forever so the original reading is never lost."""

    id: int | None = Field(default=None, primary_key=True)
    photo_id: int = Field(foreign_key="photo.id", index=True)
    model: str
    raw_response: str  # exactly as returned, all players' rows
    created_at: datetime = Field(default_factory=utc_now)


class Game(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    photo_id: int | None = Field(default=None, foreign_key="photo.id", unique=True)  # None: manual
    extraction_id: int | None = Field(default=None, foreign_key="extraction.id")
    status: GameStatus = Field(
        default=GameStatus.PENDING,
        sa_type=sa.Enum(
            GameStatus,
            values_callable=lambda statuses: [s.value for s in statuses],
            native_enum=False,
            length=20,
        ),
    )
    played_on: date | None = None  # editable; starts as the photo's capture date
    name_on_board: str | None = None
    frames: list[list[str | None]] | None = Field(default=None, sa_type=sa.JSON)
    marks: list[dict[str, Any]] = Field(default_factory=list, sa_type=sa.JSON)  # foul/split
    printed_cumulative: list[int | None] | None = Field(default=None, sa_type=sa.JSON)
    printed_total: int | None = None
    review_reasons: list[str] = Field(default_factory=list, sa_type=sa.JSON)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now, sa_column_kwargs={"onupdate": utc_now})
