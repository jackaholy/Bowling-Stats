"""Game rules that need the database: status checks, duplicates, ordering, and row matching."""

from sqlmodel import Session, col, select

from app.board import GameDraft, read_board
from app.extraction import reading_from_raw
from app.models import Alias, Extraction, Game, GameStatus, Photo

COUNTED = (GameStatus.VERIFIED, GameStatus.MANUAL)


def alias_keys(session: Session) -> set[str]:
    return set(session.exec(select(Alias.key)).all())


def confirm_keys(session: Session) -> frozenset[str]:
    """Aliases a friend might also use: games matched by them need the user to confirm."""
    return frozenset(session.exec(select(Alias.key).where(col(Alias.confirm))).all())


def apply_draft(session: Session, game: Game, draft: GameDraft) -> None:
    """Store a board reading on the game and set its status, including the database checks."""
    game.name_on_board = draft.name_on_board
    game.frames = draft.frames
    game.marks = draft.marks
    game.printed_cumulative = draft.printed_cumulative
    game.printed_total = draft.printed_total
    if draft.status is GameStatus.SKIPPED:
        game.review_reasons = draft.review_reasons
        game.status = GameStatus.SKIPPED
        return
    reasons = draft.review_reasons + database_checks(session, game)
    game.review_reasons = reasons
    game.status = GameStatus.NEEDS_REVIEW if reasons else GameStatus.VERIFIED


def database_checks(session: Session, game: Game) -> list[str]:
    reasons = []
    if game.played_on is None:
        reasons.append("the photo has no capture date; enter the date")
    duplicate = find_duplicate(session, game)
    if duplicate is not None:
        reasons.append(
            f"same date and rolls as game {duplicate.id}; possibly the same game photographed twice"
        )
    return reasons


def find_duplicate(session: Session, game: Game) -> Game | None:
    if game.played_on is None or game.frames is None:
        return None
    candidates = session.exec(
        select(Game).where(
            Game.played_on == game.played_on,
            Game.id != game.id,
            Game.status != GameStatus.SKIPPED,
        )
    )
    return next((other for other in candidates if other.frames == game.frames), None)


def rematch_unmatched(session: Session) -> list[Game]:
    """Re-run alias matching on games with no row picked yet, using the stored reading (free).
    Returns the games that changed: matched to a row, or skipped for matching several rows."""
    games = session.exec(
        select(Game).where(
            Game.status == GameStatus.NEEDS_REVIEW,
            col(Game.frames).is_(None),
            col(Game.extraction_id).is_not(None),
        )
    ).all()
    keys, confirm = alias_keys(session), confirm_keys(session)
    matched = []
    for game in games:
        extraction = session.get(Extraction, game.extraction_id)
        assert extraction is not None
        draft = read_board(reading_from_raw(extraction.raw_response), keys, confirm)
        if draft.frames is not None or draft.status is GameStatus.SKIPPED:
            apply_draft(session, game, draft)
            session.add(game)
            matched.append(game)
    session.commit()
    return matched


def ordered_games(session: Session, statuses: tuple[GameStatus, ...] | None = None) -> list[Game]:
    """Play order: editable date, then capture time on the same day, then game ID."""
    statement = select(Game).join(Photo, isouter=True)
    if statuses is not None:
        statement = statement.where(col(Game.status).in_(statuses))
    statement = statement.order_by(
        col(Game.played_on).is_(None),
        col(Game.played_on),
        col(Photo.captured_at).is_(None),
        col(Photo.captured_at),
        col(Game.id),
    )
    return list(session.exec(statement).all())
