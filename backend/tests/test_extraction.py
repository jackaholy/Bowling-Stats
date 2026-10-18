"""The API is faked: tests never call Claude or spend money."""

from typing import Any

import anthropic
import pytest
from anthropic.types.beta import BetaMessage

from app.board import BoardReading
from app.extraction import BOARD_SCHEMA, ExtractionError, extract_board

READING = {"rows": [{"name": "Jack", "frames": [], "final_total": None}], "notes": ""}


class FakeMessages:
    def __init__(self, message: dict[str, Any]) -> None:
        self.message = message
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> BetaMessage:
        self.calls.append(kwargs)
        return BetaMessage.model_validate(self.message)


class FakeClient:
    def __init__(self, message: dict[str, Any]) -> None:
        self.messages = FakeMessages(message)
        self.beta = self


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


def run(message: dict[str, Any]) -> tuple[Any, FakeClient]:
    client = FakeClient(message)
    fake: anthropic.Anthropic = client  # type: ignore[assignment]
    return extract_board(b"jpeg-bytes", client=fake, model="claude-opus-5-5"), client


def test_reading_is_parsed_and_raw_response_kept() -> None:
    text = BoardReading.model_validate(READING).model_dump_json()
    extraction, client = run(api_message([{"type": "text", "text": text}]))
    assert extraction.reading.rows[0].name == "Jack"
    assert extraction.model == "claude-opus-5-5"
    assert (extraction.input_tokens, extraction.output_tokens) == (1500, 800)
    assert '"msg_1"' in extraction.raw_response

    call = client.messages.calls[0]
    assert call["fallbacks"] == "default"
    assert call["output_config"]["format"]["schema"] == BOARD_SCHEMA
    image = call["messages"][0]["content"][0]
    assert image["source"]["media_type"] == "image/jpeg"
    assert image["source"]["data"] == "anBlZy1ieXRlcw=="  # base64 of b"jpeg-bytes"


def test_refusal_raises_with_raw_response() -> None:
    message = api_message(
        [], "refusal", stop_details={"type": "refusal", "category": "cyber", "explanation": None}
    )
    with pytest.raises(ExtractionError, match="declined") as error:
        run(message)
    assert error.value.raw_response is not None


def test_truncated_response_raises() -> None:
    with pytest.raises(ExtractionError, match="max_tokens"):
        run(api_message([{"type": "text", "text": '{"rows": ['}], "max_tokens"))


def test_schema_mismatch_raises() -> None:
    with pytest.raises(ExtractionError, match="schema"):
        run(api_message([{"type": "text", "text": '{"rows": "nope", "notes": ""}'}]))


def test_every_schema_object_forbids_extra_fields() -> None:
    objects = [BOARD_SCHEMA, *BOARD_SCHEMA["$defs"].values()]
    assert all(obj["additionalProperties"] is False for obj in objects)
