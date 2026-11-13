from datetime import date
from pathlib import Path

import anthropic
import httpx2
from conftest import FakeAnthropic, api_message, make_jpeg
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.board import BallReading, BoardReading, FrameReading, RowReading
from app.games import ordered_games, rematch_unmatched
from app.importer import (
    import_photo,
    read_photo,
    should_stop_importing,
    stage_photo,
    stored_jpeg,
)
from app.models import Alias, Extraction, Game, GameStatus

NINES: list[list[str | None]] = [["9", "-"]] * 10
NINES_TOTALS: list[int | None] = [9 * n for n in range(1, 11)]


def reading(name: str = "Jack", frames: list[list[str | None]] = NINES) -> BoardReading:
    rows = [
        RowReading(
            name=n,
            frames=[
                FrameReading(
                    balls=[BallReading(mark=m, circled=False) for m in f], total=NINES_TOTALS[i]
                )
                for i, f in enumerate(frames)
            ],
            final_total=90,
        )
        for n in (name, "Usa")
    ]
    return BoardReading(rows=rows, notes="")


def fake(*replies: BoardReading | dict[str, object] | Exception) -> anthropic.Anthropic:
    client: anthropic.Anthropic = FakeAnthropic(*replies)  # type: ignore[assignment]
    return client


def api_error() -> anthropic.APIError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(request=request)


def add_alias(session: Session, name: str = "Jack") -> None:
    session.add(Alias.of(name))
    session.commit()


