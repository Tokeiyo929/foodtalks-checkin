from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from .models import PhotoRecord

IMAGE_EXTENSIONS: Final = frozenset({".jpg", ".jpeg", ".png", ".webp", ".heic"})


class PhotoPipelineError(RuntimeError):
    pass


def scan_photos(root: Path, run_dir: Path, limit: int | None, offset: int) -> tuple[PhotoRecord, ...]:
    if not root.exists():
        msg = f"Photo path does not exist: {root}"
        raise PhotoPipelineError(msg)

    preview_dir = run_dir / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    files = discover_images(root, limit, offset)
    return tuple(make_record(path, preview_dir) for path in files)


def discover_images(root: Path, limit: int | None, offset: int) -> tuple[Path, ...]:
    if root.is_file():
        files = [root] if root.suffix.casefold() in IMAGE_EXTENSIONS else []
    else:
        files = [
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.casefold() in IMAGE_EXTENSIONS
        ]
    files.sort(key=lambda path: str(path).casefold())
    shifted = files[offset:]
    return tuple(shifted[:limit] if limit is not None else shifted)


def make_record(path: Path, preview_dir: Path) -> PhotoRecord:
    digest = hash_file(path)
    preview_path = preview_dir / f"{digest[:16]}.jpg"
    ensure_preview(path, preview_path)
    stat = path.stat()
    return PhotoRecord(
        custom_id=f"photo-{digest[:24]}",
        path=path,
        preview_path=preview_path,
        size_bytes=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        sha256=digest,
    )


def hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def ensure_preview(source: Path, target: Path, max_size: int = 1280) -> None:
    if target.exists():
        return

    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
        from pillow_heif import register_heif_opener
    except ModuleNotFoundError as error:
        msg = "Pillow and pillow-heif are required to create API preview images. Run `uv sync` first."
        raise PhotoPipelineError(msg) from error

    try:
        register_heif_opener()
        with Image.open(source) as image:
            normalized = ImageOps.exif_transpose(image)
            normalized.thumbnail((max_size, max_size))
            normalized.convert("RGB").save(target, "JPEG", quality=82, optimize=True)
    except UnidentifiedImageError as error:
        msg = f"Cannot read image file: {source}"
        raise PhotoPipelineError(msg) from error
