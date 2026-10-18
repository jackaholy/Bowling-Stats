import json
from pathlib import Path
from typing import Any

import pytest

from app.board import (
    BallReading,
    BoardReading,
    FrameReading,
    RowReading,
    draft_for_row,
    read_board,
)
from app.models import GameStatus, alias_key

FIXTURE = Path(__file__).parent / "fixtures" / "verified_games.json"


def row(
    name: str,
    frames: list[list[str | None]],
    totals: list[int | None],
    final: int | None = None,
    circled: frozenset[tuple[int, int]] = frozenset(),
) -> RowReading:
    return RowReading(
        name=name,
        frames=[
            FrameReading(
                balls=[BallReading(mark=m, circled=(i, b) in circled) for b, m in enumerate(f)],
                total=totals[i] if i < len(totals) else None,
            )
            for i, f in enumerate(frames)
        ],
        final_total=final if final is not None else (totals[-1] if totals else None),
    )


def board(*rows: RowReading) -> BoardReading:
    return BoardReading(rows=list(rows), notes="")


def frames_of(text: str) -> list[list[str | None]]:
    return [[None if c == "?" else c for c in frame] for frame in text.split()]


NINES = "9- 9- 9- 9- 9- 9- 9- 9- 9- 9-"
NINES_TOTALS: list[int | None] = [9 * n for n in range(1, 11)]


def fixture_games() -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = json.loads(FIXTURE.read_text())["games"]
    return games


@pytest.mark.parametrize("game", fixture_games(), ids=lambda game: game["photo"])
def test_fixture_rows_verify(game: dict[str, Any]) -> None:
    reading = board(
        row("Someone Else", frames_of(NINES), NINES_TOTALS),
        row(game["name_on_board"], game["frames"], game["printed_cumulative"], game["total"]),
    )
    draft = read_board(reading, {alias_key(game["name_on_board"])})
    assert draft.review_reasons == []
    assert draft.status is GameStatus.VERIFIED
    assert draft.row_index == 1
    assert draft.frames == game["frames"]


def test_alias_match_ignores_case_and_spaces() -> None:
    draft = read_board(board(row(" JACK ", frames_of(NINES), NINES_TOTALS)), {"jack"})
    assert draft.status is GameStatus.VERIFIED
    assert draft.name_on_board == " JACK "


def test_no_matching_row_goes_to_review() -> None:
    draft = read_board(board(row("Usa", frames_of(NINES), NINES_TOTALS)), {"jack"})
    assert draft.status is GameStatus.NEEDS_REVIEW
    assert draft.frames is None
    assert "Usa" in draft.review_reasons[0]


def test_several_matching_rows_go_to_review() -> None:
    reading = board(
        row("Jack", frames_of(NINES), NINES_TOTALS), row("jack", frames_of(NINES), NINES_TOTALS)
    )
    draft = read_board(reading, {"jack"})
    assert draft.status is GameStatus.NEEDS_REVIEW
    assert draft.row_index is None
    assert "several rows" in draft.review_reasons[0]


def test_user_picked_row_is_verified() -> None:
    reading = board(row("Gack", frames_of(NINES), NINES_TOTALS))
    assert draft_for_row(reading, 0).status is GameStatus.VERIFIED


@pytest.mark.parametrize(
    ("printed", "roll"),
    [("·", "-"), ("•", "-"), (".", "-"), ("0", "-"), ("G", "-"), ("–", "-"), ("x", "X")],
)
def test_marks_are_normalized(printed: str, roll: str) -> None:
    frames = frames_of(NINES)
    frames[0] = [printed] if roll == "X" else [printed, "9"]
    draft = draft_for_row(board(row("A", frames, [])), 0)
    assert draft.frames is not None
    assert draft.frames[0][0] == roll


def test_foul_counts_as_miss_with_flag() -> None:
    frames = frames_of(NINES)
    frames[2] = ["F", "9"]
    draft = draft_for_row(board(row("A", frames, NINES_TOTALS)), 0)
    assert draft.status is GameStatus.VERIFIED
    assert draft.frames is not None and draft.frames[2] == ["-", "9"]
    assert draft.marks == [{"frame": 2, "ball": 0, "kind": "foul"}]


def test_circled_digits_are_splits() -> None:
    frames = frames_of(NINES)
    frames[4] = ["⑧", "1"]
    frames[5] = ["8", "1"]
    reading = board(row("A", frames, NINES_TOTALS, circled=frozenset({(5, 0)})))
    draft = draft_for_row(reading, 0)
    assert draft.status is GameStatus.VERIFIED
    assert draft.frames is not None and draft.frames[4] == ["8", "1"]
    assert draft.marks == [
        {"frame": 4, "ball": 0, "kind": "split"},
        {"frame": 5, "ball": 0, "kind": "split"},
    ]


def test_unrecognized_mark_is_null_and_flagged() -> None:
    frames = frames_of(NINES)
    frames[1] = ["Q", "-"]
    draft = draft_for_row(board(row("A", frames, NINES_TOTALS)), 0)
    assert draft.status is GameStatus.NEEDS_REVIEW
    assert draft.frames is not None and draft.frames[1] == [None, "-"]
    assert "frame 2 ball 1: unrecognized mark 'Q'" in draft.review_reasons


def test_running_total_mismatch() -> None:
    totals = list(NINES_TOTALS)
    totals[3] = 37
    draft = draft_for_row(board(row("A", frames_of(NINES), totals, final=90)), 0)
    assert draft.status is GameStatus.NEEDS_REVIEW
    assert draft.review_reasons == ["frame 4: board shows 37, rolls give 36"]


def test_final_total_mismatch() -> None:
    draft = draft_for_row(board(row("A", frames_of(NINES), NINES_TOTALS, final=91)), 0)
    assert draft.review_reasons == ["final total: board shows 91, rolls give 90"]


def test_unreadable_printed_totals() -> None:
    totals = list(NINES_TOTALS)
    totals[6] = None
    reading = BoardReading(rows=[row("A", frames_of(NINES), totals)], notes="")
    reading.rows[0].final_total = None
    draft = draft_for_row(reading, 0)
    assert draft.review_reasons == [
        "frame 7: running total not readable",
        "final total not readable",
    ]


def test_unfinished_game_goes_to_review() -> None:
    frames = frames_of(NINES)[:6] + [[], [], [], []]
    draft = draft_for_row(board(row("A", frames, NINES_TOTALS[:6])), 0)
    assert draft.status is GameStatus.NEEDS_REVIEW
    assert draft.review_reasons == ["the game looks unfinished (some frames have no balls)"]


def test_invalid_rolls_go_to_review() -> None:
    frames = frames_of(NINES)
    frames[0] = ["6", "5"]
    draft = draft_for_row(board(row("A", frames, NINES_TOTALS)), 0)
    assert draft.status is GameStatus.NEEDS_REVIEW
    assert draft.review_reasons[0].startswith("the rolls don't form a valid game")


def test_unreadable_roll_that_affects_score_goes_to_review() -> None:
    frames = frames_of(NINES)
    frames[0] = ["9", None]
    draft = draft_for_row(board(row("A", frames, NINES_TOTALS)), 0)
    assert draft.review_reasons == ["an unreadable roll affects the score"]


def test_unreadable_first_ball_of_spare_still_verifies() -> None:
    frames = frames_of(NINES)
    frames[0] = [None, "/"]
    totals: list[int | None] = [19, *(19 + 9 * n for n in range(1, 10))]
    draft = draft_for_row(board(row("A", frames, totals)), 0)
    assert draft.status is GameStatus.VERIFIED
    assert draft.frames is not None and draft.frames[0] == [None, "/"]
