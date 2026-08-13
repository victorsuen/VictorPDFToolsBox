from __future__ import annotations

import shutil
from pathlib import Path

from pdf_core import IMAGE_SUFFIXES


def toolbox_home() -> Path:
    path = Path.home() / ".victor_pdf_toolbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def stamp_library_dir() -> Path:
    path = toolbox_home() / "stamps"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_library_stamps() -> list[Path]:
    return sorted(
        path
        for path in stamp_library_dir().iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def add_library_stamp(image_path: Path) -> Path:
    image_path = Path(image_path)
    if not image_path.is_file():
        raise ValueError(f"找不到圖片檔案：{image_path.name}")
    if image_path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError("圖章庫只接受常見圖片格式（PNG / JPG / WEBP / BMP / TIF）。")
    dest_dir = stamp_library_dir()
    dest = dest_dir / image_path.name
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        index = 2
        while dest.exists():
            dest = dest_dir / f"{stem}-{index}{suffix}"
            index += 1
    shutil.copy2(image_path, dest)
    return dest


def delete_library_stamp(path: Path) -> None:
    path = Path(path).resolve()
    library = stamp_library_dir().resolve()
    try:
        path.relative_to(library)
    except ValueError as exc:
        raise ValueError("只能刪除圖章庫內的檔案。") from exc
    if not path.is_file():
        raise ValueError("找不到圖章檔案。")
    path.unlink()
