"""Bulk-import scoreboard photos into data/bowling.db. Calls the Claude API (~$0.05 per new photo).

    cd backend && .venv/bin/python scripts/import_photos.py [FOLDER] [--alias NAME ...]
    cd backend && .venv/bin/python scripts/import_photos.py --rematch-only --alias "New Name"

FOLDER defaults to data/inbox. Photos already imported (same file hash) are skipped for free.
Games left pending by an earlier API error are retried. Games whose row didn't match an alias
are re-matched against the current aliases from their stored reading, without calling the API.
"""

import argparse
import re
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
from sqlalchemy import inspect
from sqlmodel import Session, select

from app.config import DATA_DIR
from app.db import make_engine
from app.extraction import Extraction as ClaudeReading
from app.extraction import reading_from_raw
from app.games import ordered_games, rematch_unmatched
from app.importer import (
    ReadOutcome,
    apply_reading,
    read_photo,
    should_stop_importing,
    stage_photo,
    stored_jpeg,
)
from app.models import Alias, Extraction, Game, GameStatus, Photo, alias_key
from app.photos import PhotoError, file_sha256

PHOTO_SUFFIXES = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
COST_PER_PHOTO = 0.05  # USD, measured on the fixture photos with claude-opus-5-5
PRICE_PER_MTOK = (4.0, 20.0)  # claude-opus-5-5 input, output
FRAME_PREFIX = re.compile(r"^frame \d+(?: ball \d+)?: ")  # group "frame 3: x" with "frame 4: x"
MAX_ERRORS_IN_A_ROW = 3  # API errors in a row before giving up (the SDK already retries each)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder", nargs="?", type=Path, default=DATA_DIR / "inbox")
    parser.add_argument("--alias", action="append", default=[], help="add a name (repeatable)")
    parser.add_argument(
        "--confirm",
        action="append",
        default=[],
        help="add or mark a name a friend might also use; its games need confirming (repeatable)",
    )
    parser.add_argument("--limit", type=int, help="import at most this many new photos")
    parser.add_argument("--workers", type=int, default=4, help="photos read at the same time")
    parser.add_argument("--yes", action="store_true", help="don't ask before calling the API")
    parser.add_argument("--rematch-only", action="store_true", help="only re-match (free)")
    args = parser.parse_args()

    engine = make_engine()
    if "game" not in inspect(engine).get_table_names():
        sys.exit("The database isn't set up. Run: cd backend && .venv/bin/alembic upgrade head")

    with Session(engine) as session:
        add_aliases(session, args.alias, args.confirm)
        rematched = rematch_unmatched(session)
        if rematched:
            print(f"Re-matched {len(rematched)} earlier game(s) to your aliases (no API calls).")
        if not args.rematch_only:
            import_folder(session, args)
        print_summary(session)


def add_aliases(session: Session, names: list[str], confirm: list[str]) -> None:
    existing = {alias.key: alias for alias in session.exec(select(Alias)).all()}
    for name in names + confirm:
        key = alias_key(name)
        if key and key not in existing:
            existing[key] = Alias.of(name)
            session.add(existing[key])
            print(f"Added alias {name.strip()!r}")
    for name in confirm:
        alias = existing[alias_key(name)]
        if not alias.confirm:
            alias.confirm = True
            print(f"Games matched by {alias.name!r} will need you to confirm the row")
    session.commit()
    aliases = sorted(session.exec(select(Alias)).all(), key=lambda a: a.name.casefold())
    listed = ", ".join(a.name + ("*" if a.confirm else "") for a in aliases)
    print(f"Aliases: {listed or '(none - every game will need review)'}")
    if any(a.confirm for a in aliases):
        print("  * a friend might use this name too, so you confirm the row in review")


