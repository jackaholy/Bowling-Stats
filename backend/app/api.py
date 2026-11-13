"""HTTP API under /api. Local-only, single user, no login. The frontend reaches it through the
Vite proxy, so there is no CORS. The Anthropic key never leaves the server."""

from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import anthropic
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import Engine
from sqlmodel import Session, select

from app.config import DATA_DIR
from app.db import make_engine
from app.games import (
    COUNTED,
    GameRuleError,
    alias_keys,
    check_manual_rolls,
    ordered_games,
    pick_row,
    reading_for,
    recheck,
    rematch_unmatched,
    skip,
    unskip,
)
from app.importer import apply_reading, import_photo, read_photo, stored_jpeg
from app.models import Alias, Game, GameStatus, Photo, alias_key
from app.photos import PhotoError
from app.schemas import (
    AliasEdit,
    AliasIn,
    AliasOut,
    BoardRow,
    GameDetail,
    GameEdit,
    GameOut,
    ImportOut,
    ManualGameIn,
    PickRow,
    StatsOut,
    TrendPoint,
)
from app.scoring import InvalidGameError, frame_scores, missing_rolls
from app.stats import summarize, trend

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def create_app(
    engine: Engine | None = None,
    data_dir: Path | None = None,
    client: anthropic.Anthropic | None = None,
) -> FastAPI:
    """Tests pass a temp engine, data dir and fake client; `app.main` uses the defaults."""
    app = FastAPI(title="Bowling Stats")
    app.state.engine = engine or make_engine()
    app.state.data_dir = data_dir or DATA_DIR
    app.state.client = client  # created on first use, so the app starts without an API key
    _add_routes(app)
    return app


def _session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def _client(request: Request) -> anthropic.Anthropic:
    if request.app.state.client is None:
        request.app.state.client = anthropic.Anthropic()
    client: anthropic.Anthropic = request.app.state.client
    return client


SessionDep = Annotated[Session, Depends(_session)]
ClientDep = Annotated[anthropic.Anthropic, Depends(_client)]


def _get_game(session: Session, game_id: int) -> Game:
    game = session.get(Game, game_id)
    if game is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no game {game_id}")
    return game


def _save(session: Session, game: Game) -> None:
    session.add(game)
    session.commit()
    session.refresh(game)


def _game_out(session: Session, game: Game) -> dict[str, Any]:
    assert game.id is not None
    photo = session.get(Photo, game.photo_id) if game.photo_id is not None else None
    scores: list[int | None] | None = None
    if game.frames is not None:
        try:
            scores = frame_scores(game.frames)
        except InvalidGameError:
            scores = None
    return {
        "id": game.id,
        "status": game.status,
        "played_on": game.played_on,
        "captured_at": photo.captured_at if photo else None,
        "photo_id": game.photo_id,
        "photo_name": photo.original_name if photo else None,
        "name_on_board": game.name_on_board,
        "frames": game.frames,
        "marks": game.marks,
        "printed_cumulative": game.printed_cumulative,
        "printed_total": game.printed_total,
        "scores": scores,
        "total": scores[-1] if scores else None,
        "missing_rolls": missing_rolls(game.frames) if game.frames is not None else [],
        "review_reasons": game.review_reasons,
    }


def _game_detail(session: Session, game: Game) -> GameDetail:
    reading = reading_for(session, game)
    keys = alias_keys(session)
    rows = [
        BoardRow(
            index=i,
            name=row.name,
            final_total=row.final_total,
            matches_alias=alias_key(row.name) in keys,
        )
        for i, row in enumerate(reading.rows if reading else [])
    ]
    return GameDetail(
        **_game_out(session, game), rows=rows, notes=reading.notes if reading else None
    )


