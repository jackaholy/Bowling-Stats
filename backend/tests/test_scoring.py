import json
from pathlib import Path
from typing import Any

import pytest

from app.scoring import (
    Game,
    InvalidGameError,
    frame_scores,
    game_total,
    missing_rolls,
    to_pins,
    validate,
)

FIXTURE = Path(__file__).parent / "fixtures" / "verified_games.json"


def g(text: str) -> Game:
    """Build a game from compact text: frames split by spaces, "?" = unreadable roll."""
    return [[None if c == "?" else c for c in frame] for frame in text.split()]


def load_fixture() -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = json.loads(FIXTURE.read_text())["games"]
    return games


@pytest.mark.parametrize("game", load_fixture(), ids=lambda game: game["photo"])
def test_fixture_matches_printed_scoreboard(game: dict[str, Any]) -> None:
    assert frame_scores(game["frames"]) == game["printed_cumulative"]
    assert game_total(game["frames"]) == game["total"]


@pytest.mark.parametrize(
    ("text", "total"),
    [
        ("X X X X X X X X X XXX", 300),
        ("-- -- -- -- -- -- -- -- -- --", 0),
        ("9- 9- 9- 9- 9- 9- 9- 9- 9- 9-", 90),
        ("5/ 5/ 5/ 5/ 5/ 5/ 5/ 5/ 5/ 5/5", 150),
        ("X 5/ X 5/ X 5/ X 5/ X 5/X", 200),
        ("X X X X X X X X X X9/", 289),
        ("X X X X X X X X X 9/X", 279),
        ("X X X X X X X X X XX5", 295),
        ("X X X X X X X X X X81", 287),
        ("X X X X X X X X X XX9", 299),
        ("-- -- -- -- -- -- -- -- -- 9/7", 17),
        ("-- -- -- -- -- -- -- -- -- 72", 9),
        ("-/ -- -- -- -- -- -- -- -- --", 10),
        ("-- -- -- -- -- -- -- -- -- X-/", 20),
    ],
)
def test_game_totals(text: str, total: int) -> None:
    assert game_total(g(text)) == total


def test_running_totals() -> None:
    assert frame_scores(g("X 7/ 9- X -8 8/ -6 X X X81")) == [
        20, 39, 48, 66, 74, 84, 90, 120, 148, 167,
    ]


def test_to_pins() -> None:
    assert to_pins(g("X 7/ 9- -8 -/ 9- 9- 9- 9- X-/")) == [
        [10], [7, 3], [9, 0], [0, 8], [0, 10], [9, 0], [9, 0], [9, 0], [9, 0], [10, 0, 10],
    ]


@pytest.mark.parametrize(
    ("game", "frame_index"),
    [
        (g("X X X X X X X X X"), None),
        (g("X X X X X X X X X XXX X"), None),
        (g("/5 -- -- -- -- -- -- -- -- --"), 0),
        (g("-- 55 -- -- -- -- -- -- -- --"), 1),
        (g("-- 64 -- -- -- -- -- -- -- --"), 1),
        (g("-- -- 9X -- -- -- -- -- -- --"), 2),
        (g("-- -- -- X5 -- -- -- -- -- --"), 3),
        (g("-- -- -- -- 7 -- -- -- -- --"), 4),
        (g("-- -- -- -- -- 123 -- -- -- --"), 5),
        (g("-- -- -- -- -- -- 0- -- -- --"), 6),
        (g("-- -- -- -- -- -- -- -- -- /5"), 9),
        (g("-- -- -- -- -- -- -- -- -- X/"), 9),
        (g("-- -- -- -- -- -- -- -- -- 9X"), 9),
        (g("-- -- -- -- -- -- -- -- -- 55"), 9),
        (g("-- -- -- -- -- -- -- -- -- X"), 9),
        (g("-- -- -- -- -- -- -- -- -- X9/X"), 9),
        (g("-- -- -- -- -- -- -- -- -- 72X"), 9),
        (g("-- -- -- -- -- -- -- -- -- XX"), 9),
        (g("-- -- -- -- -- -- -- -- -- 9/"), 9),
        (g("-- -- -- -- -- -- -- -- -- XX/"), 9),
        (g("-- -- -- -- -- -- -- -- -- 9//"), 9),
        (g("-- -- -- -- -- -- -- -- -- X55"), 9),
        (g("-- -- -- -- -- -- -- -- -- X9X"), 9),
    ],
)
def test_invalid_notation_raises(game: Game, frame_index: int | None) -> None:
    with pytest.raises(InvalidGameError) as exc:
        validate(game)
    assert exc.value.frame_index == frame_index


