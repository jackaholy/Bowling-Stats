from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anthropic
import pytest
from conftest import FakeAnthropic, make_jpeg
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api import create_app
from app.board import BallReading, BoardReading, FrameReading, RowReading

NINES: list[list[str | None]] = [["9", "-"]] * 10
NINES_TOTALS: list[int | None] = [9 * n for n in range(1, 11)]
TAKEN = "2024:08:26 21:14:05"


def reading(*names: str, frames: list[list[str | None]] = NINES) -> BoardReading:
    return BoardReading(
        rows=[
            RowReading(
                name=name,
                frames=[
                    FrameReading(
                        balls=[BallReading(mark=m, circled=False) for m in f], total=NINES_TOTALS[i]
                    )
                    for i, f in enumerate(frames)
                ],
                final_total=90,
            )
            for name in names
        ],
        notes="",
    )


@pytest.fixture
def fake_claude() -> FakeAnthropic:
    return FakeAnthropic(reading("Jack", "Usa"))


@pytest.fixture
def api(engine: Engine, tmp_path: Path, fake_claude: FakeAnthropic) -> Iterator[TestClient]:
    client: anthropic.Anthropic = fake_claude  # type: ignore[assignment]
    with TestClient(create_app(engine, tmp_path, client)) as test_client:
        yield test_client


def upload(api: TestClient, photo: bytes, name: str = "IMG_1.HEIC") -> dict[str, Any]:
    response = api.post("/api/photos", files={"file": (name, photo, "image/heic")})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def add_alias(api: TestClient, name: str, confirm: bool = False) -> None:
    assert api.post("/api/aliases", json={"name": name, "confirm": confirm}).status_code == 201


def test_upload_verifies_and_serves_photo(api: TestClient) -> None:
    add_alias(api, "Jack")
    body = upload(api, make_jpeg(taken=TAKEN))
    game = body["game"]
    assert body["duplicate"] is False
    assert game["status"] == "verified"
    assert game["total"] == 90
    assert game["scores"] == NINES_TOTALS
    assert game["played_on"] == "2024-08-26"
    assert game["captured_at"] == "2024-08-26T21:14:05"
    assert [row["name"] for row in game["rows"]] == ["Jack", "Usa"]
    assert [row["matches_alias"] for row in game["rows"]] == [True, False]
    image = api.get(f"/api/photos/{game['photo_id']}/image")
    assert image.headers["content-type"] == "image/jpeg"


def test_duplicate_upload_does_not_call_claude(api: TestClient, fake_claude: FakeAnthropic) -> None:
    photo = make_jpeg(taken=TAKEN)
    first = upload(api, photo)
    again = upload(api, photo)
    assert again["duplicate"] is True
    assert again["game"]["id"] == first["game"]["id"]
    assert len(fake_claude.calls) == 1


def test_not_an_image_is_rejected(api: TestClient) -> None:
    response = api.post("/api/photos", files={"file": ("x.heic", b"nope", "image/heic")})
    assert response.status_code == 422


def test_pick_row_and_save_alias(api: TestClient) -> None:
    game = upload(api, make_jpeg(taken=TAKEN))["game"]
    assert game["status"] == "needs_review"
    assert game["frames"] is None

    picked = api.post(
        f"/api/games/{game['id']}/pick-row", json={"row_index": 0, "save_alias": True}
    )
    assert picked.json()["status"] == "verified"
    assert picked.json()["name_on_board"] == "Jack"
    assert [a["name"] for a in api.get("/api/aliases").json()] == ["Jack"]


def test_confirm_name_waits_for_pick_row_even_after_edits(api: TestClient) -> None:
    add_alias(api, "Jack", confirm=True)
    game = upload(api, make_jpeg(taken=TAKEN))["game"]
    assert game["status"] == "needs_review"
    edited = api.patch(f"/api/games/{game['id']}", json={"played_on": "2024-08-27"}).json()
    assert edited["status"] == "needs_review"  # an unrelated edit doesn't confirm the row
    picked = api.post(f"/api/games/{game['id']}/pick-row", json={"row_index": 0}).json()
    assert picked["status"] == "verified"


def test_editing_rolls_rechecks_against_printed_totals(api: TestClient) -> None:
    add_alias(api, "Jack")
    game = upload(api, make_jpeg(taken=TAKEN))["game"]
    frames = [list(f) for f in NINES]
    frames[0] = ["8", "-"]
    edited = api.patch(f"/api/games/{game['id']}", json={"frames": frames}).json()
    assert edited["status"] == "needs_review"
    assert edited["review_reasons"][0] == "frame 1: board shows 9, rolls give 8"

    # The board itself was misread: fix the printed totals too, and it verifies again.
    printed = [8 + 9 * n for n in range(10)]
    fixed = api.patch(
        f"/api/games/{game['id']}", json={"printed_cumulative": printed, "printed_total": 89}
    ).json()
    assert fixed["status"] == "verified"
    assert fixed["total"] == 89


