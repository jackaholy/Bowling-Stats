"""Photo preparation: original bytes in, an API-ready JPEG out. No file or network I/O.

HEIC is decoded via pillow-heif. EXIF rotation is applied before resizing. The output JPEG
carries no EXIF, so GPS and other metadata never leave the machine.
"""

import hashlib
import io
from dataclasses import dataclass
from datetime import datetime

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

pillow_heif.register_heif_opener()

MAX_EDGE = 2000
MAX_JPEG_BYTES = 5 * 1024 * 1024  # the API's per-image limit
JPEG_QUALITIES = (90, 80, 70, 60)

_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 0x9003
_DATETIME_DIGITIZED = 0x9004
_EXIF_DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"


class PhotoError(ValueError):
    """The file isn't an image we can read, or can't be made small enough."""


@dataclass(frozen=True)
class PreparedPhoto:
    sha256: str  # of the original bytes, to skip exact duplicates
    jpeg: bytes
    width: int
    height: int
    captured_at: datetime | None  # EXIF capture time, naive; None means ask the user


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare_photo(data: bytes) -> PreparedPhoto:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            captured_at = _capture_time(opened.getexif())
            image = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise PhotoError(f"not a readable image: {error}") from error
    image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    return PreparedPhoto(
        sha256=file_sha256(data),
        jpeg=_encode_jpeg(image),
        width=image.width,
        height=image.height,
        captured_at=captured_at,
    )


def _capture_time(exif: Image.Exif) -> datetime | None:
    """DateTimeOriginal, else DateTimeDigitized. Not IFD0 DateTime: that's when the file changed."""
    sub_ifd = exif.get_ifd(_EXIF_IFD)
    for tag in (_DATETIME_ORIGINAL, _DATETIME_DIGITIZED):
        value = sub_ifd.get(tag)
        if not isinstance(value, str):
            continue
        try:
            return datetime.strptime(value.strip("\x00 "), _EXIF_DATETIME_FORMAT)
        except ValueError:
            continue  # blank or placeholder like "0000:00:00 00:00:00"
    return None


def _encode_jpeg(image: Image.Image) -> bytes:
    for quality in JPEG_QUALITIES:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        if buffer.tell() <= MAX_JPEG_BYTES:
            return buffer.getvalue()
    raise PhotoError("JPEG is over the API size limit even at the lowest quality")
