"""board/images.py 저장·검증 단위 테스트."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import images as board_images


class FakeUpload:
    """st.file_uploader 가 돌려주는 UploadedFile 과 같은 인터페이스의 대역."""

    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self.type = "image/jpeg"
        self.size = len(data)
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def _jpeg(size: tuple[int, int] = (3000, 2000), with_exif: bool = False) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", size, (200, 40, 40))
    options: dict[str, object] = {}
    if with_exif:
        exif = Image.Exif()
        exif[0x0110] = "TestPhone"
        options["exif"] = exif
    image.save(buffer, format="JPEG", **options)
    return buffer.getvalue()


def _png(size: tuple[int, int] = (40, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, (0, 0, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def _noisy_png(side: int = 1600) -> bytes:
    buffer = io.BytesIO()
    Image.frombytes("RGB", (side, side), os.urandom(side * side * 3)).save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


def test_save_uploads_shrinks_and_builds_thumbnail(tmp_path: Path) -> None:
    saved = board_images.save_uploads([FakeUpload("a.jpg", _jpeg())], tmp_path)

    assert len(saved) == 1
    meta = saved[0]
    assert max(int(meta["width"]), int(meta["height"])) == board_images.MAX_SIDE
    assert (tmp_path / str(meta["stored_name"])).is_file()
    assert (tmp_path / str(meta["thumb_name"])).is_file()
    with Image.open(tmp_path / str(meta["thumb_name"])) as thumb:
        assert max(thumb.size) <= board_images.THUMB_SIDE
    assert meta["mime"] == "image/jpeg"


def test_save_uploads_strips_exif(tmp_path: Path) -> None:
    saved = board_images.save_uploads(
        [FakeUpload("a.jpg", _jpeg(with_exif=True))], tmp_path
    )

    with Image.open(tmp_path / str(saved[0]["stored_name"])) as stored:
        assert not stored.getexif()


def test_transparent_png_is_kept_as_png(tmp_path: Path) -> None:
    saved = board_images.save_uploads([FakeUpload("a.png", _png())], tmp_path)

    assert saved[0]["mime"] == "image/png"
    assert str(saved[0]["stored_name"]).endswith(".png")


def test_rejects_too_many_images() -> None:
    files = [
        FakeUpload(f"{index}.jpg", _jpeg((20, 20)))
        for index in range(board_images.MAX_IMAGES_PER_POST + 1)
    ]

    with pytest.raises(board_images.ImageValidationError):
        board_images.validate(files)


def test_allows_adding_up_to_the_limit_with_existing_images() -> None:
    files = [FakeUpload("a.jpg", _jpeg((20, 20)))]

    board_images.validate(files, existing_count=board_images.MAX_IMAGES_PER_POST - 1)
    with pytest.raises(board_images.ImageValidationError):
        board_images.validate(files, existing_count=board_images.MAX_IMAGES_PER_POST)


def test_rejects_oversized_file(tmp_path: Path) -> None:
    upload = FakeUpload("big.jpg", _jpeg((20, 20)))
    upload.size = board_images.MAX_IMAGE_BYTES + 1

    with pytest.raises(board_images.ImageValidationError):
        board_images.validate([upload])

    noisy = _noisy_png()
    assert len(noisy) > board_images.MAX_IMAGE_BYTES
    with pytest.raises(board_images.ImageValidationError):
        board_images.save_uploads([FakeUpload("big.png", noisy)], tmp_path)


def test_rejects_non_image_payload(tmp_path: Path) -> None:
    with pytest.raises(board_images.ImageValidationError):
        board_images.save_uploads([FakeUpload("a.jpg", b"not an image")], tmp_path)


def test_resolve_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(board_images.ImageValidationError):
        board_images.resolve("../evil.jpg", tmp_path)
    with pytest.raises(board_images.ImageValidationError):
        board_images.resolve("sub/../../evil.jpg", tmp_path)


def test_delete_files_is_idempotent(tmp_path: Path) -> None:
    saved = board_images.save_uploads([FakeUpload("a.jpg", _jpeg((100, 100)))], tmp_path)
    names = [str(saved[0]["stored_name"]), str(saved[0]["thumb_name"])]

    board_images.delete_files(names, tmp_path)
    assert not any((tmp_path / name).exists() for name in names)

    board_images.delete_files(names, tmp_path)


def test_exists_reports_saved_files_only(tmp_path: Path) -> None:
    saved = board_images.save_uploads([FakeUpload("a.jpg", _jpeg((64, 64)))], tmp_path)

    assert board_images.exists(str(saved[0]["stored_name"]), tmp_path)
    assert not board_images.exists("missing.jpg", tmp_path)


def test_is_enabled_only_for_photo_board() -> None:
    assert board_images.is_enabled("family")
    assert not board_images.is_enabled("tips")
    assert not board_images.is_enabled("study")