def test_missing_date_is_fixed_by_editing_it(api: TestClient) -> None:
    add_alias(api, "Jack")
    game = upload(api, make_jpeg())["game"]
    assert game["review_reasons"] == ["the photo has no capture date; enter the date"]
    fixed = api.patch(f"/api/games/{game['id']}", json={"played_on": "2023-01-02"}).json()
    assert fixed["status"] == "verified"


def test_skip_and_unskip(api: TestClient) -> None:
    add_alias(api, "Jack")
    game = upload(api, make_jpeg(taken=TAKEN))["game"]
    assert api.post(f"/api/games/{game['id']}/skip").json()["status"] == "skipped"
    assert api.get("/api/stats").json()["games_played"] == 0
    assert api.post(f"/api/games/{game['id']}/unskip").json()["status"] == "verified"


def test_retry_reads_the_photo_again(api: TestClient, fake_claude: FakeAnthropic) -> None:
    game = upload(api, make_jpeg(taken=TAKEN))["game"]
    add_alias(api, "Jack")
    assert api.post(f"/api/games/{game['id']}/retry").json()["status"] == "verified"
    assert len(fake_claude.calls) == 2
    assert api.post(f"/api/games/{game['id']}/retry").status_code == 409  # verified now


def test_manual_games(api: TestClient) -> None:
    body = {"played_on": "2025-01-01", "frames": [["X"]] * 9 + [["X", "X", "X"]]}
    created = api.post("/api/games", json=body)
    assert created.status_code == 201
    game = created.json()
    assert (game["status"], game["total"]) == ("manual", 300)

    invalid = {"played_on": "2025-01-01", "frames": [["6", "5"]] + NINES[1:]}
    assert api.post("/api/games", json=invalid).status_code == 422
    unscorable = {"played_on": "2025-01-01", "frames": [["9", None]] + NINES[1:]}
    assert "fill in" in api.post("/api/games", json=unscorable).json()["detail"]

    assert api.delete(f"/api/games/{game['id']}").status_code == 204
    assert api.get(f"/api/games/{game['id']}").status_code == 404


def test_photo_games_cannot_be_deleted(api: TestClient) -> None:
    game = upload(api, make_jpeg(taken=TAKEN))["game"]
    assert api.delete(f"/api/games/{game['id']}").status_code == 409


def test_aliases(api: TestClient) -> None:
    add_alias(api, "Jack 1")
    assert api.post("/api/aliases", json={"name": "JACK1"}).status_code == 409
    assert api.post("/api/aliases", json={"name": "  "}).status_code == 422
    alias = api.get("/api/aliases").json()[0]
    assert api.patch(f"/api/aliases/{alias['id']}", json={"confirm": True}).json()["confirm"]
    assert api.delete(f"/api/aliases/{alias['id']}").status_code == 204
    assert api.get("/api/aliases").json() == []


def test_stats_follow_play_order_and_editable_dates(api: TestClient) -> None:
    for day, frames in (("2025-03-01", [["X"]] * 9 + [["X", "X", "X"]]), ("2025-02-01", NINES)):
        api.post("/api/games", json={"played_on": day, "frames": frames})
    stats = api.get("/api/stats").json()
    assert (stats["games_played"], stats["average"], stats["high"], stats["low"]) == (
        2,
        195,
        300,
        90,
    )
    assert [p["total"] for p in stats["trend"]] == [90, 300]
    assert [p["rolling_average"] for p in stats["trend"]] == [90, 195]

    first_game = stats["trend"][0]["game_id"]
    api.patch(f"/api/games/{first_game}", json={"played_on": "2025-04-01"})
    assert [p["total"] for p in api.get("/api/stats").json()["trend"]] == [300, 90]


def test_list_games_by_status(api: TestClient) -> None:
    add_alias(api, "Jack")
    upload(api, make_jpeg((1, 2, 3), TAKEN), "a")
    upload(api, make_jpeg((9, 9, 9)), "b")  # no date -> review
    assert [g["photo_name"] for g in api.get("/api/games?status=needs_review").json()] == ["b"]
    assert len(api.get("/api/games").json()) == 2


def test_root_redirects_to_api_docs(api: TestClient) -> None:
    response = api.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"
