# Bowling Stats

Web app that imports photos of bowling scoreboards, reads the user's row with the Claude API, lets the user review/fix flagged games, and shows stats (high/low/average, trend, strikes, spares, and more).

## Stack
- Backend: Python 3.12, FastAPI, SQLite (SQLModel), pytest
- Frontend: React + TypeScript (Vite), Recharts for charts
- Photo reading: Claude API via the official `anthropic` Python SDK (backend only)

## Commands (update as the project is scaffolded)
- Backend dev: `cd backend && uvicorn app.main:app --reload`
- Backend tests: `cd backend && pytest`
- Frontend dev: `cd frontend && npm run dev`

## Architecture rules (do not break these)
1. **Claude reads, code computes.** The model only transcribes rolls and printed scores from a photo. All frame scores and stats are computed in `backend/app/scoring.py` and `stats.py` from stored rolls.
2. **Every extracted game is verified.** Recompute the frame-by-frame totals from the rolls and compare to the scoreboard's printed totals. Any mismatch -> status `needs_review`.
3. **Never guess.** Unreadable roll -> null plus a flag, not a best guess.
4. **Find the user's row by name.** Match against the user's alias list (stored in the DB, case-insensitive). Zero or multiple matches -> `needs_review` so the user picks the row.
5. **API key stays server-side.** Read `ANTHROPIC_API_KEY` from `.env`. Never expose it to the frontend or commit it.
6. **Photos:** HEIC must be converted to JPEG before calling the API (the API does not accept HEIC). Resize to <= 2000 px on the long edge. One photo per API request. Read the capture date from EXIF.

## Roll notation
`X` strike, `/` spare, `-` miss (0), digits = pins. Frames 1-9 have 1-2 entries; frame 10 has 2-3.

## Game statuses
`pending` -> `verified` | `needs_review` | `skipped` | `manual` (entered by hand, no photo)

## Stat definitions
- Strike % = strikes / balls thrown at a full rack (includes frame-10 fill balls)
- Spare conversion = spares / spare chances (frames where the first ball left pins, plus frame-10 fill balls that left pins)
- Open frame = no strike and no spare
- Average, high, low, games played, rolling average for the trend line

## Testing
- Test fixture: `backend/tests/fixtures/verified_games.json` (10 real games, hand-verified against the scoreboards).
- `scoring.py` must reproduce every `total` in the fixture exactly. Add edge cases: perfect game (300), all gutters (0), 10th-frame variants (X X X, X 9 /, 9 / X, open).

## Git and privacy
- Never commit: `.env`, real scoreboard photos, the database file. Keep them in gitignored `data/`.
- Only synthetic or blurred sample images go in `samples/`.
- Small commits with clear messages.

## Code style
- Type hints everywhere in Python; TypeScript strict mode.
- Keep scoring and stats as pure functions with unit tests.