def test_scoring_validates_first() -> None:
    with pytest.raises(InvalidGameError):
        frame_scores(g("-- 55 -- -- -- -- -- -- -- --"))


def test_null_roll_nulls_its_frame_and_all_later_frames() -> None:
    assert frame_scores(g("9- 9- 9? 9- 9- 9- 9- 9- 9- 9-")) == [9, 18] + [None] * 8


def test_null_bonus_roll_nulls_the_frame_that_borrows_it() -> None:
    assert frame_scores(g("X ?- 9- 9- 9- 9- 9- 9- 9- 9-")) == [None] * 10


def test_null_after_spare_nulls_the_spare_frame() -> None:
    assert frame_scores(g("9- 5/ ?- 9- 9- 9- 9- 9- 9- 9-")) == [9] + [None] * 9


def test_null_first_ball_of_a_spare_still_scores() -> None:
    assert frame_scores(g("?/ 5- 9- 9- 9- 9- 9- 9- 9- 9-")) == [15, 20] + [
        20 + 9 * n for n in range(1, 9)
    ]
    assert frame_scores(g("X ?/ 9- 9- 9- 9- 9- 9- 9- 9-"))[:3] == [20, 39, 48]
    assert game_total(g("-- -- -- -- -- -- -- -- -- ?/5")) == 15
    assert game_total(g("-- -- -- -- -- -- -- -- -- X?/")) == 20
    assert game_total(g("-- -- -- -- -- -- -- -- X ?/5")) == 35
    # Frame 9's strike counts X and the null ball but not the "/", so it is truly unknown.
    assert game_total(g("-- -- -- -- -- -- -- -- X X?/")) is None


def test_missing_rolls_lists_every_null_even_when_scorable() -> None:
    assert missing_rolls(g("?/ 5- 9- 9- 9- 9- 9- 9- 9- X?/")) == [(0, 0), (9, 1)]
    assert missing_rolls(g("X X X X X X X X X XXX")) == []


def test_null_fill_ball_nulls_only_frame_ten() -> None:
    first_nine = [9 * n for n in range(1, 10)]
    assert frame_scores(g("9- 9- 9- 9- 9- 9- 9- 9- 9- 9/?")) == first_nine + [None]
    assert game_total(g("9- 9- 9- 9- 9- 9- 9- 9- 9- XX?")) is None


@pytest.mark.parametrize(
    "text",
    [
        "? -- -- -- -- -- -- -- -- --",
        "?? -- -- -- -- -- -- -- -- --",
        "?/ -- -- -- -- -- -- -- -- --",
        "-- -- -- -- -- -- -- -- -- ?X",
        "-- -- -- -- -- -- -- -- -- ?XX",
        "-- -- -- -- -- -- -- -- -- ?5",
        "-- -- -- -- -- -- -- -- -- ?53",
        "-- -- -- -- -- -- -- -- -- 5?",
        "-- -- -- -- -- -- -- -- -- 5?3",
        "-- -- -- -- -- -- -- -- -- X?X",
        "-- -- -- -- -- -- -- -- -- X?/",
    ],
)
def test_checks_that_need_a_null_roll_are_skipped(text: str) -> None:
    validate(g(text))


def test_null_rolls_still_fail_checks_that_dont_need_them() -> None:
    with pytest.raises(InvalidGameError):
        validate(g("/? -- -- -- -- -- -- -- -- --"))
    with pytest.raises(InvalidGameError):
        validate(g("?X -- -- -- -- -- -- -- -- --"))
    with pytest.raises(InvalidGameError):
        validate(g("-- -- -- -- -- -- -- -- -- ?/"))
