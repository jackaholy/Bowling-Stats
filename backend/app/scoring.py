"""Bowling scoring engine: pure functions over roll notation, no I/O.

Notation: "X" strike, "/" spare, "-" miss, "1"-"9" pins, None unreadable.
Frames 1-9 have 1-2 entries; frame 10 has 2-3.
"""

Roll = str | None
Frame = list[Roll]
Game = list[Frame]
Pins = int | None

FRAMES = 10
PINS = 10
TENTH = FRAMES - 1

_COUNTS: dict[str, int] = {"-": 0, **{str(n): n for n in range(1, 10)}}
_SYMBOLS = {"X", "/", *_COUNTS}


class InvalidGameError(ValueError):
    """Notation that no real game could produce. `frame_index` is 0-based, or None for the game."""

    def __init__(self, frame_index: int | None, reason: str) -> None:
        self.frame_index = frame_index
        self.reason = reason
        where = "game" if frame_index is None else f"frame {frame_index + 1}"
        super().__init__(f"{where}: {reason}")


def validate(game: Game) -> None:
    """Raise InvalidGameError on bad notation. Checks that would need a null roll are skipped."""
    if len(game) != FRAMES:
        raise InvalidGameError(None, f"expected {FRAMES} frames, got {len(game)}")
    for i, frame in enumerate(game):
        for roll in frame:
            if roll is not None and roll not in _SYMBOLS:
                raise InvalidGameError(i, f"unknown symbol {roll!r}")
        if i < TENTH:
            _validate_frame(i, frame)
        else:
            _validate_tenth(frame)


def to_pins(game: Game) -> list[list[Pins]]:
    """Convert notation to pins knocked down per ball ("/" = 10 minus the previous ball)."""
    validate(game)
    return [_frame_pins(frame) for frame in game]


def frame_scores(game: Game) -> list[Pins]:
    """The 10 running totals as a scoreboard prints them; null from the first unscorable frame."""
    frames = to_pins(game)
    rolls = [roll for frame in game for roll in frame]
    balls = [pins for frame in frames for pins in frame]
    totals: list[Pins] = []
    running: Pins = 0
    start = 0
    for i, raw in enumerate(game):
        # A strike or spare counts its own balls plus the next one or two: three balls total.
        size = 3 if i < TENTH and (raw[0] == "X" or raw[-1] == "/") else len(raw)
        end = start + size
        score = _window_score(rolls[start:end], balls[start:end])
        running = None if running is None or score is None else running + score
        totals.append(running)
        start += len(raw)
    return totals


def game_total(game: Game) -> Pins:
    """The final score, or None if any frame can't be scored."""
    return frame_scores(game)[-1]


def missing_rolls(game: Game) -> list[tuple[int, int]]:
    """(frame_index, ball_index) of every unreadable roll, 0-based, including ones that
    don't affect the score (a null first ball before "/"), so the user can fill them in."""
    return [
        (i, b) for i, frame in enumerate(game) for b, roll in enumerate(frame) if roll is None
    ]


def _window_score(rolls: list[Roll], pins: list[Pins]) -> Pins:
    """Sum consecutive balls; a ball followed by "/" counts with it as 10, even if unreadable."""
    total = 0
    for k, roll in enumerate(rolls):
        if k + 1 < len(rolls) and rolls[k + 1] == "/":
            continue
        value = PINS if roll == "/" else pins[k]
        if value is None:
            return None
        total += value
    return total


def _validate_frame(i: int, frame: Frame) -> None:
    if len(frame) == 1:
        if frame[0] not in ("X", None):
            raise InvalidGameError(i, "only a strike ends a frame after one ball")
        return
    if len(frame) != 2:
        raise InvalidGameError(i, f"expected 1 or 2 balls, got {len(frame)}")
    first, second = frame
    if first == "X":
        raise InvalidGameError(i, "a strike ends the frame")
    if first == "/":
        raise InvalidGameError(i, "spare on the first ball")
    _check_second_ball(i, first, second)


def _validate_tenth(frame: Frame) -> None:
    if len(frame) not in (2, 3):
        raise InvalidGameError(TENTH, f"expected 2 or 3 balls, got {len(frame)}")
    first, second = frame[0], frame[1]
    if first == "/":
        raise InvalidGameError(TENTH, "spare on the first ball")

    # Whether the third (fill) ball was earned; None when a null roll hides it.
    earned: bool | None
    if first == "X":
        if second == "/":
            raise InvalidGameError(TENTH, "spare on the first ball of a fresh rack")
        earned = True
    elif first is None:
        earned = True if second == "/" else None
    else:
        _check_second_ball(TENTH, first, second)
        earned = None if second is None else second == "/"

    if earned is True and len(frame) == 2:
        raise InvalidGameError(TENTH, "missing the earned fill ball")
    if earned is False and len(frame) == 3:
        raise InvalidGameError(TENTH, "fill ball without a strike or spare")
    if len(frame) == 3:
        third = frame[2]
        if second in ("X", "/"):
            if third == "/":
                raise InvalidGameError(TENTH, "spare on the first ball of a fresh rack")
        elif first == "X" and second is not None:
            _check_second_ball(TENTH, second, third)


def _check_second_ball(i: int, first: Roll, second: Roll) -> None:
    """Check the second ball at a rack whose first ball was not a strike."""
    if second == "X":
        raise InvalidGameError(i, "strike on the second ball of a rack")
    if first is None or second is None or second == "/":
        return
    if _COUNTS[first] + _COUNTS[second] >= PINS:
        raise InvalidGameError(i, "two balls total 10 or more without a spare mark")


def _frame_pins(frame: Frame) -> list[Pins]:
    pins: list[Pins] = []
    fresh_rack = True
    rack_first: Pins = None
    for roll in frame:
        value: Pins
        if roll == "X":
            value = PINS
            fresh_rack = True
        elif roll == "/":
            value = None if rack_first is None else PINS - rack_first
            fresh_rack = True
        else:
            value = None if roll is None else _COUNTS[roll]
            if fresh_rack:
                rack_first = value
            fresh_rack = not fresh_rack
        pins.append(value)
    return pins