def _add_routes(app: FastAPI) -> None:
    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """Nothing lives at the root: the frontend is served by Vite. Show the API docs."""
        return RedirectResponse("/docs")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # --- photos -------------------------------------------------------------------------------

    @app.post("/api/photos")
    def upload_photo(
        request: Request,
        session: SessionDep,
        client: ClientDep,
        file: Annotated[UploadFile, File()],
    ) -> ImportOut:
        """Import one photo. Calls Claude unless it's an exact duplicate (~10 s, ~$0.05)."""
        data = file.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "photo is over 50 MB")
        try:
            staged = import_photo(
                session, data, file.filename or "upload", request.app.state.data_dir, client
            )
        except PhotoError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
        return ImportOut(game=_game_detail(session, staged.game), duplicate=staged.duplicate)

    @app.get("/api/photos/{photo_id}/image")
    def photo_image(request: Request, session: SessionDep, photo_id: int) -> FileResponse:
        photo = session.get(Photo, photo_id)
        if photo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no photo {photo_id}")
        return FileResponse(request.app.state.data_dir / photo.stored_path, media_type="image/jpeg")

    # --- games --------------------------------------------------------------------------------

    @app.get("/api/games")
    def list_games(session: SessionDep, status: GameStatus | None = None) -> list[GameOut]:
        """All games in play order (date, then capture time), optionally of one status."""
        games = ordered_games(session, (status,) if status else None)
        return [GameOut(**_game_out(session, game)) for game in games]

    @app.get("/api/games/{game_id}")
    def get_game(session: SessionDep, game_id: int) -> GameDetail:
        return _game_detail(session, _get_game(session, game_id))

    @app.patch("/api/games/{game_id}")
    def edit_game(session: SessionDep, game_id: int, edit: GameEdit) -> GameDetail:
        """Change rolls, flags, date or printed totals. Claude's original reading is kept."""
        game = _get_game(session, game_id)
        fields = edit.model_fields_set
        if game.status is GameStatus.MANUAL and fields & {"printed_cumulative", "printed_total"}:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "manual games have no printed totals"
            )
        if "frames" in fields:
            if edit.frames is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "frames can't be null")
            if game.status is GameStatus.MANUAL:
                _check_manual(edit.frames)
            game.frames = edit.frames
        if "marks" in fields:
            game.marks = [mark.model_dump() for mark in edit.marks or []]
        if "played_on" in fields:
            if edit.played_on is None and game.status is GameStatus.MANUAL:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "manual games need a date"
                )
            game.played_on = edit.played_on
        if "printed_cumulative" in fields:
            game.printed_cumulative = edit.printed_cumulative
        if "printed_total" in fields:
            game.printed_total = edit.printed_total
        recheck(session, game)
        _save(session, game)
        return _game_detail(session, game)

    @app.post("/api/games/{game_id}/pick-row")
    def pick_game_row(session: SessionDep, game_id: int, pick: PickRow) -> GameDetail:
        """Use this row as the user's (confirms a match by a name a friend might use)."""
        game = _get_game(session, game_id)
        _apply_rule(lambda: pick_row(session, game, pick.row_index, pick.save_alias))
        _save(session, game)
        return _game_detail(session, game)

    @app.post("/api/games/{game_id}/skip")
    def skip_game(session: SessionDep, game_id: int) -> GameDetail:
        game = _get_game(session, game_id)
        _apply_rule(lambda: skip(game))
        _save(session, game)
        return _game_detail(session, game)

    @app.post("/api/games/{game_id}/unskip")
    def unskip_game(session: SessionDep, game_id: int) -> GameDetail:
        game = _get_game(session, game_id)
        unskip(session, game)
        _save(session, game)
        return _game_detail(session, game)

    @app.post("/api/games/{game_id}/retry")
    def retry_game(
        request: Request, session: SessionDep, client: ClientDep, game_id: int
    ) -> GameDetail:
        """Read the photo with Claude again (~$0.05). Replaces the rolls, keeps old readings."""
        game = _get_game(session, game_id)
        if game.photo_id is None or game.status in COUNTED:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "only unverified photo games can be read again"
            )
        jpeg = stored_jpeg(session, game, request.app.state.data_dir)
        apply_reading(session, game, read_photo(jpeg, client))
        return _game_detail(session, game)

    @app.post("/api/games", status_code=status.HTTP_201_CREATED)
    def add_manual_game(session: SessionDep, game_in: ManualGameIn) -> GameDetail:
        """Enter a game by hand (no photo). It counts towards stats right away."""
        _check_manual(game_in.frames)
        game = Game(
            status=GameStatus.MANUAL,
            played_on=game_in.played_on,
            frames=game_in.frames,
            marks=[mark.model_dump() for mark in game_in.marks],
        )
        _save(session, game)
        return _game_detail(session, game)

    @app.delete("/api/games/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_manual_game(session: SessionDep, game_id: int) -> Response:
        """Only hand-entered games can be deleted; photo games are skipped instead."""
        game = _get_game(session, game_id)
        if game.status is not GameStatus.MANUAL:
            raise HTTPException(status.HTTP_409_CONFLICT, "skip photo games instead of deleting")
        session.delete(game)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # --- aliases ------------------------------------------------------------------------------

    @app.post("/api/games/rematch")
    def rematch(session: SessionDep) -> list[GameOut]:
        """Re-match games with no row picked against the current aliases (free, no API calls).
        Returns the games that changed."""
        return [GameOut(**_game_out(session, game)) for game in rematch_unmatched(session)]

    @app.get("/api/aliases")
    def list_aliases(session: SessionDep) -> list[AliasOut]:
        aliases = sorted(session.exec(select(Alias)).all(), key=lambda a: a.name.casefold())
        return [AliasOut(id=a.id or 0, name=a.name, confirm=a.confirm) for a in aliases]

    @app.post("/api/aliases", status_code=status.HTTP_201_CREATED)
    def add_alias(session: SessionDep, alias_in: AliasIn) -> AliasOut:
        """Add a name. Games whose row wasn't found are re-matched for free by the import script."""
        if not alias_key(alias_in.name):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the name is empty")
        if alias_key(alias_in.name) in alias_keys(session):
            raise HTTPException(status.HTTP_409_CONFLICT, f"{alias_in.name!r} is already an alias")
        alias = Alias.of(alias_in.name, confirm=alias_in.confirm)
        session.add(alias)
        session.commit()
        session.refresh(alias)
        return AliasOut(id=alias.id or 0, name=alias.name, confirm=alias.confirm)

    @app.patch("/api/aliases/{alias_id}")
    def edit_alias(session: SessionDep, alias_id: int, edit: AliasEdit) -> AliasOut:
        alias = session.get(Alias, alias_id)
        if alias is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no alias {alias_id}")
        alias.confirm = edit.confirm
        session.add(alias)
        session.commit()
        return AliasOut(id=alias_id, name=alias.name, confirm=alias.confirm)

    @app.delete("/api/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_alias(session: SessionDep, alias_id: int) -> Response:
        alias = session.get(Alias, alias_id)
        if alias is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no alias {alias_id}")
        session.delete(alias)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # --- stats --------------------------------------------------------------------------------

    @app.get("/api/stats")
    def stats(session: SessionDep) -> StatsOut:
        """Stats over verified and manual games, in play order, with a 10-game rolling average."""
        games = [game for game in ordered_games(session, COUNTED) if game.frames is not None]
        summary = summarize([game.frames for game in games if game.frames is not None])
        totals = [frame_scores(game.frames)[-1] or 0 for game in games if game.frames is not None]
        points = [
            TrendPoint(
                game_id=game.id or 0, played_on=game.played_on, total=total, rolling_average=avg
            )
            for game, total, avg in zip(games, totals, trend(totals), strict=True)
        ]
        return StatsOut(**asdict(summary), trend=points)


def _check_manual(frames: list[list[str | None]]) -> None:
    try:
        check_manual_rolls(frames)
    except GameRuleError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


def _apply_rule(action: Any) -> None:
    try:
        action()
    except GameRuleError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
