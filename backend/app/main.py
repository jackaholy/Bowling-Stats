"""Entry point: `cd backend && .venv/bin/uvicorn app.main:app --reload` (API docs at /docs)."""

from app.api import create_app

app = create_app()
