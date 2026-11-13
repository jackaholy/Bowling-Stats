"""Request and response shapes for the HTTP API. Scores are computed here, never stored."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models import GameStatus

Rolls = list[list[str | None]]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Mark(BaseModel):
    frame: int
    ball: int
    kind: Literal["foul", "split"]


class GameOut(BaseModel):
    id: int
    status: GameStatus
    played_on: date | None
    captured_at: datetime | None  # EXIF capture time, no time zone
    photo_id: int | None
    photo_name: str | None
    name_on_board: str | None
    frames: Rolls | None
    marks: list[Mark]
    printed_cumulative: list[int | None] | None
    printed_total: int | None
    scores: list[int | None] | None  # running totals computed from the rolls
    total: int | None
    missing_rolls: list[tuple[int, int]]  # (frame, ball) of each unreadable roll
    review_reasons: list[str]


class BoardRow(BaseModel):
    index: int
    name: str
    final_total: int | None
    matches_alias: bool


class GameDetail(GameOut):
    rows: list[BoardRow]  # every row Claude read on the photo, to pick from
    notes: str | None  # Claude's notes on what made the photo hard to read


class ImportOut(BaseModel):
    game: GameDetail
    duplicate: bool  # the same photo was already imported


class GameEdit(_In):
    """Only the fields sent are changed. Photo games are re-verified afterwards."""

    frames: Rolls | None = None
    marks: list[Mark] | None = None
    played_on: date | None = None
    printed_cumulative: list[int | None] | None = None
    printed_total: int | None = None


class PickRow(_In):
    row_index: int
    save_alias: bool = False


class ManualGameIn(_In):
    played_on: date
    frames: Rolls
    marks: list[Mark] = []


class AliasIn(_In):
    name: str
    confirm: bool = False


class AliasEdit(_In):
    confirm: bool


class AliasOut(BaseModel):
    id: int
    name: str
    confirm: bool


class TrendPoint(BaseModel):
    game_id: int
    played_on: date | None
    total: int
    rolling_average: float


class StatsOut(BaseModel):
    games_played: int
    average: float | None
    high: int | None
    low: int | None
    strikes: int
    strike_chances: int
    strike_rate: float | None
    spares: int
    spare_chances: int
    spare_rate: float | None
    open_frames: int
    frames: int
    open_rate: float | None
    trend: list[TrendPoint]
