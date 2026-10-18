"""Extraction accuracy on the fixture photos. Calls the Claude API (costs money); not in pytest.

    cd backend && .venv/bin/python scripts/eval_extraction.py [--model M] [--photos IMG_1 IMG_2]
    cd backend && .venv/bin/python scripts/eval_extraction.py --rescore ../data/eval/<run>   # free

Each raw API response is saved under data/eval/<run>/ (gitignored), so normalization and
verification changes can be re-scored with --rescore without calling the API again.

The headline number is "verified but wrong": games that pass every printed-total check but
whose rolls differ from the hand-verified fixture. Those would reach stats unnoticed.
"""

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from anthropic.types.beta import BetaMessage

from app.board import BoardReading, GameDraft, draft_for_row, read_board
from app.config import DATA_DIR, extraction_model
from app.extraction import ExtractionError, extract_board
from app.models import GameStatus, alias_key
from app.photos import prepare_photo

FIXTURE = Path(__file__).parents[1] / "tests" / "fixtures" / "verified_games.json"
PRICES_PER_MTOK = {  # (input, output) USD
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


@dataclass
class Result:
    photo: str
    expected_name: str
    error: str | None = None
    picked_name: str | None = None
    status: GameStatus | None = None
    reasons: list[str] | None = None
    balls_right: int = 0
    balls_total: int = 0
    totals_right: int = 0
    frame_diffs: list[str] | None = None
    served_by: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0

    @property
    def rolls_exact(self) -> bool:
        return self.error is None and self.balls_right == self.balls_total and not self.frame_diffs

    @property
    def verified_but_wrong(self) -> bool:
        return self.status is GameStatus.VERIFIED and not self.rolls_exact


def score(game: dict[str, Any], reading: BoardReading, alias_keys: set[str]) -> Result:
    result = Result(photo=game["photo"], expected_name=game["name_on_board"])
    draft = read_board(reading, alias_keys)
    result.picked_name, result.status, result.reasons = (
        draft.name_on_board,
        draft.status,
        draft.review_reasons,
    )
    # Score the right row's rolls even if alias matching didn't pick it.
    expected_key = alias_key(game["name_on_board"])
    right = next((i for i, r in enumerate(reading.rows) if alias_key(r.name) == expected_key), None)
    if right is None:
        result.frame_diffs = [f"no row named {game['name_on_board']!r} was read"]
        return result
    compare(game, draft if draft.row_index == right else draft_for_row(reading, right), result)
    return result


def compare(game: dict[str, Any], draft: GameDraft, result: Result) -> None:
    expected: list[list[str]] = game["frames"]
    got = draft.frames or []
    result.frame_diffs = []
    for i, want in enumerate(expected):
        have = got[i] if i < len(got) else []
        result.balls_total += len(want)
        if len(have) == len(want):
            result.balls_right += sum(a == b for a, b in zip(want, have, strict=True))
        if have != want:
            result.frame_diffs.append(f"frame {i + 1}: read {fmt(have)}, expected {fmt(want)}")
    printed = draft.printed_cumulative or []
    result.totals_right = sum(
        a == b for a, b in zip(game["printed_cumulative"], printed, strict=False)
    )


def fmt(frame: Sequence[str | None]) -> str:
    return " ".join("?" if r is None else r for r in frame) or "(empty)"


def reading_from_raw(raw: str) -> BoardReading:
    message = BetaMessage.model_validate_json(raw)
    text = next(b.text for b in message.content if b.type == "text")
    return BoardReading.model_validate_json(text)


def run_live(game: dict[str, Any], model: str, out: Path, alias_keys: set[str]) -> Result:
    photo = DATA_DIR / f"{game['photo']}.HEIC"
    started = time.perf_counter()
    try:
        extraction = extract_board(prepare_photo(photo.read_bytes()).jpeg, model=model)
    except ExtractionError as error:
        if error.raw_response:
            (out / f"{game['photo']}.json").write_text(error.raw_response)
        return Result(game["photo"], game["name_on_board"], error=str(error))
    (out / f"{game['photo']}.json").write_text(extraction.raw_response)
    result = score(game, extraction.reading, alias_keys)
    result.served_by = extraction.model
    result.input_tokens, result.output_tokens = extraction.input_tokens, extraction.output_tokens
    result.seconds = time.perf_counter() - started
    return result


def run_saved(game: dict[str, Any], run_dir: Path, alias_keys: set[str]) -> Result:
    path = run_dir / f"{game['photo']}.json"
    if not path.exists():
        return Result(game["photo"], game["name_on_board"], error="no saved response")
    raw = path.read_text()
    try:
        reading = reading_from_raw(raw)
    except Exception as error:  # noqa: BLE001 - report any unusable saved response
        return Result(game["photo"], game["name_on_board"], error=f"unusable response: {error}")
    result = score(game, reading, alias_keys)
    message = BetaMessage.model_validate_json(raw)
    result.served_by = message.model
    result.input_tokens = message.usage.input_tokens
    result.output_tokens = message.usage.output_tokens
    return result


def report(results: list[Result], model: str) -> None:
    for r in results:
        if r.error:
            print(f"{r.photo}  ERROR  {r.error}")
            continue
        picked = "row OK" if r.picked_name and r.picked_name.strip() == r.expected_name else (
            f"row {r.picked_name!r}"
        )
        status = r.status.value if r.status else "-"
        flag = "  <-- VERIFIED BUT WRONG" if r.verified_but_wrong else ""
        print(
            f"{r.photo}  {status:<12} {picked:<12} balls {r.balls_right}/{r.balls_total}"
            f"  totals {r.totals_right}/10  {r.seconds:5.1f}s{flag}"
        )
        for diff in r.frame_diffs or []:
            print(f"    {diff}")
        for reason in r.reasons or []:
            print(f"    review: {reason}")

    ok = [r for r in results if not r.error]
    balls = sum(r.balls_right for r in ok), sum(r.balls_total for r in ok)
    tokens_in, tokens_out = sum(r.input_tokens for r in ok), sum(r.output_tokens for r in ok)
    print()
    print(f"model                 {model}")
    print(f"games with exact rolls {sum(r.rolls_exact for r in ok)}/{len(results)}")
    print(f"balls read correctly  {balls[0]}/{balls[1]}")
    verified = sum(r.status is GameStatus.VERIFIED for r in ok)
    print(f"verified              {verified}/{len(results)}")
    print(f"VERIFIED BUT WRONG    {sum(r.verified_but_wrong for r in ok)}")
    print(f"errors                {len(results) - len(ok)}")
    print(f"tokens                {tokens_in} in / {tokens_out} out")
    if model in PRICES_PER_MTOK:
        price_in, price_out = PRICES_PER_MTOK[model]
        cost = (tokens_in * price_in + tokens_out * price_out) / 1_000_000
        print(f"cost                  ${cost:.3f} (${cost / max(len(ok), 1):.3f} per photo)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", default=extraction_model())
    parser.add_argument("--photos", nargs="*", help="photo IDs (default: all fixture photos)")
    parser.add_argument("--rescore", type=Path, help="re-score a saved run without calling the API")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    games: list[dict[str, Any]] = json.loads(FIXTURE.read_text())["games"]
    if args.photos:
        games = [g for g in games if g["photo"] in set(args.photos)]
    alias_keys = {alias_key(g["name_on_board"]) for g in games}

    task: Callable[[dict[str, Any]], Result]
    if args.rescore:
        task = lambda game: run_saved(game, args.rescore, alias_keys)  # noqa: E731
        print(f"re-scoring {args.rescore}\n")
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = DATA_DIR / "eval" / f"{stamp}-{args.model}"
        out.mkdir(parents=True)
        task = lambda game: run_live(game, args.model, out, alias_keys)  # noqa: E731
        print(f"calling {args.model} on {len(games)} photos; raw responses -> {out}\n")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(task, games))
    report(results, args.model)
    sys.exit(0)


if __name__ == "__main__":
    main()
