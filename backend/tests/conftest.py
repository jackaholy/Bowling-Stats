"""Shared fixtures and fakes. Tests never touch data/bowling.db or call the Claude API."""

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from anthropic.types.beta import BetaMessage
from PIL import Image
from sqlalchemy import Engine

from app.board import BoardReading
from app.db import make_engine

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
def alembic_cfg(db_url: str) -> Config:
    return alembic_config(db_url)


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    engine = make_engine(db_url)
    yield engine
    engine.dispose()


class FakeAnthropic:
    """Stands in for anthropic.Anthropic. Replies are used in order (the last one repeats): a
    BoardReading becomes a successful message, a dict is a raw message, an exception is raised."""

    def __init__(self, *replies: BoardReading | dict[str, Any] | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.beta = self
        self.messages = self

    def create(self, **kwargs: Any) -> BetaMessage:
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, BoardReading):
            reply = api_message([{"type": "text", "text": reply.model_dump_json()}])
        return BetaMessage.model_validate(reply)


def api_message(
    content: list[dict[str, Any]], stop_reason: str = "end_turn", **extra: Any
) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1500, "output_tokens": 800},
        **extra,
    }


def make_jpeg(color: tuple[int, int, int] = (200, 30, 30), taken: str | None = None) -> bytes:
    """A small synthetic photo; `taken` is an EXIF DateTimeOriginal like "2024:08:26 21:14:05"."""
    exif = Image.Exif()
    if taken is not None:
        exif.get_ifd(0x8769)[0x9003] = taken
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buffer, format="JPEG", exif=exif.tobytes())
    return buffer.getvalue()
