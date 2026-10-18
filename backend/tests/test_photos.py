"""Synthetic images only: real scoreboard photos never go in the repo."""

import hashlib
import io
from datetime import datetime

import pytest
from PIL import Image

from app.photos import MAX_EDGE, PhotoError, prepare_photo

RED = (255, 0, 0)
BLUE = (0, 0, 255)


def make_image(
    width: int = 300,
    height: int = 100,
    *,
    format: str = "JPEG",
    orientation: int | None = None,
    original: str | None = None,
    digitized: str | None = None,
    mode: str = "RGB",
) -> bytes:
    """Left half red, right half blue, with optional EXIF."""
    image = Image.new(mode, (width, height), BLUE)
    image.paste(RED, (0, 0, width // 2, height))
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    sub_ifd = exif.get_ifd(0x8769)
    if original is not None:
        sub_ifd[0x9003] = original
    if digitized is not None:
        sub_ifd[0x9004] = digitized
    buffer = io.BytesIO()
    image.save(buffer, format=format, exif=exif.tobytes())
    return buffer.getvalue()


def decode(jpeg: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(jpeg))
    assert image.format == "JPEG"
    return image


def close_to(pixel: object, color: tuple[int, int, int]) -> bool:
    assert isinstance(pixel, tuple)
    return all(abs(a - b) < 40 for a, b in zip(pixel, color, strict=True))


def test_jpeg_with_capture_time() -> None:
    data = make_image(original="2024:08:26 21:14:05")
    photo = prepare_photo(data)
    assert photo.captured_at == datetime(2024, 8, 26, 21, 14, 5)
    assert photo.sha256 == hashlib.sha256(data).hexdigest()
    assert (photo.width, photo.height) == (300, 100)


def test_heic_is_converted_to_jpeg() -> None:
    photo = prepare_photo(make_image(format="HEIF", original="2026:05:28 19:02:00"))
    image = decode(photo.jpeg)
    assert image.size == (300, 100)
    assert photo.captured_at == datetime(2026, 5, 28, 19, 2)


@pytest.mark.parametrize("format", ["JPEG", "HEIF"])
def test_exif_rotation_is_applied(format: str) -> None:
    # Orientation 6: the camera was turned, so the stored image displays rotated 90° clockwise.
    image = decode(prepare_photo(make_image(format=format, orientation=6)).jpeg)
    assert image.size == (100, 300)
    assert close_to(image.getpixel((50, 10)), RED)  # the left half is now on top
    assert close_to(image.getpixel((50, 290)), BLUE)


def test_rotation_happens_before_resizing() -> None:
    photo = prepare_photo(make_image(4000, 1000, orientation=6))
    assert (photo.width, photo.height) == (500, MAX_EDGE)


def test_large_photo_is_shrunk_to_max_edge() -> None:
    photo = prepare_photo(make_image(4032, 3024))
    assert (photo.width, photo.height) == (MAX_EDGE, 1500)
    assert decode(photo.jpeg).size == (MAX_EDGE, 1500)


def test_small_photo_is_not_enlarged() -> None:
    assert prepare_photo(make_image(800, 600)).width == 800


def test_png_with_alpha_becomes_jpeg() -> None:
    assert decode(prepare_photo(make_image(format="PNG", mode="RGBA")).jpeg).mode == "RGB"


def test_output_has_no_exif() -> None:
    data = make_image(orientation=6, original="2024:08:26 21:14:05")
    assert len(decode(prepare_photo(data).jpeg).getexif()) == 0


def test_missing_capture_time_is_none() -> None:
    assert prepare_photo(make_image()).captured_at is None


def test_placeholder_capture_time_falls_back_to_digitized() -> None:
    data = make_image(original="0000:00:00 00:00:00", digitized="2023:03:20 18:30:00")
    assert prepare_photo(data).captured_at == datetime(2023, 3, 20, 18, 30)


def test_unparseable_capture_times_are_none() -> None:
    assert prepare_photo(make_image(original="    :  :     :  :  ")).captured_at is None


def test_not_an_image_is_refused() -> None:
    with pytest.raises(PhotoError):
        prepare_photo(b"definitely not a photo")
