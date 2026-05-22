from __future__ import annotations

import re
from copy import copy
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter

try:
    import pypdfium2 as pdfium

    PDF_RENDER_AVAILABLE = True
except Exception:
    pdfium = None
    PDF_RENDER_AVAILABLE = False


@dataclass(frozen=True)
class PageItem:
    pdf_path: Path
    page_index: int
    label: str
    rotation: int = 0


def parse_pages(spec: str, page_count: int) -> list[int]:
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("請輸入頁碼，例如 1,3,5-8。")

    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"頁碼範圍不正確：{part}")
            pages.extend(range(start - 1, end))
        else:
            pages.append(int(part) - 1)

    deduped: list[int] = []
    for page in pages:
        if page < 0 or page >= page_count:
            raise ValueError(f"頁碼超出範圍：{page + 1}，目前共有 {page_count} 頁。")
        if page not in deduped:
            deduped.append(page)
    return deduped


def safe_output_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip() or "output.pdf"


def open_reader(path: Path, password: str = "") -> PdfReader:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        if not password:
            raise ValueError(f"{path.name} 已加密，請輸入密碼。")
        result = reader.decrypt(password)
        if result == 0:
            raise ValueError(f"{path.name} 密碼不正確。")
    return reader


def write_pdf(writer: PdfWriter, path: Path) -> None:
    with path.open("wb") as stream:
        writer.write(stream)


def page_item_label(item: PageItem) -> str:
    if item.rotation:
        return f"{item.label} (旋轉 {item.rotation}度)"
    return item.label


def page_object_for_item(reader: PdfReader, item: PageItem):
    page = copy(reader.pages[item.page_index])
    if item.rotation:
        page.rotate(item.rotation)
    return page


def write_page_items_merged(page_items: list[PageItem], indexes: list[int], target: Path, password: str = "") -> None:
    if not indexes:
        raise ValueError("請先選取要擷取的頁面。")
    writer = PdfWriter()
    reader_cache: dict[Path, PdfReader] = {}
    for index in indexes:
        item = page_items[index]
        reader = reader_cache.get(item.pdf_path)
        if reader is None:
            reader = open_reader(item.pdf_path, password)
            reader_cache[item.pdf_path] = reader
        writer.add_page(page_object_for_item(reader, item))
    write_pdf(writer, target)


def write_page_items_separately(page_items: list[PageItem], indexes: list[int], folder: Path, password: str = "") -> int:
    if not indexes:
        raise ValueError("請先選取要擷取的頁面。")
    folder.mkdir(parents=True, exist_ok=True)
    reader_cache: dict[Path, PdfReader] = {}
    for output_index, page_index in enumerate(indexes, start=1):
        item = page_items[page_index]
        reader = reader_cache.get(item.pdf_path)
        if reader is None:
            reader = open_reader(item.pdf_path, password)
            reader_cache[item.pdf_path] = reader
        writer = PdfWriter()
        writer.add_page(page_object_for_item(reader, item))
        filename = safe_output_name(f"{output_index:03d}-{item.pdf_path.stem}-page-{item.page_index + 1}.pdf")
        write_pdf(writer, folder / filename)
    return len(indexes)