def test_import_verifies_the_users_row(engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        add_alias(session)
        staged = import_photo(
            session, make_jpeg(taken="2024:08:26 21:14:05"), "IMG_1.HEIC", tmp_path, fake(reading())
        )
        game = staged.game
        assert not staged.duplicate
        assert game.status is GameStatus.VERIFIED
        assert game.review_reasons == []
        assert game.name_on_board == "Jack"
        assert game.frames == NINES
        assert game.played_on == date(2024, 8, 26)
        extraction = session.get(Extraction, game.extraction_id)
        assert extraction is not None and "Usa" in extraction.raw_response
        assert stored_jpeg(session, game, tmp_path)[:2] == b"\xff\xd8"  # a JPEG


def test_exact_duplicate_photo_is_skipped_without_calling_claude(
    engine: Engine, tmp_path: Path
) -> None:
    client = FakeAnthropic(reading())
    photo = make_jpeg(taken="2024:08:26 21:14:05")
    with Session(engine) as session:
        first = import_photo(session, photo, "a.HEIC", tmp_path, client)  # type: ignore[arg-type]
        again = import_photo(session, photo, "b.HEIC", tmp_path, client)  # type: ignore[arg-type]
        assert again.duplicate
        assert again.game.id == first.game.id
        assert len(client.calls) == 1


def test_no_alias_match_then_rematch_after_adding_alias(engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        photo = make_jpeg(taken="2024:08:26 21:14:05")
        game = import_photo(session, photo, "a.HEIC", tmp_path, fake(reading("Gack"))).game
        assert game.status is GameStatus.NEEDS_REVIEW
        assert game.frames is None
        assert "Gack" in game.review_reasons[0]

        add_alias(session, "gack")
        assert [g.id for g in rematch_unmatched(session)] == [game.id]
        rematched = session.get(Game, game.id)
        assert rematched is not None and rematched.status is GameStatus.VERIFIED


def test_rematch_skips_boards_with_several_of_the_users_names(
    engine: Engine, tmp_path: Path
) -> None:
    with Session(engine) as session:
        photo = make_jpeg(taken="2024:08:26 21:14:05")
        game = import_photo(session, photo, "a", tmp_path, fake(reading("Holy"))).game
        assert game.status is GameStatus.NEEDS_REVIEW  # no aliases yet

        session.add_all([Alias.of("Holy"), Alias.of("Usa")])
        session.commit()
        assert [g.id for g in rematch_unmatched(session)] == [game.id]
        skipped = session.get(Game, game.id)
        assert skipped is not None and skipped.status is GameStatus.SKIPPED
        assert skipped.review_reasons == [
            "several rows match your names (Holy, Usa); skipped, enter it by hand"
        ]


def test_confirm_alias_sends_game_to_review(engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        session.add(Alias.of("Nick", confirm=True))
        session.commit()
        photo = make_jpeg(taken="2024:08:26 21:14:05")
        game = import_photo(session, photo, "a", tmp_path, fake(reading("Nick"))).game
        assert game.status is GameStatus.NEEDS_REVIEW
        assert game.frames == NINES
        assert "confirm it's you" in game.review_reasons[0]


def test_missing_capture_date_goes_to_review(engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        add_alias(session)
        game = import_photo(session, make_jpeg(), "a.png", tmp_path, fake(reading())).game
        assert game.status is GameStatus.NEEDS_REVIEW
        assert game.played_on is None
        assert game.review_reasons == ["the photo has no capture date; enter the date"]


def test_same_date_and_rolls_is_flagged_as_possible_duplicate(
    engine: Engine, tmp_path: Path
) -> None:
    with Session(engine) as session:
        add_alias(session)
        client = fake(reading())
        first = import_photo(
            session, make_jpeg((1, 2, 3), "2024:08:26 21:14:05"), "a", tmp_path, client
        ).game
        second = import_photo(
            session, make_jpeg((200, 2, 3), "2024:08:26 21:20:00"), "b", tmp_path, client
        ).game
        assert first.status is GameStatus.VERIFIED
        assert second.status is GameStatus.NEEDS_REVIEW
        assert second.review_reasons == [
            f"same date and rolls as game {first.id}; possibly the same game photographed twice"
        ]


def test_api_error_leaves_game_pending_for_retry(engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        add_alias(session)
        photo = make_jpeg(taken="2024:08:26 21:14:05")
        game = import_photo(session, photo, "a", tmp_path, fake(api_error())).game
        assert game.status is GameStatus.PENDING
        assert game.extraction_id is None
        assert "APIConnectionError" in game.review_reasons[0]


def status_error(cls: type[anthropic.APIStatusError], status: int, message: str) -> Exception:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx2.Response(status, request=request), body=None)


def test_import_stops_on_errors_every_photo_would_hit() -> None:
    credit = "Your credit balance is too low to access the Anthropic API."
    stops = [
        status_error(anthropic.BadRequestError, 400, credit),
        status_error(anthropic.AuthenticationError, 401, "invalid x-api-key"),
        status_error(anthropic.PermissionDeniedError, 403, "forbidden"),
        status_error(anthropic.APIStatusError, 402, "payment required"),
    ]
    keeps_going = [
        status_error(anthropic.BadRequestError, 400, "image could not be processed"),
        status_error(anthropic.InternalServerError, 500, "server error"),
        api_error(),
    ]
    assert all(should_stop_importing(e) for e in stops)  # type: ignore[arg-type]
    assert not any(should_stop_importing(e) for e in keeps_going)  # type: ignore[arg-type]


def test_refusal_is_stored_and_sent_to_review(engine: Engine, tmp_path: Path) -> None:
    refusal = api_message(
        [], "refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": None}
    )
    with Session(engine) as session:
        photo = make_jpeg(taken="2024:08:26 21:14:05")
        game = import_photo(session, photo, "a", tmp_path, fake(refusal)).game
        assert game.status is GameStatus.NEEDS_REVIEW
        assert "declined" in game.review_reasons[0]
        assert session.exec(select(Extraction)).one().photo_id == game.photo_id


def test_staging_and_reading_can_be_split(engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        staged = stage_photo(session, make_jpeg(taken="2024:08:26 21:14:05"), "a", tmp_path)
        assert staged.game.status is GameStatus.PENDING
        outcome = read_photo(staged.jpeg, fake(reading()))
        assert not isinstance(outcome, Exception)


def test_ordered_games_follow_the_editable_date(engine: Engine) -> None:
    with Session(engine) as session:
        late = Game(status=GameStatus.MANUAL, played_on=date(2025, 1, 1), frames=NINES)
        early = Game(status=GameStatus.MANUAL, played_on=date(2024, 1, 1), frames=NINES)
        session.add_all([late, early])
        session.commit()
        assert [g.id for g in ordered_games(session)] == [early.id, late.id]
        early.played_on = date(2026, 1, 1)
        session.commit()
        assert [g.id for g in ordered_games(session)] == [late.id, early.id]
