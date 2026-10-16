# Bowling Stats

Web app that imports photos of bowling scoreboards, reads the user's row with the Claude API, lets the user review/fix flagged games, and shows stats (high/low/average, trend, strikes, spares, and more).

## Stack
- Backend: Python 3.12, FastAPI, SQLite (SQLModel), pytest
- Frontend: React + TypeScript (Vite), Recharts for charts
- Photo reading: Claude API via the official `anthropic` Python SDK (backend only)
- Python tooling: `pyproject.toml` + pip + venv at `backend/.venv` (no uv). Lint with `ruff`, type-check with `mypy --strict`.

## Commands (update as the project is scaffolded)
- Backend setup: `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
- Backend dev: `cd backend && uvicorn app.main:app --reload`
- Backend tests: `cd backend && pytest`
- Backend lint/types: `cd backend && ruff check . && mypy --strict app`
- Frontend dev: `cd frontend && npm run dev`

## Architecture rules (do not break these)
1. **Claude reads, code computes.** The model only transcribes rolls and printed scores from a photo. All frame scores and stats are computed in `backend/app/scoring.py` and `stats.py` from stored rolls.
2. **Every extracted game is verified.** Recompute the 10 running totals from the rolls and compare them to the board's printed running totals (`printed_cumulative`) and the printed final total. Any mismatch -> status `needs_review`.
3. **Never guess.** An unreadable roll is stored as null plus a flag, not a best guess.
4. **Find the user's row by name.** Exact match against the user's alias list (stored in the DB), case-insensitive after trimming whitespace. No fuzzy matching, on purpose: zero or multiple matches -> `needs_review` so the user picks the row, and the app offers to save that name as a new alias. Single user, local-only, no login; one global alias list.
5. **API key stays server-side.** Read `ANTHROPIC_API_KEY` from `.env`. Never expose it to the frontend or commit it.
6. **Photos:** HEIC must be converted to JPEG before calling the API (the API does not accept HEIC). Resize to <= 2000 px on the long edge. One photo per API request. Read the capture date and time from EXIF. Apply EXIF rotation before resizing, and use pillow-heif for HEIC

## Roll notation
`X` strike, `/` spare, `-` miss (0), digits = pins. Frames 1-9 have 1-2 entries; frame 10 has 2-3. A null entry means unreadable.

Normalize other symbols before storing:
- `0` and `G` (gutter) -> `-`
- `F` (foul) -> `-` plus a `foul` flag on that roll
- Circled digits (a split) -> the digit, plus `split: true` on that frame's first ball. Scoring ignores the flag; it exists for future split stats.

## Scoring engine (`backend/app/scoring.py`)
Pure functions, no I/O. Types: `Roll = str | None`, `Frame = list[Roll]`, `Game = list[Frame]`.
- `to_pins(game)`: notation -> pin counts (`/` = 10 minus the previous ball)
- `validate(game)`: raises `InvalidGameError(frame_index, reason)` on bad notation. The caller catches it and sets the game to `needs_review`. Checks that would need a null roll are skipped.
- `frame_scores(game)`: the 10 running totals as a scoreboard prints them
- `game_total(game)`: the last running total

Invalid notation (raise, don't repair):
- `/` as the first ball of a frame
- two balls in frames 1-9 that add up to 10 or more without `/`
- `X` as the second ball in frames 1-9
- wrong number of frames, or wrong number of entries in a frame
- an unearned fill ball in frame 10, or a missing earned one

Null handling: a frame's running total is null if any roll it needs is null, including bonus rolls borrowed from later frames, and every frame after it is null too. A null frame-10 fill ball makes only frame 10 null. Exception: a null first ball before `/` doesn't block scoring (the spare is 10 either way), but `missing_rolls(game)` still lists it so the app can prompt the user to fill it in.

## Import and review
- One game per photo. Photos may have several players, but only use the game that the user played.
- Photos taken midgame (missing data) go to review.
- Skip exact duplicate photos using a hash, and flag games with the same date and identical rolls.
- No EXIF date -> ask the user. Store the capture time (for ordering) plus an editable date.
- Claude returns JSON that matches a schema; store the raw response with the game.
- Editing a verified game recomputes and re-checks it; Claude's original reading is kept.
- Accuracy script (outside pytest, costs API money) runs extraction on the fixture photos and reports accuracy.
- Set up Alembic migrations before the first real import.
- Frontend calls the backend through a Vite proxy (no CORS).

## Game statuses
`pending` -> `verified` | `needs_review` | `skipped` | `manual` (entered by hand, no photo)

## Stat definitions
- Only verified and manual games count towards stats.
- Strike % = strikes / balls thrown at a full rack (includes frame-10 fill balls)
- Spare conversion = spares / spare chances (frames where the first ball left pins, plus frame-10 fill balls that left pins)
- Open frame = no strike and no spare
- Average, high, low, games played
- Trend line = rolling average over the last 10 games
- Order games by EXIF capture time (it has no time zone), then by photo ID as a tiebreaker. The user can edit a game's date, and edit other stats.

## Testing
- Test fixture: `backend/tests/fixtures/verified_games.json` (10 real games, hand-verified against the scoreboards). Each game has `frames`, `total`, and `printed_cumulative` (the 10 running totals printed on the board).
- `scoring.py` must reproduce every `total` and every `printed_cumulative` in the fixture exactly.
- Edge cases: perfect game (300), all gutters (0), all `9 -` (90), all `5 /` with a 5 fill ball (150), alternating strike/spare (200), frame-10 variants (X X X, X 9 /, 9 / X, X X 5, X 8 1, 9 / 7, open), each invalid-notation case above, and null-roll cases.

## Git and privacy
- Never commit: `.env`, real scoreboard photos, the database file. Keep them in gitignored `data/`.
- Only synthetic or blurred sample images go in `samples/`.
- Small commits with clear messages.

## Code style
- Type hints everywhere in Python (enforced by `mypy --strict`); TypeScript strict mode.
- Keep scoring and stats as pure functions with unit tests.