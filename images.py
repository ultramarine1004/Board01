"""사진 첨부 저장소.

Streamlit 에 의존하지 않는 순수 파이썬 모듈이다. 업로드된 사진을 검증한 뒤
EXIF 를 제거하고 다시 인코딩해 ``board/data/uploads`` 에 저장하며, 목록용
썸네일을 함께 만든다. 저장 파일 이름은 항상 UUID 로 새로 만들기 때문에
사용자가 올린 파일 이름이 경로에 영향을 주지 않는다.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageOps, UnidentifiedImageError

ENABLED_BOARDS: tuple[str, ...] = ("family",)
MAX_IMAGES_PER_POST: int = 10
MAX_IMAGE_BYTES: int = 5 * 1024 * 1024
MAX_SIDE: int = 1920
THUMB_SIDE: int = 320
JPEG_QUALITY: int = 85
ACCEPTED_TYPES: tuple[str, ...] = ("jpg", "jpeg", "png", "webp")
UPLOAD_DIR: Path = Path(__file__).resolve().parent / "data" / "uploads"

# 압축 폭탄(decompression bomb) 방어: 이 값을 넘는 픽셀 수는 열지 않는다.
Image.MAX_IMAGE_PIXELS = 40_000_000

_PNG_MODES = {"RGBA", "LA", "PA"}


class ImageValidationError(ValueError):
    """사진이 형식·용량·장수 정책을 벗어났을 때 발생한다."""


def is_enabled(board: str) -> bool:
    """해당 게시판에서 사진 첨부를 허용하는지 반환한다."""
    return board in ENABLED_BOARDS


def validate(files: Iterable[Any], existing_count: int = 0) -> None:
    """저장 전에 장수와 장당 용량을 검사한다."""
    items = list(files or ())
    if existing_count + len(items) > MAX_IMAGES_PER_POST:
        raise ImageValidationError(
            f"사진은 게시글당 {MAX_IMAGES_PER_POST}장까지 올릴 수 있습니다."
        )
    limit_mb = MAX_IMAGE_BYTES // (1024 * 1024)
    for item in items:
        size = int(getattr(item, "size", 0) or len(_read(item)))
        if size > MAX_IMAGE_BYTES:
            name = getattr(item, "name", "사진")
            raise ImageValidationError(f"'{name}' 은(는) {limit_mb}MB 를 넘습니다.")


def upload_dir(upload_dir_path: Path | str | None = None) -> Path:
    """업로드 저장 폴더를 반환하고 없으면 만든다."""
    path = Path(upload_dir_path or UPLOAD_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve(name: str, upload_dir_path: Path | str | None = None) -> Path:
    """저장 이름으로 실제 파일 경로를 구한다. 폴더 밖 경로는 거부한다."""
    base = Path(upload_dir_path or UPLOAD_DIR).resolve()
    candidate = (base / name).resolve()
    if base != candidate.parent:
        raise ImageValidationError("잘못된 이미지 경로입니다.")
    return candidate


def exists(name: str, upload_dir_path: Path | str | None = None) -> bool:
    """저장 파일이 실제로 남아 있는지 확인한다(수동 삭제 대비)."""
    try:
        return resolve(name, upload_dir_path).is_file()
    except (OSError, ImageValidationError):
        return False


def save_uploads(
    files: Iterable[Any], upload_dir_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """업로드 파일들을 검증·재인코딩해 저장하고 메타데이터 목록을 반환한다."""
    target = upload_dir(upload_dir_path)
    saved: list[dict[str, Any]] = []
    for item in files or ():
        image = _open_image(item)
        try:
            saved.append(_write_image(image, target))
        except (OSError, ValueError):
            delete_files(_names(saved), target)
            raise
        finally:
            image.close()
    return saved


def delete_files(names: Iterable[str], upload_dir_path: Path | str | None = None) -> None:
    """저장된 이미지 파일들을 지운다. 이미 없으면 조용히 넘어간다."""
    for name in names:
        if not name:
            continue
        try:
            resolve(name, upload_dir_path).unlink(missing_ok=True)
        except (OSError, ImageValidationError):
            continue


def _read(item: Any) -> bytes:
    if hasattr(item, "getvalue"):
        return bytes(item.getvalue())
    if hasattr(item, "read"):
        return bytes(item.read())
    return bytes(item)


def _open_image(item: Any) -> Image.Image:
    raw = _read(item)
    name = getattr(item, "name", "사진")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ImageValidationError(
            f"'{name}' 은(는) {MAX_IMAGE_BYTES // (1024 * 1024)}MB 를 넘습니다."
        )
    try:
        probe = Image.open(io.BytesIO(raw))
        probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ImageValidationError(f"'{name}' 은(는) 이미지 파일이 아닙니다.") from error
    try:
        return Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ImageValidationError(f"'{name}' 을(를) 읽을 수 없습니다.") from error


def _write_image(image: Image.Image, target: Path) -> dict[str, Any]:
    # 회전 정보를 픽셀에 반영한 뒤 EXIF(촬영 위치 포함)를 저장 파일에서 제거한다.
    upright = ImageOps.exif_transpose(image) or image
    use_png = upright.mode in _PNG_MODES or (
        upright.mode == "P" and "transparency" in upright.info
    )
    fmt, ext, mime = ("PNG", ".png", "image/png") if use_png else ("JPEG", ".jpg", "image/jpeg")
    converted = upright.convert("RGBA" if use_png else "RGB")

    resized = _shrink(converted, MAX_SIDE)
    thumb = _shrink(resized, THUMB_SIDE)

    token = uuid.uuid4().hex
    stored_name = f"{token}{ext}"
    thumb_name = f"{token}_t{ext}"
    main_bytes = _encode(resized, fmt)
    thumb_bytes = _encode(thumb, fmt)

    target.joinpath(stored_name).write_bytes(main_bytes)
    target.joinpath(thumb_name).write_bytes(thumb_bytes)
    if resized is not converted:
        resized.close()
    thumb.close()
    converted.close()

    return {
        "stored_name": stored_name,
        "thumb_name": thumb_name,
        "mime": mime,
        "width": resized.width,
        "height": resized.height,
        "byte_size": len(main_bytes),
    }


def _shrink(image: Image.Image, limit: int) -> Image.Image:
    longest = max(image.width, image.height)
    if longest <= limit:
        return image
    ratio = limit / longest
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    return image.resize(size, Image.LANCZOS)


def _encode(image: Image.Image, fmt: str) -> bytes:
    buffer = io.BytesIO()
    options: dict[str, Any] = {"optimize": True}
    if fmt == "JPEG":
        options["quality"] = JPEG_QUALITY
        options["progressive"] = True
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


def _names(saved: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in saved:
        names.append(str(item["stored_name"]))
        names.append(str(item["thumb_name"]))
    return names
