"""What Claude reads off a scoreboard, and how code turns it into a verified game. Pure, no I/O.

Claude transcribes marks exactly as printed (`BoardReading`). Code normalizes them, finds the
user's row by alias, and checks the rolls against every printed total.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models import GameStatus, alias_key
from app.scoring import FRAMES, Game, InvalidGameError, frame_scores, validate


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # additionalProperties: false, required by the API


class BallReading(_Strict):
    mark: str | None  # exactly as printed; None if unreadable
    circled: bool  # drawn inside a circle (a split)


class FrameReading(_Strict):
    balls: list[BallReading]  # empty if the frame hasn't been bowled
    total: int | None  # running total printed under the frame; None if blank or unreadable


class RowReading(_Strict):
    name: str
    frames: list[FrameReading]
    final_total: int | None


class BoardReading(_Strict):
    rows: list[RowReading]
    notes: str  # anything that made the photo hard to read


@dataclass(frozen=True)
class GameDraft:
    """A game ready to store: `status` is verified only if every printed total matched."""

    status: GameStatus
    review_reasons: list[str]
    row_index: int | None = None
    name_on_board: str | None = None
    frames: Game | None = None
    marks: list[dict[str, Any]] = field(default_factory=list)
    printed_cumulative: list[int | None] | None = None
    printed_total: int | None = None


_STRIKES = {"X", "x"}
_MISSES = {"-", "–", "—", "·", "•", ".", "0", "G", "g"}
_FOULS = {"F", "f"}
_CIRCLED_DIGITS = {chr(0x2460 + n - 1): str(n) for n in range(1, 10)}  # ① .. ⑨
_DIGITS = {str(n) for n in range(1, 10)}


def matching_rows(reading: BoardReading, alias_keys: set[str]) -> list[int]:
    return [i for i, row in enumerate(reading.rows) if alias_key(row.name) in alias_keys]


def read_board(reading: BoardReading, alias_keys: set[str]) -> GameDraft:
    """Find the user's row by alias and verify it; zero or several matches go to review."""
    matches = matching_rows(reading, alias_keys)
    if len(matches) == 1:
        return draft_for_row(reading, matches[0])
    if not matches:
        names = ", ".join(row.name for row in reading.rows) or "none"
        reason = f"no row matches your names (rows on the board: {names})"
    else:
        names = ", ".join(reading.rows[i].name for i in matches)
        reason = f"several rows match your names: {names}"
    return GameDraft(status=GameStatus.NEEDS_REVIEW, review_reasons=[reason])


def draft_for_row(reading: BoardReading, row_index: int) -> GameDraft:
    """Normalize one row and verify it against the board's printed totals."""
    row = reading.rows[row_index]
    reasons: list[str] = []
    frames: Game = []
    marks: list[dict[str, Any]] = []
    for i, frame in enumerate(row.frames):
        rolls: list[str | None] = []
        for b, ball in enumerate(frame.balls):
            roll, kinds, problem = _normalize(ball)
            rolls.append(roll)
            marks.extend({"frame": i, "ball": b, "kind": kind} for kind in kinds)
            if problem:
                reasons.append(f"frame {i + 1} ball {b + 1}: {problem}")
        frames.append(rolls)
    printed = [frame.total for frame in row.frames]
    reasons += _verify(frames, printed, row.final_total)
    return GameDraft(
        status=GameStatus.NEEDS_REVIEW if reasons else GameStatus.VERIFIED,
        review_reasons=reasons,
        row_index=row_index,
        name_on_board=row.name,
        frames=frames,
        marks=marks,
        printed_cumulative=printed,
        printed_total=row.final_total,
    )


def _normalize(ball: BallReading) -> tuple[str | None, list[str], str | None]:
    """(roll, flag kinds, problem). Unknown marks become None plus a problem, never a guess."""
    if ball.mark is None:
        return None, [], None
    mark = ball.mark.strip()
    split = ball.circled
    if mark in _CIRCLED_DIGITS:
        mark, split = _CIRCLED_DIGITS[mark], True
    if mark in _STRIKES:
        return "X", [], None
    if mark == "/":
        return "/", [], None
    if mark in _MISSES:
        return "-", [], None
    if mark in _FOULS:
        return "-", ["foul"], None
    if mark in _DIGITS:
        return mark, ["split"] if split else [], None
    return None, [], f"unrecognized mark {ball.mark!r}"


def _verify(frames: Game, printed: list[int | None], final_total: int | None) -> list[str]:
    if len(frames) != FRAMES or any(not frame for frame in frames):
        return ["the game looks unfinished (some frames have no balls)"]
    try:
        validate(frames)
    except InvalidGameError as error:
        return [f"the rolls don't form a valid game ({error})"]
    scores = frame_scores(frames)
    if None in scores:
        return ["an unreadable roll affects the score"]
    reasons = []
    for i, (board, computed) in enumerate(zip(printed, scores, strict=True)):
        if board is None:
            reasons.append(f"frame {i + 1}: running total not readable")
        elif board != computed:
            reasons.append(f"frame {i + 1}: board shows {board}, rolls give {computed}")
    if final_total is None:
        reasons.append("final total not readable")
    elif final_total != scores[-1]:
        reasons.append(f"final total: board shows {final_total}, rolls give {scores[-1]}")
    return reasons
