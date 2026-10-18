"""Paths and settings. The database and photos live in the gitignored data/ folder.

`.env` at the repo root is loaded here; `ANTHROPIC_API_KEY` is read from it by the SDK.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

load_dotenv(REPO_ROOT / ".env")

DEFAULT_MODEL = "claude-opus-5-5"


def database_url() -> str:
    """`BOWLING_DATABASE_URL` if set (tests use it), else `data/bowling.db`."""
    return os.environ.get("BOWLING_DATABASE_URL", f"sqlite:///{DATA_DIR / 'bowling.db'}")


def extraction_model() -> str:
    """`BOWLING_MODEL` if set, else Claude Opus 5.5."""
    return os.environ.get("BOWLING_MODEL", DEFAULT_MODEL)
