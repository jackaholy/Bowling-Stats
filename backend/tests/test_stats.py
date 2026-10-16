import json
from pathlib import Path
from typing import Any

import pytest

from app.scoring import Game
from app.stats import GameCounts, UnscorableGameError, game_counts, summarize, trend

FIXTURE = Path(__file__).parent / "fixtures" / "verified_games.json"


def g(text: str) -> Game:
    """Build a game from compact text: frames split by spaces, "?" = unreadable roll."""
    return [[None if c == "?" else c for c in frame] for frame in text.split()]


def fixture_games() -> dict[str, Game]:
    games: list[dict[str, Any]] = json.loads(FIXTURE.read_text())["games"]
    return {game["photo"]: game["frames"] for game in games}


# Counted by hand from the scoreboards: (total, strikes, strike chances, spares, spare chances,
# open frames). Every game has 9 strike chances in frames 1-9 plus 1-2 in frame 10.
FIXTURE_COUNTS = {
    "IMG_4253": (140, 1, 11, 5, 9, 4),
    "IMG_6093": (115, 2, 10, 2, 8, 6),
    "IMG_7026": (149, 5, 11, 1, 6, 5),
    "IMG_0320": (121, 2, 11, 4, 9, 5),
    "IMG_0464": (201, 5, 10, 3, 5, 2),
    "IMG_1582": (140, 3, 11, 3, 7, 4),
    "IMG_3237": (115, 1, 10, 3, 9, 6),
    "IMG_4210": (136, 1, 11, 6, 9, 3),
    "IMG_4367": (137, 0, 11, 7, 10, 3),
    "IMG_4724": (133, 2, 10, 2, 8, 6),
}


@pytest.mark.parametrize("photo", FIXTURE_COUNTS)
def test_fixture_game_counts(photo: str) -> None:
    assert game_counts(fixture_games()[photo]) == GameCounts(*FIXTURE_COUNTS[photo], frames=10)


def test_fixture_summary() -> None:
    summary = summarize(list(fixture_games().values()))
    assert summary.games_played == 10
    assert summary.average == pytest.approx(138.7)
    assert (summary.high, summary.low) == (201, 115)
    assert (summary.strikes, summary.strike_chances) == (22, 106)
    assert summary.strike_rate == pytest.approx(22 / 106)
    assert (summary.spares, summary.spare_chances) == (36, 80)
    assert summary.spare_rate == pytest.approx(36 / 80)
    assert (summary.open_frames, summary.frames) == (44, 100)
    assert summary.open_rate == pytest.approx(0.44)


def test_fixture_trend_starts_at_game_one() -> None:
    totals = [game_counts(game).total for game in fixture_games().values()]
    assert trend(totals) == pytest.approx(
        [140, 127.5, 404 / 3, 131.25, 145.2, 866 / 6, 981 / 7, 139.625, 1254 / 9, 138.7]
    )


def test_trend_window_rolls() -> None:
    assert trend([100, 200, 300, 400, 500], window=3) == pytest.approx([100, 150, 200, 300, 400])
    assert trend([]) == []


@pytest.mark.parametrize(
    ("text", "counts"),
    [
        ("X X X X X X X X X XXX", (300, 12, 12, 0, 0, 0)),
        ("-- -- -- -- -- -- -- -- -- --", (0, 0, 10, 0, 10, 10)),
        ("5/ 5/ 5/ 5/ 5/ 5/ 5/ 5/ 5/ 5/5", (150, 0, 11, 10, 10, 0)),
        # Frame 10: the 8 after a strike is a spare chance; a last ball that leaves pins is not.
        ("-- -- -- -- -- -- -- -- -- X8/", (20, 1, 11, 1, 10, 9)),
        ("-- -- -- -- -- -- -- -- -- X81", (19, 1, 11, 0, 10, 9)),
        ("-- -- -- -- -- -- -- -- -- XX8", (28, 2, 12, 0, 9, 9)),
        ("-- -- -- -- -- -- -- -- -- 9/7", (17, 0, 11, 1, 10, 9)),
        # An unreadable first ball before "/" is a spare chance, not a strike.
        ("?/ -- -- -- -- -- -- -- -- X?/", (30, 1, 11, 2, 10, 8)),
    ],
)
def test_game_counts(text: str, counts: tuple[int, int, int, int, int, int]) -> None:
    assert game_counts(g(text)) == GameCounts(*counts, frames=10)


def test_unscorable_game_is_refused() -> None:
    with pytest.raises(UnscorableGameError):
        game_counts(g("9? -- -- -- -- -- -- -- -- --"))
    with pytest.raises(UnscorableGameError):
        summarize([g("9- -- -- -- -- -- -- -- -- --"), g("X ?- -- -- -- -- -- -- -- --")])


def test_summary_of_no_games() -> None:
    summary = summarize([])
    assert summary.games_played == 0
    assert summary.average is None
    assert summary.high is None and summary.low is None
    assert summary.strike_rate is None and summary.spare_rate is None and summary.open_rate is None
