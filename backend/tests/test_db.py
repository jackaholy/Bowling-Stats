from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlmodel import Session, SQLModel, select

from app.db import make_engine
from app.models import Alias, Extraction, Game, GameStatus, Photo, alias_key

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


def alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    engine = make_engine(db_url)
    yield engine
    engine.dispose()


def add_photo(session: Session, sha256: str = "abc") -> Photo:
    photo = Photo(sha256=sha256, original_name="IMG_1.HEIC", stored_path="photos/abc.jpg")
    session.add(photo)
    session.commit()
    return photo


def test_migrations_match_models(engine: Engine) -> None:
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), SQLModel.metadata) == []


def test_downgrade_removes_every_table(db_url: str, engine: Engine) -> None:
    command.downgrade(alembic_config(db_url), "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]


def test_game_round_trip(engine: Engine) -> None:
    captured = datetime(2024, 8, 26, 21, 14, 5)
    with Session(engine) as session:
        photo = add_photo(session)
        photo.captured_at = captured
        assert photo.id is not None
        extraction = Extraction(photo_id=photo.id, model="claude-test", raw_response='{"rows": []}')
        session.add(extraction)
        session.commit()
        session.add(
            Game(
                photo_id=photo.id,
                extraction_id=extraction.id,
                status=GameStatus.NEEDS_REVIEW,
                played_on=date(2024, 8, 26),
                name_on_board="Holy",
                frames=[["9", "/"], ["X"], [None, "/"]],
                marks=[{"frame": 0, "ball": 0, "kind": "split"}],
                printed_cumulative=[20, None],
                printed_total=201,
                review_reasons=["printed total mismatch"],
            )
        )
        session.commit()

    with Session(engine) as session:
        game = session.exec(select(Game)).one()
        assert game.status is GameStatus.NEEDS_REVIEW
        assert game.frames == [["9", "/"], ["X"], [None, "/"]]
        assert game.marks == [{"frame": 0, "ball": 0, "kind": "split"}]
        assert game.printed_cumulative == [20, None]
        assert game.review_reasons == ["printed total mismatch"]
        assert game.played_on == date(2024, 8, 26)
        assert game.created_at.tzinfo is UTC
        photo = session.exec(select(Photo)).one()
        assert photo.captured_at == captured
        assert photo.captured_at.tzinfo is None
        stored = session.exec(text("SELECT status FROM game")).scalar_one()  # type: ignore[call-overload]
        assert stored == "needs_review"


def test_manual_game_needs_no_photo(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(Game(status=GameStatus.MANUAL, played_on=date(2026, 1, 2), frames=[["X"]]))
        session.commit()
        assert session.exec(select(Game)).one().photo_id is None


def test_duplicate_photo_hash_is_rejected(engine: Engine) -> None:
    with Session(engine) as session:
        add_photo(session, "same")
        with pytest.raises(IntegrityError):
            add_photo(session, "same")


def test_one_game_per_photo(engine: Engine) -> None:
    with Session(engine) as session:
        photo = add_photo(session)
        session.add(Game(photo_id=photo.id))
        session.commit()
        session.add(Game(photo_id=photo.id))
        with pytest.raises(IntegrityError):
            session.commit()


def test_foreign_keys_are_enforced(engine: Engine) -> None:
    with Session(engine) as session:
        session.add(Game(photo_id=999))
        with pytest.raises(IntegrityError):
            session.commit()


def test_aliases_match_case_insensitively(engine: Engine) -> None:
    assert alias_key("  JACK ") == alias_key("jack") == "jack"
    with Session(engine) as session:
        session.add(Alias.of(" Jack "))
        session.commit()
        alias = session.exec(select(Alias)).one()
        assert (alias.name, alias.key) == ("Jack", "jack")
        session.add(Alias.of("JACK"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_naive_timestamps_are_refused_for_our_own_columns(engine: Engine) -> None:
    with Session(engine) as session:
        naive = datetime(2026, 1, 1)
        session.add(Photo(sha256="n", original_name="a", stored_path="b", imported_at=naive))
        with pytest.raises(StatementError):
            session.commit()
