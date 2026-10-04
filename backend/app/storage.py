"""Photo storage for accepted observations (flow step J).

Photos are re-encoded from decoded pixels before they are written, so EXIF - including
the phone's GPS tag and device serial - never reaches the disk, and faces are blurred. The location that is
kept is the one the reporter chose to send, in its own column.

Local disk for now; S3 or Supabase Storage (plan section 3) only needs `save_photo`
to write somewhere else.
"""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from app.privacy import blur_faces

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PHOTO_DIR = REPO_ROOT / "backend" / "storage" / "photos"
MAX_STORED_SIDE = 2048  # enough for a reviewer to zoom in; a 12 MP original is not needed


@dataclass(frozen=True)
class StoredPhoto:
    relative_path: str
    sha256: str
    faces_blurred: int = 0


def photo_dir() -> Path:
    return Path(os.environ.get("AQUAPULSE_PHOTO_DIR", DEFAULT_PHOTO_DIR))


def encode_for_storage(image: Image.Image) -> bytes:
    picture = image.convert("RGB")
    if max(picture.size) > MAX_STORED_SIDE:
        scale = MAX_STORED_SIDE / max(picture.size)
        picture = picture.resize((round(picture.width * scale), round(picture.height * scale)))
    buffer = io.BytesIO()
    picture.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def save_photo(image: Image.Image) -> StoredPhoto:
    # Section 22: faces are blurred before anything is written.
    image, faces = blur_faces(image)
    data = encode_for_storage(image)
    digest = hashlib.sha256(data).hexdigest()
    relative = f"{digest[:2]}/{digest}.jpg"
    target = photo_dir() / relative
    if not target.exists():  # identical photo already stored: content-addressed, keep one copy
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return StoredPhoto(relative, digest, faces)