def import_folder(session: Session, args: argparse.Namespace) -> None:
    folder: Path = args.folder
    if not folder.is_dir():
        sys.exit(f"No folder {folder}. Put your photos there, or pass a folder.")
    files = sorted(
        p
        for p in folder.iterdir()
        if p.suffix.lower() in PHOTO_SUFFIXES and not p.name.startswith(".")
    )
    known = set(session.exec(select(Photo.sha256)).all())
    new = [p for p in files if file_sha256(p.read_bytes()) not in known]
    imported = len(files) - len(new)
    held_back = 0
    if args.limit is not None:
        held_back = max(len(new) - args.limit, 0)
        new = new[: args.limit]
    pending = session.exec(select(Game).where(Game.status == GameStatus.PENDING)).all()
    to_read = len(new) + len(pending)
    print(
        f"{len(files)} photo(s) in {folder}: {imported} already imported, "
        f"{len(new)} to import"
        + (f" ({held_back} more left for later by --limit)" if held_back else "")
        + f", plus {len(pending)} pending retry."
    )
    if to_read == 0:
        return
    if not args.yes and not confirm(
        f"Read {to_read} photo(s) for about ${to_read * COST_PER_PHOTO:.2f}?"
    ):
        sys.exit("Stopped; nothing was sent to the API.")

    jobs: list[tuple[str, Game, bytes]] = []
    for game in pending:
        photo = session.get(Photo, game.photo_id)
        jobs.append(
            (
                photo.original_name if photo else f"game {game.id}",
                game,
                stored_jpeg(session, game, DATA_DIR),
            )
        )
    for path in new:
        try:
            staged = stage_photo(session, path.read_bytes(), path.name, DATA_DIR)
        except PhotoError as error:
            print(f"  skipped {path.name}: {error}")
            continue
        if not staged.duplicate:  # a duplicate inside the folder itself
            jobs.append((path.name, staged.game, staged.jpeg))

    client = anthropic.Anthropic()
    stop = threading.Event()  # set when every remaining call would fail (e.g. out of credit)

    def read_unless_stopped(jpeg: bytes) -> ReadOutcome | None:
        return None if stop.is_set() else read_photo(jpeg, client)

    tokens = [0, 0]
    errors_in_a_row = 0
    not_read = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(read_unless_stopped, jpeg): (name, game) for name, game, jpeg in jobs
        }
        for done, future in enumerate(as_completed(futures), start=1):
            name, game = futures[future]
            outcome = future.result()
            if outcome is None:
                not_read += 1  # stays pending; the next run retries it
                continue
            if isinstance(outcome, ClaudeReading):
                tokens[0] += outcome.input_tokens
                tokens[1] += outcome.output_tokens
            errors_in_a_row = errors_in_a_row + 1 if isinstance(outcome, anthropic.APIError) else 0
            apply_reading(session, game, outcome)  # database writes stay on this thread
            print(f"  [{done}/{len(jobs)}] {name}: {describe(game)}")
            if isinstance(outcome, anthropic.APIError) and not stop.is_set():
                if should_stop_importing(outcome) or errors_in_a_row >= MAX_ERRORS_IN_A_ROW:
                    stop.set()
                    print(f"\nStopping: {outcome}\n")
    cost = (tokens[0] * PRICE_PER_MTOK[0] + tokens[1] * PRICE_PER_MTOK[1]) / 1_000_000
    print(f"API cost for this run: ${cost:.2f}")
    if stop.is_set():
        print(
            f"Stopped early: {not_read} photo(s) weren't sent. They're saved as pending; "
            "run this again (e.g. after adding credit) to read them."
        )


def describe(game: Game) -> str:
    if game.status is GameStatus.VERIFIED:
        total = game.printed_total
        return f"verified ({total}) on {game.played_on}"
    return f"{game.status.value}: {'; '.join(game.review_reasons)}"


def confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        sys.exit(f"{question} Re-run with --yes to confirm.")
    return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


def print_summary(session: Session) -> None:
    games = session.exec(select(Game)).all()
    counts = Counter(game.status.value for game in games)
    print("\nAll games: " + ", ".join(f"{n} {status}" for status, n in sorted(counts.items())))

    several = [
        game
        for game in ordered_games(session, (GameStatus.SKIPPED,))
        if game.review_reasons and game.review_reasons[0].startswith("several rows")
    ]
    if several:
        print(f"\n{len(several)} game(s) skipped: several of your names were on the board.")
        print("Enter these by hand later:")
        for game in several:
            photo = session.get(Photo, game.photo_id)
            matched = game.review_reasons[0].split("(")[1].split(")")[0]
            print(f"  {photo.original_name if photo else '?'}  {game.played_on}  ({matched})")

    unmatched = [
        game
        for game in games
        if game.status is GameStatus.NEEDS_REVIEW
        and game.review_reasons
        and game.review_reasons[0].startswith("no row matches")
    ]
    names: Counter[str] = Counter()
    for game in unmatched:
        extraction = session.get(Extraction, game.extraction_id)
        if extraction is not None:
            rows = reading_from_raw(extraction.raw_response).rows
            names.update({row.name.strip() for row in rows})
    if names:
        print(f"\n{len(unmatched)} game(s) didn't match an alias. Names on those boards:")
        for name, n in names.most_common():
            print(f"  {name!r} on {n} board(s)")
        print('Add yours with --rematch-only --alias "Name" (free, no API calls).')

    reasons = Counter(
        FRAME_PREFIX.sub("", reason)
        for game in games
        if game.status is GameStatus.NEEDS_REVIEW and game not in unmatched
        for reason in game.review_reasons
    )
    if reasons:
        print("\nOther review reasons (games can have several):")
        for reason, n in reasons.most_common():
            print(f"  {n} x {reason}")


if __name__ == "__main__":
    main()
