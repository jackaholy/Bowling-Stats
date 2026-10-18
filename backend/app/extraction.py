"""One Claude API call per photo: transcribe every bowler row. The model only reads; code in
`board.py` normalizes, matches and verifies."""

import base64
from dataclasses import dataclass
from typing import Literal

import anthropic
from anthropic.types.beta import BetaMessageParam, BetaOutputConfigParam
from pydantic import ValidationError

from app.board import BoardReading
from app.config import extraction_model

EFFORT: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
MAX_TOKENS = 16000
BOARD_SCHEMA = BoardReading.model_json_schema()

SYSTEM_PROMPT = """\
You transcribe photos of bowling scoreboards. Report exactly what is printed. Do not compute, \
infer or correct anything: code checks your transcription against the printed totals.

- rows: every bowler row, top to bottom. Skip team-total rows (e.g. "9 Team") and header rows.
- name: the bowler name as printed.
- frames: one entry per frame column, 1 to 10, in order.
  - balls: the marks in that frame's ball boxes, left to right, using the printed character \
(X, /, a digit, -, ·, F, G, 0, ...). Frame 10 can have up to three balls. Leave balls empty for \
a frame that hasn't been bowled yet.
  - circled: true if the mark is drawn inside a circle (a split).
  - total: the running total printed for that frame, or null if it is blank.
- final_total: the number in the TOTAL column for the current game. Ignore other numbers such as \
series totals, ball speed, handicap or the game number.
- notes: briefly mention anything that made the photo hard to read, or "" if nothing did.

If a mark or number is unclear (glare, blur, cut off, ambiguous), use null instead of your best \
guess. A null is shown to the user to fix; a wrong guess may never be caught."""


class ExtractionError(RuntimeError):
    """The call returned no usable reading. `raw_response` is kept for debugging when present."""

    def __init__(self, message: str, raw_response: str | None = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response


@dataclass(frozen=True)
class Extraction:
    reading: BoardReading
    raw_response: str  # the full API message as JSON
    model: str  # the model that answered (differs from the request after a fallback)
    input_tokens: int
    output_tokens: int


def extract_board(
    jpeg: bytes, client: anthropic.Anthropic | None = None, model: str | None = None
) -> Extraction:
    client = client or anthropic.Anthropic()
    output_config: BetaOutputConfigParam = {
        "effort": EFFORT,
        "format": {"type": "json_schema", "schema": BOARD_SCHEMA},
    }
    user_message: BetaMessageParam = {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(jpeg).decode("ascii"),
                },
            },
            {"type": "text", "text": "Transcribe this scoreboard."},
        ],
    }
    message = client.beta.messages.create(
        model=model or extraction_model(),
        max_tokens=MAX_TOKENS,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # a false-positive safety refusal retries on another model
        system=SYSTEM_PROMPT,
        output_config=output_config,
        messages=[user_message],
    )
    raw = message.to_json()
    if message.stop_reason == "refusal":
        category = message.stop_details.category if message.stop_details else None
        raise ExtractionError(f"Claude declined to read the photo ({category})", raw)
    if message.stop_reason == "max_tokens":
        raise ExtractionError("the response was cut off at max_tokens", raw)
    text = next((block.text for block in message.content if block.type == "text"), None)
    if text is None:
        raise ExtractionError("the response had no text", raw)
    try:
        reading = BoardReading.model_validate_json(text)
    except ValidationError as error:
        raise ExtractionError(f"the response didn't match the schema: {error}", raw) from error
    return Extraction(
        reading=reading,
        raw_response=raw,
        model=message.model,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
    )
