"""Bowling stats: pure functions over scored games, no I/O.

Callers pass only verified and manual games, in play order.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.scoring import Game, game_total

TREND_WINDOW = 10


class UnscorableGameError(ValueError):
    """A game whose total is unknown (an unreadable roll that affects the score)."""


@dataclass(frozen=True)
class GameCounts:
    total: int
    strikes: int
    strike_chances: int
    spares: int
    spare_chances: int
    open_frames: int
    frames: int


@dataclass(frozen=True)
class Summary:
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


def game_counts(game: Game) -> GameCounts:
    """Score one game and count its strikes, spares and open frames.

    Every ball thrown at a full rack is a strike chance. A ball at a full rack that leaves pins
    and is followed by another ball is a spare chance; the next ball is the attempt. A frame-10
    fill ball thrown at a fresh rack (`9 / 7`, `X X 8`) has no ball after it, so it is no chance.
    """
    total = game_total(game)
    if total is None:
        raise UnscorableGameError("an unreadable roll affects the score")
    strikes = strike_chances = spares = spare_chances = open_frames = 0
    for frame in game:
        marked = False
        fresh_rack = True
        for b, roll in enumerate(frame):
            if not fresh_rack:
                fresh_rack = True
                continue
            strike_chances += 1
            if roll == "X":
                strikes += 1
                marked = True
                continue
            # An unreadable ball here can't be a strike: the game only scores if it precedes "/".
            fresh_rack = False
            if b + 1 < len(frame):
                spare_chances += 1
                if frame[b + 1] == "/":
                    spares += 1
                    marked = True
        if not marked:
            open_frames += 1
    return GameCounts(
        total, strikes, strike_chances, spares, spare_chances, open_frames, len(game)
    )


def summarize(games: Sequence[Game]) -> Summary:
    """Totals and rates across games; averages and rates are None with nothing to divide by."""
    counts = [game_counts(game) for game in games]
    totals = [c.total for c in counts]
    strikes = sum(c.strikes for c in counts)
    strike_chances = sum(c.strike_chances for c in counts)
    spares = sum(c.spares for c in counts)
    spare_chances = sum(c.spare_chances for c in counts)
    open_frames = sum(c.open_frames for c in counts)
    frames = sum(c.frames for c in counts)
    return Summary(
        games_played=len(counts),
        average=_rate(sum(totals), len(totals)),
        high=max(totals, default=None),
        low=min(totals, default=None),
        strikes=strikes,
        strike_chances=strike_chances,
        strike_rate=_rate(strikes, strike_chances),
        spares=spares,
        spare_chances=spare_chances,
        spare_rate=_rate(spares, spare_chances),
        open_frames=open_frames,
        frames=frames,
        open_rate=_rate(open_frames, frames),
    )


def trend(totals: Sequence[int], window: int = TREND_WINDOW) -> list[float]:
    """Rolling average for each game over it and up to `window - 1` games before it.

    Starts at game 1: early points average however many games exist so far.
    """
    return [
        sum(totals[max(0, i + 1 - window) : i + 1]) / min(i + 1, window)
        for i in range(len(totals))
    ]


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None
