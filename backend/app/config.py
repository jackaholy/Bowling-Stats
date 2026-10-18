"""Paths and settings. The database and photos live in the gitignored data/ folder."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


def database_url() -> str:
    """`BOWLING_DATABASE_URL` if set (tests use it), else `data/bowling.db`."""
    return os.environ.get("BOWLING_DATABASE_URL", f"sqlite:///{DATA_DIR / 'bowling.db'}")
