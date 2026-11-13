"""Import pipeline: photo bytes -> stored photo, Claude's reading, and a verified or flagged game.

Three steps so many photos can be read in parallel while only one thread writes the database:
`stage_photo` (database), `read_photo` (API only, thread-safe), `apply_reading` (database).
"""

from dataclasses import dataclass
from pathlib import Path

import anthropic
from sqlmodel import Session, select

from app.board import read_board
from app.config import extraction_model
from app.extraction import Extraction as ClaudeReading
from app.extraction import ExtractionError, extract_board
from app.games import alias_keys, apply_draft, confirm_keys
from app.models import Extraction, Game, GameStatus, Photo
from app.photos import file_sha256, prepare_photo

PHOTO_DIR = "photos"  # under the data dir; JPEGs are named by the original file's hash

ReadOutcome = ClaudeReading | ExtractionError | anthropic.APIError


@dataclass(frozen=True)
class Staged:
    game: Game
    jpeg: bytes  # empty for a duplicate
    duplicate: bool


def stage_photo(session: Session, data: bytes, original_name: str, data_dir: Path) -> Staged:
    """Skip exact duplicates; otherwise save the API-ready JPEG and create a pending game.

    Raises PhotoError if the file isn't a readable image.
    """
    sha256 = file_sha256(data)
    photo = session.exec(select(Photo).where(Photo.sha256 == sha256)).first()
    if photo is not None:
        game = session.exec(select(Game).where(Game.photo_id == photo.id)).one()
        return Staged(game, b"", duplicate=True)

    prepared = prepare_photo(data)
    stored_path = f"{PHOTO_DIR}/{sha256}.jpg"
    (data_dir / PHOTO_DIR).mkdir(parents=True, exist_ok=True)
    (data_dir / stored_path).write_bytes(prepared.jpeg)
    photo = Photo(
        sha256=sha256,
        original_name=original_name,
        stored_path=stored_path,
        captured_at=prepared.captured_at,
    )
    session.add(photo)
    session.flush()
    game = Game(
        photo_id=photo.id,
        played_on=prepared.captured_at.date() if prepared.captured_at else None,
    )
    session.add(game)
    session.commit()
    session.refresh(game)
    return Staged(game, prepared.jpeg, duplicate=False)


def read_photo(jpeg: bytes, client: anthropic.Anthropic | None = None) -> ReadOutcome:
    """Call Claude. Touches no database, so it's safe to run in worker threads."""
    try:
        return extract_board(jpeg, client)
    except (ExtractionError, anthropic.APIError) as error:
        return error


def should_stop_importing(error: anthropic.APIError) -> bool:
    """Errors that will hit every remaining photo too: out of credit, or a bad/blocked API key.
    (Rate limits and server errors are already retried by the SDK.)"""
    if isinstance(error, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        return True
    if isinstance(error, anthropic.APIStatusError) and error.status_code == 402:
        return True
    message = str(error).lower()
    return isinstance(error, anthropic.BadRequestError) and (
        "credit" in message or "billing" in message
    )


def apply_reading(session: Session, game: Game, outcome: ReadOutcome) -> None:
    """Store Claude's reading (kept forever) and verify the game against the board."""
    assert game.photo_id is not None, "only photo games are read by Claude"
    if isinstance(outcome, anthropic.APIError):
        # Nothing was read: the game stays pending so it can be retried.
        game.status = GameStatus.PENDING
        game.review_reasons = [f"Claude API error ({type(outcome).__name__}); try again"]
    elif isinstance(outcome, ExtractionError):
        if outcome.raw_response:
            session.add(
                Extraction(
                    photo_id=game.photo_id,
                    model=extraction_model(),
                    raw_response=outcome.raw_response,
                )
            )
        game.status = GameStatus.NEEDS_REVIEW
        game.review_reasons = [f"Claude couldn't read the photo: {outcome}"]
    else:
        extraction = Extraction(
            photo_id=game.photo_id, model=outcome.model, raw_response=outcome.raw_response
        )
        session.add(extraction)
        session.flush()
        game.extraction_id = extraction.id
        draft = read_board(outcome.reading, alias_keys(session), confirm_keys(session))
        apply_draft(session, game, draft)
    session.add(game)
    session.commit()
    session.refresh(game)


def stored_jpeg(session: Session, game: Game, data_dir: Path) -> bytes:
    """The saved JPEG for a photo game, to retry reading it."""
    photo = session.get(Photo, game.photo_id)
    if photo is None:
        raise ValueError(f"game {game.id} has no photo")
    return (data_dir / photo.stored_path).read_bytes()


def import_photo(
    session: Session,
    data: bytes,
    original_name: str,
    data_dir: Path,
    client: anthropic.Anthropic | None = None,
) -> Staged:
    """All three steps for one photo. Duplicates are returned without calling Claude."""
    staged = stage_photo(session, data, original_name, data_dir)
    if not staged.duplicate:
        apply_reading(session, staged.game, read_photo(staged.jpeg, client))
    return staged
