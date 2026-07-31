from __future__ import annotations

import io
import re
import tempfile
import zipfile
from copy import copy
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    ByteStringObject,
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    RectangleObject,
    TextStringObject,
)

try:
    import pypdfium2 as pdfium

    PDF_RENDER_AVAILABLE = True
except Exception:
    pdfium = None
    PDF_RENDER_AVAILABLE = False

try:
    import pytesseract
    from pytesseract import TesseractNotFoundError

    OCR_AVAILABLE = True
except Exception:
    pytesseract = None

    class TesseractNotFoundError(Exception):
        pass

    OCR_AVAILABLE = False

try:
    import fitz

    PYMUPDF_AVAILABLE = True
except Exception:
    fitz = None
    PYMUPDF_AVAILABLE = False

PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
OCR_LANGUAGE_OPTIONS = {
    "eng": "English",
    "chi_tra": "Traditional Chinese",
    "chi_sim": "Simplified Chinese",
    "eng+chi_tra": "English + Traditional Chinese",
    "eng+chi_sim": "English + Simplified Chinese",
}


@dataclass(frozen=True)
class PageItem:
    pdf_path: Path
    page_index: int
    label: str
    rotation: int = 0


@dataclass(frozen=True)
class TextBlock:
    text: str
    x: float
    y: float
    width: float
    height: float
    font_size: float
    font_name: str = ""
    color_rgb: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    font_flags: int = 0
    page_font_name: str = ""
    font_file: str = ""


def block_right(block: TextBlock) -> float:
    return block.x + block.width


def block_bottom(block: TextBlock) -> float:
    return block.y - block.height


def _merge_block_bbox(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    if left == (0.0, 0.0, 0.0, 0.0):
        return right
    if right == (0.0, 0.0, 0.0, 0.0):
        return left
    return (
        min(left[0], right[0]),
        min(left[1], right[1]),
        max(left[2], right[2]),
        max(left[3], right[3]),
    )


def text_blocks_on_same_line(left: TextBlock, right: TextBlock) -> bool:
    tolerance = max(left.font_size, right.font_size) * 0.6
    return abs(left.y - right.y) <= tolerance


def merge_text_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    if not blocks:
        return []
    sorted_blocks = sorted(blocks, key=lambda block: (-block.y, block.x))
    lines: list[list[TextBlock]] = []
    for block in sorted_blocks:
        for line in lines:
            if text_blocks_on_same_line(line[0], block):
                line.append(block)
                break
        else:
            lines.append([block])

    merged: list[TextBlock] = []
    for line in lines:
        line = sorted(line, key=lambda block: block.x)
        current = line[0]
        for block in line[1:]:
            gap = block.x - block_right(current)
            max_gap = max(current.font_size, block.font_size) * 1.8
            if gap <= max_gap:
                separator = " " if gap > current.font_size * 0.25 else ""
                left = min(current.x, block.x)
                right = max(block_right(current), block_right(block))
                top = max(current.y, block.y)
                bottom = min(block_bottom(current), block_bottom(block))
                current = TextBlock(
                    text=f"{current.text}{separator}{block.text}",
                    x=left,
                    y=top,
                    width=right - left,
                    height=top - bottom,
                    font_size=max(current.font_size, block.font_size),
                    font_name=current.font_name or block.font_name,
                    color_rgb=current.color_rgb,
                    bbox=_merge_block_bbox(current.bbox, block.bbox),
                    font_flags=current.font_flags or block.font_flags,
                    page_font_name=current.page_font_name or block.page_font_name,
                    font_file=current.font_file or block.font_file,
                )
            else:
                merged.append(current)
                current = block
        merged.append(current)
    return sorted(merged, key=lambda block: (-block.y, block.x))


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


def merge_pdf_files(paths: list[Path], target: Path, password: str = "") -> None:
    if len(paths) < 2:
        raise ValueError("合併 PDF 至少需要兩個檔案。")
    writer = PdfWriter()
    for path in paths:
        reader = open_reader(path, password)
        for page in reader.pages:
            writer.add_page(page)
    write_pdf(writer, target)


def split_pdf_to_zip(source: Path, target_zip: Path, password: str = "") -> int:
    reader = open_reader(source, password)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        generated: list[Path] = []
        for index, page in enumerate(reader.pages, start=1):
            writer = PdfWriter()
            writer.add_page(page)
            part = temp_path / f"page-{index:04d}.pdf"
            write_pdf(writer, part)
            generated.append(part)
        with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in generated:
                archive.write(item, item.name)
    return len(reader.pages)


def extract_pdf_pages(source: Path, target: Path, pages_spec: str, password: str = "") -> None:
    reader = open_reader(source, password)
    pages = parse_pages(pages_spec, len(reader.pages))
    writer = PdfWriter()
    for index in pages:
        writer.add_page(reader.pages[index])
    write_pdf(writer, target)


def delete_pdf_pages(source: Path, target: Path, pages_spec: str, password: str = "") -> None:
    reader = open_reader(source, password)
    delete_pages = set(parse_pages(pages_spec, len(reader.pages)))
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index not in delete_pages:
            writer.add_page(page)
    if not writer.pages:
        raise ValueError("不能刪除全部頁面。")
    write_pdf(writer, target)


def rotate_pdf_pages(source: Path, target: Path, angle: int, pages_spec: str = "", password: str = "") -> None:
    if angle not in {90, 180, 270}:
        raise ValueError("旋轉角度只支援 90、180、270。")
    reader = open_reader(source, password)
    rotate_pages = set(parse_pages(pages_spec, len(reader.pages))) if pages_spec.strip() else set(range(len(reader.pages)))
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index in rotate_pages:
            page.rotate(angle)
        writer.add_page(page)
    write_pdf(writer, target)


def encrypt_pdf(source: Path, target: Path, new_password: str, password: str = "") -> None:
    if not new_password:
        raise ValueError("請輸入新密碼。")
    reader = open_reader(source, password)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(new_password)
    write_pdf(writer, target)


def decrypt_pdf(source: Path, target: Path, password: str = "") -> None:
    reader = open_reader(source, password)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    write_pdf(writer, target)


def compress_pdf(source: Path, target: Path, password: str = "") -> None:
    reader = open_reader(source, password)
    writer = PdfWriter()
    for page in reader.pages:
        page.compress_content_streams()
        writer.add_page(page)
    write_pdf(writer, target)


def extract_pdf_text(source: Path, target: Path, password: str = "") -> None:
    reader = open_reader(source, password)
    pieces = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pieces.append(f"--- Page {index} ---\n{text.strip()}\n")
    target.write_text("\n".join(pieces), encoding="utf-8")


def write_pdf_info(source: Path, target: Path, password: str = "") -> None:
    reader = open_reader(source, password)
    metadata = reader.metadata or {}
    lines = [
        "Victor PDF Tools Box - PDF Info",
        f"File: {source.name}",
        f"Pages: {len(reader.pages)}",
        f"Encrypted: {reader.is_encrypted}",
        "",
        "Metadata:",
    ]
    for key, value in metadata.items():
        lines.append(f"{key}: {value}")
    target.write_text("\n".join(lines), encoding="utf-8")


def ensure_pymupdf_available() -> None:
    if not PYMUPDF_AVAILABLE or fitz is None:
        raise ValueError("無痕文字替換需要 PyMuPDF（pymupdf）。")


def normalize_font_key(font_name: str) -> str:
    normalized = re.sub(r"^[A-Z0-9]{6}\+", "", font_name or "", flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "", normalized.lower())


def int_color_to_rgb(color: int) -> tuple[float, float, float]:
    if color == 0:
        return (0.0, 0.0, 0.0)
    return (
        ((color >> 16) & 255) / 255.0,
        ((color >> 8) & 255) / 255.0,
        (color & 255) / 255.0,
    )


WINDOWS_FONT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "helvetica": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "timesnewroman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "timesroman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "courier": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "couriernew": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "microsoftyahei": ("msyh.ttc", "msyhbd.ttc"),
    "yahei": ("msyh.ttc", "msyhbd.ttc"),
    "mingliu": ("mingliu.ttc", "mingliub.ttc"),
    "pmingliu": ("mingliu.ttc", "mingliub.ttc"),
    "simsun": ("simsun.ttc", "simsunb.ttf"),
    "nsimsun": ("simsun.ttc", "simsunb.ttf"),
    "simhei": ("simhei.ttf",),
    "calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf"),
    "verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
}


def _font_file_variant_index(bold: bool, italic: bool) -> int:
    if bold and italic:
        return 3
    if bold:
        return 1
    if italic:
        return 2
    return 0


def resolve_system_font_file(font_name: str, font_flags: int = 0) -> str:
    key = normalize_font_key(font_name)
    candidates = None
    for pattern, files in WINDOWS_FONT_CANDIDATES.items():
        if pattern in key or key in pattern:
            candidates = files
            break
    if candidates is None:
        if any(token in key for token in ("song", "ming", "kai", "hei", "yahei", "gothic", "mincho")):
            candidates = ("msyh.ttc", "mingliu.ttc", "simsun.ttc")
        else:
            candidates = WINDOWS_FONT_CANDIDATES["arial"]
    bold = bool(font_flags & 16)
    italic = bool(font_flags & 2)
    index = _font_file_variant_index(bold, italic)
    fonts_dir = Path("C:/Windows/Fonts")
    for offset in (0, 1, 2, 3):
        candidate_index = min(index + offset, len(candidates) - 1)
        path = fonts_dir / candidates[candidate_index]
        if path.exists():
            return str(path)
    fallback = fonts_dir / candidates[0]
    if fallback.exists():
        return str(fallback)
    return ""


def match_page_font_name(span_font: str, page_fonts: list[tuple]) -> str:
    span_key = normalize_font_key(span_font)
    if not span_key:
        return ""
    best_name = ""
    best_score = 0
    for _xref, _ext, _kind, basefont, name, _encoding in page_fonts:
        for candidate in (basefont, name):
            candidate_key = normalize_font_key(str(candidate))
            if not candidate_key:
                continue
            if candidate_key == span_key:
                return str(name)
            if candidate_key in span_key or span_key in candidate_key:
                score = min(len(candidate_key), len(span_key))
                if score > best_score:
                    best_score = score
                    best_name = str(name)
    return best_name


def span_to_text_block(span: dict, page_fonts: list[tuple]) -> TextBlock:
    text = (span.get("text") or "").replace("\u00a0", " ").strip()
    bbox = tuple(float(value) for value in span.get("bbox", (0, 0, 0, 0)))
    origin = span.get("origin") or (bbox[0], bbox[3])
    font_name = str(span.get("font") or "")
    font_flags = int(span.get("flags") or 0)
    font_size = float(span.get("size") or 12)
    page_font_name = match_page_font_name(font_name, page_fonts)
    font_file = resolve_system_font_file(font_name, font_flags)
    width = max(bbox[2] - bbox[0], font_size * 2.0)
    height = max(bbox[3] - bbox[1], font_size * 1.2)
    return TextBlock(
        text=text,
        x=float(origin[0]),
        y=float(origin[1]),
        width=width,
        height=height,
        font_size=font_size,
        font_name=font_name,
        color_rgb=int_color_to_rgb(int(span.get("color") or 0)),
        bbox=bbox,
        font_flags=font_flags,
        page_font_name=page_font_name,
        font_file=font_file,
    )


def extract_page_text_blocks_pymupdf(source: Path, page_index: int, password: str = "") -> list[TextBlock]:
    ensure_pymupdf_available()
    document = fitz.open(str(source))
    try:
        if document.is_encrypted:
            if not password or document.authenticate(password) == 0:
                raise ValueError(f"{source.name} 已加密，請輸入密碼。")
        if page_index < 0 or page_index >= document.page_count:
            raise ValueError("頁碼超出範圍。")
        page = document[page_index]
        page_fonts = page.get_fonts()
        blocks: list[TextBlock] = []
        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    item = span_to_text_block(span, page_fonts)
                    if item.text:
                        blocks.append(item)
        return merge_text_blocks(blocks)
    finally:
        document.close()


def extract_page_text_blocks_pypdf(source: Path, page_index: int, password: str = "") -> list[TextBlock]:
    reader = open_reader(source, password)
    if page_index < 0 or page_index >= len(reader.pages):
        raise ValueError("頁碼超出範圍。")

    blocks: list[TextBlock] = []

    def visitor_text(text, _cm, tm, font_dict, font_size):
        normalized = (text or "").strip()
        if not normalized:
            return
        x = float(tm[4])
        y = float(tm[5])
        size = float(font_size or 12)
        width = max(len(normalized) * size * 0.55, size * 2.0)
        height = max(size * 1.5, 12.0)
        font_name = ""
        if font_dict:
            font_name = str(font_dict.get("/BaseFont", ""))
        blocks.append(TextBlock(normalized, x, y, width, height, size, font_name))

    reader.pages[page_index].extract_text(visitor_text=visitor_text)
    return merge_text_blocks(blocks)


def extract_page_text_blocks(source: Path, page_index: int, password: str = "") -> list[TextBlock]:
    if PYMUPDF_AVAILABLE:
        try:
            return extract_page_text_blocks_pymupdf(source, page_index, password)
        except Exception:
            pass
    return extract_page_text_blocks_pypdf(source, page_index, password)


def text_block_redaction_rect(block: TextBlock, replacement: str = "") -> "fitz.Rect":
    ensure_pymupdf_available()
    padding = max(block.font_size * 0.15, 1.5)
    if block.bbox != (0.0, 0.0, 0.0, 0.0):
        rect = fitz.Rect(block.bbox)
    else:
        rect = fitz.Rect(
            block.x,
            block.y - block.height,
            block.x + block.width,
            block.y + max(block.font_size * 0.35, 4.0),
        )
    rect = rect + (-padding, -padding, padding, padding)
    if replacement:
        extra_width = max(len(replacement) - len(block.text.strip()), 0) * block.font_size * 0.55
        if extra_width > 0:
            rect.x1 += extra_width + padding
    return rect


def _insert_text_with_block_style(page, block: TextBlock, replacement: str, rect: "fitz.Rect") -> None:
    fontsize = max(block.font_size, 6.0)
    color = block.color_rgb
    kwargs: dict = {"fontsize": fontsize, "color": color, "align": fitz.TEXT_ALIGN_LEFT}
    if block.page_font_name:
        kwargs["fontname"] = block.page_font_name
    elif block.font_file:
        kwargs["fontfile"] = block.font_file
    else:
        kwargs["fontname"] = "helv"

    overflow = page.insert_textbox(rect, replacement, **kwargs)
    if overflow >= 0:
        return

    point = fitz.Point(block.x, block.y)
    insert_kwargs = {"fontsize": fontsize, "color": color}
    if block.page_font_name:
        insert_kwargs["fontname"] = block.page_font_name
    elif block.font_file:
        insert_kwargs["fontfile"] = block.font_file
    else:
        insert_kwargs["fontname"] = "helv"
    page.insert_text(point, replacement, **insert_kwargs)


def replace_text_block_seamless(
    source: Path,
    target: Path,
    page_index: int,
    block: TextBlock,
    replacement: str,
    password: str = "",
) -> None:
    """Remove the original text run and rewrite with matched font/size/color."""

    if not replacement.strip():
        raise ValueError("請輸入替換文字。")
    ensure_pymupdf_available()

    document = fitz.open(str(source))
    try:
        if document.is_encrypted:
            if not password or document.authenticate(password) == 0:
                raise ValueError(f"{source.name} 已加密，請輸入密碼。")
        if page_index < 0 or page_index >= document.page_count:
            raise ValueError("頁碼超出範圍。")

        page = document[page_index]
        replacement_text = replacement.strip()
        rect = text_block_redaction_rect(block, replacement_text)

        needle = block.text.strip()
        if needle:
            matches = page.search_for(needle)
            if matches:
                rect = matches[0]
                if replacement_text and len(replacement_text) > len(needle):
                    extra = (len(replacement_text) - len(needle)) * block.font_size * 0.55
                    rect.x1 += extra + max(block.font_size * 0.15, 1.5)

        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()

        _insert_text_with_block_style(page, block, replacement_text, rect)
        document.save(str(target), garbage=4, deflate=True)
    finally:
        document.close()


def replace_text_block_overlay(
    source: Path,
    target: Path,
    page_index: int,
    block: TextBlock,
    replacement: str,
    password: str = "",
) -> None:
    if not replacement.strip():
        raise ValueError("請輸入替換文字。")
    bold = "bold" in (block.font_name or "").lower()
    add_text_overlay_annotation(
        source=source,
        target=target,
        page_index=page_index,
        x=block.x,
        y=block.y,
        text=replacement,
        font_size=max(int(round(block.font_size)), 8),
        cover_original=True,
        cover_width=max(block.width + block.font_size * 0.8, len(replacement) * block.font_size * 0.65),
        cover_height=max(block.height, block.font_size * 1.8),
        password=password,
        font_key=font_key_for_pdf_font(block.font_name),
        bold=bold,
        color_rgb=block.color_rgb,
    )


def redact_text_block_overlay(
    source: Path,
    target: Path,
    page_index: int,
    block: TextBlock,
    password: str = "",
) -> None:
    reader = open_reader(source, password)
    if page_index < 0 or page_index >= len(reader.pages):
        raise ValueError("頁碼超出範圍。")

    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    page = writer.pages[page_index]
    add_annotation_to_page(writer, page, redaction_annotation_for_block(block))
    write_pdf(writer, target)


def redaction_annotation_for_block(block: TextBlock) -> DictionaryObject:
    padding = max(block.font_size * 0.2, 2.0)
    return DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Square"),
            NameObject("/Rect"): ArrayObject(
                [
                    FloatObject(block.x - padding),
                    FloatObject(block.y - block.height - padding),
                    FloatObject(block.x + block.width + padding),
                    FloatObject(block.y + padding),
                ]
            ),
            NameObject("/C"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(0)]),
            NameObject("/IC"): ArrayObject([FloatObject(0), FloatObject(0), FloatObject(0)]),
            NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
            NameObject("/F"): NumberObject(4),
        }
    )


def redact_matching_text_blocks_overlay(
    source: Path,
    target: Path,
    query: str,
    password: str = "",
    case_sensitive: bool = False,
    whole_word: bool = False,
) -> int:
    if not (query or "").strip():
        raise ValueError("請輸入要批量遮蔽的搜尋文字。")

    reader = open_reader(source, password)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    match_count = 0
    for page_index, page in enumerate(writer.pages):
        blocks = extract_page_text_blocks(source, page_index, password)
        for block in blocks:
            if text_matches_query(block.text, query, case_sensitive, whole_word):
                add_annotation_to_page(writer, page, redaction_annotation_for_block(block))
                match_count += 1
    if match_count == 0:
        raise ValueError(f"找不到要遮蔽的文字：{query.strip()}")
    write_pdf(writer, target)
    return match_count


def text_matches_query(text: str, query: str, case_sensitive: bool = False, whole_word: bool = False) -> bool:
    needle = (query or "").strip()
    if not needle:
        return False
    haystack = text or ""
    if whole_word:
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack, flags) is not None
    if case_sensitive:
        return needle in haystack
    return needle.lower() in haystack.lower()


def validate_content_stream_replacement(original: str, replacement: str) -> tuple[str, str]:
    old_text = re.sub(r"\s+", " ", original or "").strip()
    new_text = replacement.strip()
    if not old_text:
        raise ValueError("沒有可替換的原文字。")
    if not new_text:
        raise ValueError("請輸入替換文字。")
    if not re.fullmatch(r"[\x20-\x7E]+", old_text) or not re.fullmatch(r"[\x20-\x7E]+", new_text):
        raise ValueError("直接改內容流目前只支援簡單英文、數字和半形符號。")
    if len(old_text) != len(new_text):
        raise ValueError("直接改內容流目前要求新舊文字長度相同，以避免版面走位。")
    return old_text, new_text


def replace_text_in_show_operand(operand, old_text: str, new_text: str) -> tuple[object, bool]:
    if isinstance(operand, TextStringObject) and str(operand) == old_text:
        return TextStringObject(new_text), True
    if isinstance(operand, ByteStringObject):
        try:
            decoded = bytes(operand).decode("latin-1")
        except Exception:
            return operand, False
        if decoded == old_text:
            return ByteStringObject(new_text.encode("latin-1")), True
    return operand, False


def replace_text_in_array_operand(operand, old_text: str, new_text: str) -> tuple[object, bool]:
    if not isinstance(operand, ArrayObject):
        return operand, False
    string_parts = [part for part in operand if isinstance(part, (TextStringObject, ByteStringObject))]
    joined = "".join(str(part) if isinstance(part, TextStringObject) else bytes(part).decode("latin-1") for part in string_parts)
    if joined != old_text:
        return operand, False

    replaced = ArrayObject()
    offset = 0
    for part in operand:
        if isinstance(part, TextStringObject):
            length = len(str(part))
            replaced.append(TextStringObject(new_text[offset : offset + length]))
            offset += length
        elif isinstance(part, ByteStringObject):
            length = len(bytes(part))
            replaced.append(ByteStringObject(new_text[offset : offset + length].encode("latin-1")))
            offset += length
        else:
            replaced.append(part)
    return replaced, True


def replace_text_block_content_stream(
    source: Path,
    target: Path,
    page_index: int,
    block: TextBlock,
    replacement: str,
    password: str = "",
) -> None:
    old_text, new_text = validate_content_stream_replacement(block.text, replacement)
    replace_text_in_content_stream(source, target, page_index, old_text, new_text, password)


def replace_text_in_content_stream(
    source: Path,
    target: Path,
    page_index: int,
    old_text: str,
    new_text: str,
    password: str = "",
) -> None:
    reader = open_reader(source, password)
    if page_index < 0 or page_index >= len(reader.pages):
        raise ValueError("頁碼超出範圍。")

    writer = PdfWriter()
    replacements = 0
    for index, page in enumerate(reader.pages):
        page_copy = copy(page)
        if index == page_index:
            contents = page_copy.get_contents()
            if contents is None:
                raise ValueError("此頁沒有可修改的內容流。")
            content = ContentStream(contents, reader)
            new_operations = []
            for operands, operator in content.operations:
                operands = list(operands)
                replaced = False
                if operator in {b"Tj", b"'"} and operands:
                    operands[0], replaced = replace_text_in_show_operand(operands[0], old_text, new_text)
                elif operator == b'"' and len(operands) >= 3:
                    operands[2], replaced = replace_text_in_show_operand(operands[2], old_text, new_text)
                elif operator == b"TJ" and operands:
                    operands[0], replaced = replace_text_in_array_operand(operands[0], old_text, new_text)
                if replaced:
                    replacements += 1
                new_operations.append((operands, operator))
            if replacements != 1:
                raise ValueError("找不到唯一可直接修改的文字；請改用覆蓋方式。")
            content.operations = new_operations
            stream = DecodedStreamObject()
            stream.set_data(content.get_data())
            page_copy[NameObject("/Contents")] = stream
        writer.add_page(page_copy)
    write_pdf(writer, target)


def redact_text_block_secure(
    source: Path,
    target: Path,
    page_index: int,
    block: TextBlock,
    password: str = "",
) -> None:
    old_text = re.sub(r"\s+", " ", block.text or "").strip()
    if not old_text:
        raise ValueError("沒有可遮蔽的原文字。")
    if not re.fullmatch(r"[\x20-\x7E]+", old_text):
        raise ValueError("安全遮蔽目前只支援簡單英文、數字和半形符號。")
    with tempfile.TemporaryDirectory() as temp_dir:
        stripped_pdf = Path(temp_dir) / "redaction-content-removed.pdf"
        replace_text_in_content_stream(
            source,
            stripped_pdf,
            page_index,
            old_text,
            " " * len(old_text),
            password,
        )
        redact_text_block_overlay(stripped_pdf, target, page_index, block)


def font_key_for_pdf_font(font_name: str) -> str:
    normalized = (font_name or "").lower()
    if "times" in normalized or "roman" in normalized:
        return "times"
    if "courier" in normalized or "mono" in normalized:
        return "courier"
    return "helvetica"


def ensure_ocr_available() -> None:
    if not OCR_AVAILABLE or pytesseract is None:
        raise ValueError("OCR 需要安裝 pytesseract Python 套件和 Tesseract OCR。")
    try:
        pytesseract.get_tesseract_version()
    except TesseractNotFoundError as exc:
        raise ValueError(
            "找不到 Tesseract OCR 執行檔。請先安裝 Tesseract，或把 tesseract.exe 加入 PATH。"
        ) from exc


def selected_page_indexes(source: Path, password: str = "", pages_spec: str = "") -> list[int]:
    reader = open_reader(source, password)
    if (pages_spec or "").strip():
        return parse_pages(pages_spec, len(reader.pages))
    return list(range(len(reader.pages)))


def render_pdf_page_images(
    source: Path,
    password: str = "",
    pages_spec: str = "",
    dpi: int = 200,
) -> list[tuple[int, Image.Image]]:
    if not PDF_RENDER_AVAILABLE or pdfium is None:
        raise ValueError("PDF OCR 需要 pypdfium2 預覽元件。")
    if dpi < 72 or dpi > 600:
        raise ValueError("解析度請介於 72 至 600 DPI。")

    page_indexes = selected_page_indexes(source, password, pages_spec)
    if not page_indexes:
        raise ValueError("沒有可處理的頁面。")

    scale = dpi / 72.0
    images: list[tuple[int, Image.Image]] = []
    document = pdfium.PdfDocument(str(source), password=password or None)
    try:
        for page_index in page_indexes:
            page = document.get_page(page_index)
            try:
                image = page.render(scale=scale).to_pil().convert("RGB")
            finally:
                page.close()
            images.append((page_index, image))
    finally:
        document.close()
    return images


def ocr_pdf_to_text(
    source: Path,
    target: Path,
    password: str = "",
    language: str = "eng+chi_tra",
    pages_spec: str = "",
    dpi: int = 200,
) -> int:
    ensure_ocr_available()
    pieces: list[str] = []
    rendered_pages = render_pdf_page_images(source, password, pages_spec, dpi)
    for page_index, image in rendered_pages:
        text = pytesseract.image_to_string(image, lang=language)
        pieces.append(f"--- Page {page_index + 1} ---\n{text.strip()}\n")
        image.close()
    target.write_text("\n".join(pieces), encoding="utf-8")
    return len(rendered_pages)


def ocr_pdf_to_searchable_pdf(
    source: Path,
    target: Path,
    password: str = "",
    language: str = "eng+chi_tra",
    pages_spec: str = "",
    dpi: int = 200,
) -> int:
    ensure_ocr_available()
    writer = PdfWriter()
    rendered_pages = render_pdf_page_images(source, password, pages_spec, dpi)
    try:
        for _page_index, image in rendered_pages:
            pdf_bytes = pytesseract.image_to_pdf_or_hocr(
                image,
                extension="pdf",
                lang=language,
            )
            reader = PdfReader(io.BytesIO(pdf_bytes))
            for page in reader.pages:
                writer.add_page(page)
    finally:
        for _page_index, image in rendered_pages:
            image.close()
    write_pdf(writer, target)
    return len(rendered_pages)


IMAGE_EXPORT_FORMATS = {"png", "jpg", "jpeg", "webp"}


def _image_extension(image_format: str) -> str:
    normalized = (image_format or "png").lower()
    if normalized in {"jpg", "jpeg"}:
        return "jpg"
    if normalized == "webp":
        return "webp"
    return "png"


def _save_rendered_image(image: Image.Image, path: Path, image_format: str) -> None:
    normalized = (image_format or "png").lower()
    if normalized in {"jpg", "jpeg"}:
        image.save(path, format="JPEG", quality=92)
    elif normalized == "webp":
        image.save(path, format="WEBP", quality=90)
    else:
        image.save(path, format="PNG")


def pdf_to_images(
    source: Path,
    target: Path,
    password: str = "",
    image_format: str = "png",
    dpi: int = 200,
    pages_spec: str = "",
) -> int:
    if not PDF_RENDER_AVAILABLE or pdfium is None:
        raise ValueError("PDF 轉圖片需要 pypdfium2 預覽元件。")
    if dpi < 72 or dpi > 600:
        raise ValueError("解析度請介於 72 至 600 DPI。")

    page_indexes = selected_page_indexes(source, password, pages_spec)
    if not page_indexes:
        raise ValueError("沒有可輸出的頁面。")

    scale = dpi / 72.0
    extension = _image_extension(image_format)
    stem = safe_output_name(source.stem)

    def write_images(folder: Path) -> list[Path]:
        folder.mkdir(parents=True, exist_ok=True)
        generated: list[Path] = []
        document = pdfium.PdfDocument(str(source), password=password or None)
        try:
            for output_index, page_index in enumerate(page_indexes, start=1):
                page = document.get_page(page_index)
                try:
                    image = page.render(scale=scale).to_pil().convert("RGB")
                finally:
                    page.close()
                filename = safe_output_name(f"{stem}-page-{page_index + 1:04d}.{extension}")
                output_path = folder / filename
                _save_rendered_image(image, output_path, image_format)
                generated.append(output_path)
        finally:
            document.close()
        return generated

    if target.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory() as temp_dir:
            generated = write_images(Path(temp_dir))
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                for item in generated:
                    archive.write(item, item.name)
        return len(page_indexes)

    generated = write_images(target)
    return len(generated)


def images_to_pdf(paths: list[Path], target: Path) -> None:
    if not paths:
        raise ValueError("請選擇圖片。")
    converted: list[Image.Image] = []
    for image_path in paths:
        image = Image.open(image_path)
        if image.mode in {"RGBA", "P"}:
            image = image.convert("RGB")
        converted.append(image)
    first, rest = converted[0], converted[1:]
    first.save(target, save_all=True, append_images=rest, resolution=150.0)
    for image in converted:
        image.close()


ANNOTATION_FONT_OPTIONS = {
    "helvetica": ("Helv", "Helv-Bold"),
    "times": ("Times-Roman", "Times-Bold"),
    "courier": ("Courier", "Courier-Bold"),
}

ANNOTATION_COLOR_PRESETS: dict[str, tuple[float, float, float]] = {
    "black": (0.0, 0.0, 0.0),
    "red": (0.8, 0.0, 0.0),
    "blue": (0.0, 0.0, 0.7),
    "gray": (0.4, 0.4, 0.4),
}


def build_annotation_da(
    font_key: str,
    font_size: int,
    bold: bool,
    color_rgb: tuple[float, float, float],
) -> str:
    regular, bold_name = ANNOTATION_FONT_OPTIONS.get(font_key, ANNOTATION_FONT_OPTIONS["helvetica"])
    font_name = bold_name if bold else regular
    red, green, blue = color_rgb
    return f"/{font_name} {font_size} Tf {red} {green} {blue} rg"


def rgb_to_hex(color_rgb: tuple[float, float, float]) -> str:
    red, green, blue = color_rgb
    return "#{:02x}{:02x}{:02x}".format(
        int(max(0.0, min(red, 1.0)) * 255),
        int(max(0.0, min(green, 1.0)) * 255),
        int(max(0.0, min(blue, 1.0)) * 255),
    )


def add_annotation_to_page(writer: PdfWriter, page, annotation: DictionaryObject) -> None:
    annotation_ref = writer._add_object(annotation)
    if "/Annots" not in page:
        page[NameObject("/Annots")] = ArrayObject()
    page["/Annots"].append(annotation_ref)


def add_text_overlay_annotation(
    source: Path,
    target: Path,
    page_index: int,
    x: float,
    y: float,
    text: str,
    font_size: int,
    cover_original: bool,
    cover_width: float,
    cover_height: float,
    password: str = "",
    font_key: str = "helvetica",
    bold: bool = False,
    color_rgb: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> None:
    reader = open_reader(source, password)
    if page_index < 0 or page_index >= len(reader.pages):
        raise ValueError("頁碼超出範圍。")
    if not text.strip():
        raise ValueError("請輸入要加入的文字。")

    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    page = writer.pages[page_index]
    text_height = max(float(font_size) * 1.8, 24.0)
    rect_width = max(float(cover_width), 80.0)
    rect_height = max(float(cover_height), text_height)

    if cover_original:
        cover = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Square"),
                NameObject("/Rect"): ArrayObject(
                    [
                        FloatObject(x),
                        FloatObject(y - 4),
                        FloatObject(x + rect_width),
                        FloatObject(y + rect_height),
                    ]
                ),
                NameObject("/C"): ArrayObject([FloatObject(1), FloatObject(1), FloatObject(1)]),
                NameObject("/IC"): ArrayObject([FloatObject(1), FloatObject(1), FloatObject(1)]),
                NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
                NameObject("/F"): NumberObject(4),
            }
        )
        add_annotation_to_page(writer, page, cover)

    free_text = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/FreeText"),
            NameObject("/Rect"): ArrayObject(
                [
                    FloatObject(x),
                    FloatObject(y),
                    FloatObject(x + rect_width),
                    FloatObject(y + rect_height),
                ]
            ),
            NameObject("/Contents"): TextStringObject(text),
            NameObject("/DA"): TextStringObject(build_annotation_da(font_key, font_size, bold, color_rgb)),
            NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
            NameObject("/F"): NumberObject(4),
        }
    )
    add_annotation_to_page(writer, page, free_text)
    write_pdf(writer, target)


def add_page_numbers(source: Path, target: Path, template: str = "Page {page} of {total}", password: str = "") -> None:
    reader = open_reader(source, password)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    total = len(writer.pages)
    for index, page in enumerate(writer.pages, start=1):
        width = float(page.mediabox.width)
        text = template.format(page=index, total=total)
        rect_width = max(160.0, len(text) * 7.0)
        x = max((width - rect_width) / 2, 24.0)
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/FreeText"),
                NameObject("/Rect"): ArrayObject(
                    [FloatObject(x), FloatObject(20), FloatObject(x + rect_width), FloatObject(42)]
                ),
                NameObject("/Contents"): TextStringObject(text),
                NameObject("/DA"): TextStringObject("/Helv 10 Tf 0.25 0.25 0.25 rg"),
                NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
                NameObject("/F"): NumberObject(4),
            }
        )
        add_annotation_to_page(writer, page, annotation)
    write_pdf(writer, target)


def add_watermark(source: Path, target: Path, text: str, password: str = "") -> None:
    if not text.strip():
        raise ValueError("請輸入水印 / 印章文字。")
    reader = open_reader(source, password)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    for page in writer.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        rect_width = min(max(len(text) * 18.0, 240.0), max(width - 72.0, 180.0))
        rect_height = 70.0
        x = max((width - rect_width) / 2, 24.0)
        y = max((height - rect_height) / 2, 24.0)
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/FreeText"),
                NameObject("/Rect"): ArrayObject(
                    [FloatObject(x), FloatObject(y), FloatObject(x + rect_width), FloatObject(y + rect_height)]
                ),
                NameObject("/Contents"): TextStringObject(text),
                NameObject("/DA"): TextStringObject("/Helv 34 Tf 0.75 0.75 0.75 rg"),
                NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
                NameObject("/F"): NumberObject(4),
            }
        )
        add_annotation_to_page(writer, page, annotation)
    write_pdf(writer, target)


def rendered_page_is_blank(page, threshold: int) -> bool:
    if not PDF_RENDER_AVAILABLE or pdfium is None:
        raise ValueError("刪除空白頁需要 pypdfium2 預覽元件。")
    bitmap = page.render(scale=0.15)
    image = bitmap.to_pil().convert("L")
    non_white = 0
    for pixel in image.getdata():
        if pixel < 245:
            non_white += 1
            if non_white > threshold:
                return False
    return True


def remove_blank_pages(source: Path, target: Path, threshold: int = 25, password: str = "") -> int:
    reader = open_reader(source, password)
    document = pdfium.PdfDocument(str(source), password=password or None) if pdfium is not None else None
    writer = PdfWriter()
    removed = 0
    try:
        for index, source_page in enumerate(reader.pages):
            rendered_page = document.get_page(index)
            try:
                is_blank = rendered_page_is_blank(rendered_page, threshold)
            finally:
                rendered_page.close()
            if is_blank:
                removed += 1
            else:
                writer.add_page(source_page)
    finally:
        if document is not None:
            document.close()
    if not writer.pages:
        raise ValueError("所有頁面都被判定為空白，已取消輸出。")
    write_pdf(writer, target)
    return removed


def clean_metadata(source: Path, target: Path, password: str = "") -> None:
    reader = open_reader(source, password)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.add_metadata({"/Producer": "Victor PDF Tools Box"})
    write_pdf(writer, target)


@dataclass(frozen=True)
class BookmarkItem:
    title: str
    page_index: int
    level: int = 0


def extract_outline(source: Path, password: str = "") -> list[BookmarkItem]:
    """Return a flattened list of bookmarks with indentation levels."""

    reader = open_reader(source, password)
    page_count = len(reader.pages)
    items: list[BookmarkItem] = []

    def walk(entries, level: int) -> None:
        for entry in entries:
            if isinstance(entry, list):
                walk(entry, level + 1)
                continue
            title = str(getattr(entry, "title", "") or "").strip()
            try:
                page_index = reader.get_destination_page_number(entry)
            except Exception:
                page_index = None
            if page_index is None or page_index < 0:
                page_index = 0
            if page_count and page_index >= page_count:
                page_index = page_count - 1
            items.append(BookmarkItem(title or "(未命名書籤)", int(page_index), max(0, level)))

    try:
        outline = reader.outline
    except Exception:
        outline = []
    walk(outline, 0)
    return items


def apply_outline(source: Path, target: Path, items: list[BookmarkItem], password: str = "") -> None:
    """Rebuild the document outline from a flat list of bookmarks."""

    reader = open_reader(source, password)
    page_count = len(reader.pages)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    parents: dict[int, object] = {}
    for item in items:
        title = (item.title or "").strip() or "(未命名書籤)"
        page_index = item.page_index
        if page_index < 0:
            page_index = 0
        if page_count and page_index >= page_count:
            page_index = page_count - 1
        level = max(0, item.level)
        parent = parents.get(level - 1) if level > 0 else None
        ref = writer.add_outline_item(title, page_index, parent=parent)
        parents[level] = ref
        for deeper in [key for key in parents if key > level]:
            del parents[deeper]

    write_pdf(writer, target)


# --- markup annotations (highlight / shapes / sticky notes) ------------------

MARKUP_KINDS = (
    "highlight",
    "underline",
    "strikeout",
    "rect",
    "ellipse",
    "line",
    "arrow",
    "note",
)

MARKUP_SUBTYPES = {
    "highlight": "/Highlight",
    "underline": "/Underline",
    "strikeout": "/StrikeOut",
    "rect": "/Square",
    "ellipse": "/Circle",
    "line": "/Line",
    "arrow": "/Line",
    "note": "/Text",
}

MARKUP_COLOR_PRESETS: dict[str, tuple[float, float, float]] = {
    "yellow": (1.0, 0.92, 0.23),
    "green": (0.45, 0.86, 0.45),
    "blue": (0.40, 0.74, 1.0),
    "pink": (1.0, 0.58, 0.79),
    "red": (0.88, 0.16, 0.16),
    "black": (0.0, 0.0, 0.0),
}


@dataclass(frozen=True)
class MarkupAnnotation:
    """A markup placed on a page, in PDF user space (origin bottom-left).

    For rectangle-like markups (highlight/underline/strikeout/rect/ellipse) the
    two points are opposite corners. For line/arrow they are the endpoints. For
    a sticky note only (x0, y0) is used as the anchor point.
    """

    kind: str
    x0: float
    y0: float
    x1: float
    y1: float
    color_rgb: tuple[float, float, float] = (1.0, 0.92, 0.23)
    contents: str = ""


def _normalized_rect(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _color_array(color_rgb: tuple[float, float, float]) -> ArrayObject:
    red, green, blue = color_rgb
    return ArrayObject([FloatObject(red), FloatObject(green), FloatObject(blue)])


def build_markup_annotation(markup: MarkupAnnotation) -> DictionaryObject:
    kind = markup.kind
    if kind not in MARKUP_SUBTYPES:
        raise ValueError(f"未知的標註類型：{kind}")
    color = _color_array(markup.color_rgb)

    if kind in {"highlight", "underline", "strikeout"}:
        left, bottom, right, top = _normalized_rect(markup.x0, markup.y0, markup.x1, markup.y1)
        quad = ArrayObject(
            [
                FloatObject(left),
                FloatObject(top),
                FloatObject(right),
                FloatObject(top),
                FloatObject(left),
                FloatObject(bottom),
                FloatObject(right),
                FloatObject(bottom),
            ]
        )
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject(MARKUP_SUBTYPES[kind]),
                NameObject("/Rect"): ArrayObject(
                    [FloatObject(left), FloatObject(bottom), FloatObject(right), FloatObject(top)]
                ),
                NameObject("/QuadPoints"): quad,
                NameObject("/C"): color,
                NameObject("/F"): NumberObject(4),
            }
        )
        if markup.contents:
            annotation[NameObject("/Contents")] = TextStringObject(markup.contents)
        return annotation

    if kind in {"rect", "ellipse"}:
        left, bottom, right, top = _normalized_rect(markup.x0, markup.y0, markup.x1, markup.y1)
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject(MARKUP_SUBTYPES[kind]),
                NameObject("/Rect"): ArrayObject(
                    [FloatObject(left), FloatObject(bottom), FloatObject(right), FloatObject(top)]
                ),
                NameObject("/C"): color,
                NameObject("/BS"): DictionaryObject(
                    {NameObject("/W"): NumberObject(2), NameObject("/S"): NameObject("/S")}
                ),
                NameObject("/F"): NumberObject(4),
            }
        )
        if markup.contents:
            annotation[NameObject("/Contents")] = TextStringObject(markup.contents)
        return annotation

    if kind in {"line", "arrow"}:
        left, bottom, right, top = _normalized_rect(markup.x0, markup.y0, markup.x1, markup.y1)
        padding = 6.0
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Line"),
                NameObject("/L"): ArrayObject(
                    [
                        FloatObject(markup.x0),
                        FloatObject(markup.y0),
                        FloatObject(markup.x1),
                        FloatObject(markup.y1),
                    ]
                ),
                NameObject("/Rect"): ArrayObject(
                    [
                        FloatObject(left - padding),
                        FloatObject(bottom - padding),
                        FloatObject(right + padding),
                        FloatObject(top + padding),
                    ]
                ),
                NameObject("/C"): color,
                NameObject("/BS"): DictionaryObject({NameObject("/W"): NumberObject(2)}),
                NameObject("/F"): NumberObject(4),
            }
        )
        if kind == "arrow":
            annotation[NameObject("/LE")] = ArrayObject([NameObject("/None"), NameObject("/OpenArrow")])
        if markup.contents:
            annotation[NameObject("/Contents")] = TextStringObject(markup.contents)
        return annotation

    # sticky note
    size = 18.0
    annotation = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Text"),
            NameObject("/Rect"): ArrayObject(
                [
                    FloatObject(markup.x0),
                    FloatObject(markup.y0 - size),
                    FloatObject(markup.x0 + size),
                    FloatObject(markup.y0),
                ]
            ),
            NameObject("/Contents"): TextStringObject(markup.contents or "備註"),
            NameObject("/Name"): NameObject("/Comment"),
            NameObject("/Open"): BooleanObject(False),
            NameObject("/C"): color,
            NameObject("/F"): NumberObject(4),
        }
    )
    return annotation


def apply_markup_annotations(
    source: Path,
    target: Path,
    markups: list[tuple[int, MarkupAnnotation]],
    password: str = "",
) -> int:
    if not markups:
        raise ValueError("請先加入至少一個標註。")
    reader = open_reader(source, password)
    page_count = len(reader.pages)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    applied = 0
    for page_index, markup in markups:
        if page_index < 0 or page_index >= page_count:
            continue
        add_annotation_to_page(writer, writer.pages[page_index], build_markup_annotation(markup))
        applied += 1
    if applied == 0:
        raise ValueError("沒有可套用的標註。")
    write_pdf(writer, target)
    return applied


# --- page cropping -----------------------------------------------------------

def crop_pdf_pages(
    source: Path,
    target: Path,
    rect: tuple[float, float, float, float],
    pages_spec: str = "",
    password: str = "",
) -> int:
    """Crop selected pages to ``rect`` (left, bottom, right, top) in PDF points.

    The rectangle is the area to keep and is clamped to each page's media box.
    """

    left, bottom, right, top = rect
    if right <= left or top <= bottom:
        raise ValueError("裁切範圍無效，請重新框選或輸入正確數值。")

    reader = open_reader(source, password)
    page_count = len(reader.pages)
    selected = (
        set(parse_pages(pages_spec, page_count))
        if (pages_spec or "").strip()
        else set(range(page_count))
    )
    if not selected:
        raise ValueError("沒有要裁切的頁面。")

    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    cropped = 0
    for index, page in enumerate(writer.pages):
        if index not in selected:
            continue
        media = page.mediabox
        new_left = max(left, float(media.left))
        new_bottom = max(bottom, float(media.bottom))
        new_right = min(right, float(media.right))
        new_top = min(top, float(media.top))
        if new_right <= new_left or new_top <= new_bottom:
            continue
        box = RectangleObject([new_left, new_bottom, new_right, new_top])
        page.cropbox = box
        page.trimbox = box
        cropped += 1
    if cropped == 0:
        raise ValueError("裁切範圍與頁面沒有重疊，未輸出任何頁面。")
    write_pdf(writer, target)
    return cropped


# --- advanced split ----------------------------------------------------------

def parse_page_groups(spec: str, page_count: int) -> list[list[int]]:
    """Parse a spec where each comma-separated part becomes its own group.

    Example: ``"1-3,4-6,7"`` -> ``[[0,1,2], [3,4,5], [6]]``.
    """

    spec = (spec or "").strip()
    if not spec:
        raise ValueError("請輸入範圍，例如 1-3,4-6,7-9。")
    groups: list[list[int]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"頁碼範圍不正確：{part}")
            pages = list(range(start - 1, end))
        else:
            pages = [int(part) - 1]
        for page in pages:
            if page < 0 or page >= page_count:
                raise ValueError(f"頁碼超出範圍：{page + 1}，目前共有 {page_count} 頁。")
        groups.append(pages)
    if not groups:
        raise ValueError("沒有有效的拆分範圍。")
    return groups


def split_pdf_advanced(
    source: Path,
    target_zip: Path,
    mode: str,
    value: str,
    password: str = "",
) -> int:
    """Split a PDF into multiple files inside a ZIP.

    ``mode="every"`` groups every ``value`` pages into one file. ``mode="ranges"``
    treats ``value`` as a comma list where each part becomes one output file.
    Returns the number of output PDFs.
    """

    reader = open_reader(source, password)
    page_count = len(reader.pages)
    if page_count == 0:
        raise ValueError("PDF 沒有頁面可拆分。")

    if mode == "every":
        try:
            size = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError("請輸入每檔頁數（正整數）。")
        if size < 1:
            raise ValueError("每檔頁數必須至少為 1。")
        groups = [list(range(start, min(start + size, page_count))) for start in range(0, page_count, size)]
    elif mode == "ranges":
        groups = parse_page_groups(value, page_count)
    else:
        raise ValueError(f"未知的拆分模式：{mode}")

    stem = safe_output_name(source.stem)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        generated: list[Path] = []
        for part_index, pages in enumerate(groups, start=1):
            if not pages:
                continue
            writer = PdfWriter()
            for page_index in pages:
                writer.add_page(reader.pages[page_index])
            first = pages[0] + 1
            last = pages[-1] + 1
            label = f"{first}" if first == last else f"{first}-{last}"
            part = temp_path / safe_output_name(f"{part_index:03d}-{stem}-pages-{label}.pdf")
            write_pdf(writer, part)
            generated.append(part)
        if not generated:
            raise ValueError("沒有可輸出的拆分檔案。")
        with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in generated:
                archive.write(item, item.name)
    return len(generated)


# --- Bates numbering ---------------------------------------------------------

BATES_POSITIONS = {
    "bottom-right": "右下",
    "bottom-left": "左下",
    "top-right": "右上",
    "top-left": "左上",
}


def add_bates_numbering(
    source: Path,
    target: Path,
    prefix: str = "",
    start: int = 1,
    digits: int = 6,
    suffix: str = "",
    position: str = "bottom-right",
    password: str = "",
) -> int:
    """Stamp sequential Bates numbers (e.g. ABC-000001) on every page."""

    if digits < 1 or digits > 12:
        raise ValueError("位數請介於 1 至 12。")
    if position not in BATES_POSITIONS:
        raise ValueError("不支援的 Bates 位置。")

    reader = open_reader(source, password)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    for index, page in enumerate(writer.pages):
        number = start + index
        text = f"{prefix}{number:0{digits}d}{suffix}"
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        rect_width = max(120.0, len(text) * 8.0)
        margin = 24.0
        if position.endswith("right"):
            x = max(width - rect_width - margin, margin)
        else:
            x = margin
        if position.startswith("bottom"):
            y = margin
        else:
            y = max(height - margin - 18.0, margin)
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/FreeText"),
                NameObject("/Rect"): ArrayObject(
                    [FloatObject(x), FloatObject(y), FloatObject(x + rect_width), FloatObject(y + 20)]
                ),
                NameObject("/Contents"): TextStringObject(text),
                NameObject("/DA"): TextStringObject("/Helv 10 Tf 0.1 0.1 0.1 rg"),
                NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
                NameObject("/F"): NumberObject(4),
            }
        )
        add_annotation_to_page(writer, page, annotation)
    write_pdf(writer, target)
    return len(writer.pages)


# --- permission control ------------------------------------------------------

def encrypt_pdf_with_permissions(
    source: Path,
    target: Path,
    owner_password: str,
    allow_print: bool = True,
    allow_copy: bool = True,
    allow_modify: bool = True,
    user_password: str = "",
    password: str = "",
) -> None:
    """Encrypt with an owner password and restrict printing/copying/modifying.

    ``user_password`` (empty by default) lets recipients open the file without a
    password while still being bound by the permission flags.
    """

    if not owner_password:
        raise ValueError("請輸入擁有者密碼（用來鎖定權限）。")

    reader = open_reader(source, password)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    permissions = UserAccessPermissions(0)
    if allow_print:
        permissions |= UserAccessPermissions.PRINT | UserAccessPermissions.PRINT_TO_REPRESENTATION
    if allow_copy:
        permissions |= (
            UserAccessPermissions.EXTRACT | UserAccessPermissions.EXTRACT_TEXT_AND_GRAPHICS
        )
    if allow_modify:
        permissions |= (
            UserAccessPermissions.MODIFY
            | UserAccessPermissions.ADD_OR_MODIFY
            | UserAccessPermissions.FILL_FORM_FIELDS
            | UserAccessPermissions.ASSEMBLE_DOC
        )

    writer.encrypt(
        user_password=user_password,
        owner_password=owner_password,
        permissions_flag=permissions,
    )
    write_pdf(writer, target)


# --- Adobe-Pro-like page / stamp / compare / bookmark tools ------------------

TEXT_MARKUP_KINDS = frozenset({"highlight", "underline", "strikeout"})


def _resolve_page_indexes(reader: PdfReader, pages_spec: str) -> list[int]:
    if (pages_spec or "").strip():
        return parse_pages(pages_spec, len(reader.pages))
    return list(range(len(reader.pages)))


def _pymupdf_search_rects(page, query: str, case_sensitive: bool = False) -> list:
    needle = (query or "").strip()
    if not needle:
        return []
    if case_sensitive:
        return page.search_for(needle)
    rects: list = []
    for x0, y0, x1, y1, word, *_rest in page.get_text("words"):
        if needle.lower() in word.lower():
            rects.append(fitz.Rect(x0, y0, x1, y1))
    if rects:
        return rects
    return page.search_for(needle)


def insert_pdf_pages(
    source: Path,
    insert_from: Path,
    target: Path,
    at_index: int,
    pages_spec: str = "",
    password: str = "",
    insert_password: str = "",
) -> int:
    """Insert pages from ``insert_from`` into ``source`` at ``at_index`` (0-based)."""

    source_reader = open_reader(source, password)
    insert_reader = open_reader(insert_from, insert_password)
    source_count = len(source_reader.pages)
    if at_index < 0 or at_index > source_count:
        raise ValueError(f"插入位置超出範圍：{at_index + 1}，目前共有 {source_count} 頁。")

    insert_indexes = _resolve_page_indexes(insert_reader, pages_spec)
    if not insert_indexes:
        raise ValueError("沒有可插入的頁面。")

    writer = PdfWriter()
    for index in range(at_index):
        writer.add_page(source_reader.pages[index])
    for index in insert_indexes:
        writer.add_page(insert_reader.pages[index])
    for index in range(at_index, source_count):
        writer.add_page(source_reader.pages[index])
    write_pdf(writer, target)
    return len(insert_indexes)


def replace_pdf_pages(
    source: Path,
    replacement: Path,
    target: Path,
    start_index: int,
    pages_spec: str = "",
    password: str = "",
    replacement_password: str = "",
) -> int:
    """Replace consecutive pages in ``source`` with pages from ``replacement``."""

    source_reader = open_reader(source, password)
    replacement_reader = open_reader(replacement, replacement_password)
    source_count = len(source_reader.pages)
    replacement_indexes = _resolve_page_indexes(replacement_reader, pages_spec)
    if not replacement_indexes:
        raise ValueError("沒有可替換的頁面。")

    replace_count = len(replacement_indexes)
    if start_index < 0 or start_index >= source_count:
        raise ValueError(f"替換起始位置超出範圍：{start_index + 1}，目前共有 {source_count} 頁。")
    if start_index + replace_count > source_count:
        raise ValueError(
            f"替換範圍超出文件頁數：需 {replace_count} 頁，從第 {start_index + 1} 頁起不足。"
        )

    writer = PdfWriter()
    for index in range(start_index):
        writer.add_page(source_reader.pages[index])
    for index in replacement_indexes:
        writer.add_page(replacement_reader.pages[index])
    for index in range(start_index + replace_count, source_count):
        writer.add_page(source_reader.pages[index])
    write_pdf(writer, target)
    return replace_count


def add_image_stamp(
    source: Path,
    target: Path,
    image_path: Path,
    page_index: int,
    x: float,
    y: float,
    width: float,
    height: float,
    password: str = "",
) -> None:
    """Place an image stamp/signature on a page using PyMuPDF."""

    ensure_pymupdf_available()
    image_path = Path(image_path)
    if not image_path.exists():
        raise ValueError(f"找不到圖片檔案：{image_path.name}")

    document = fitz.open(str(source))
    try:
        if document.is_encrypted:
            if not password or document.authenticate(password) == 0:
                raise ValueError(f"{source.name} 已加密，請輸入密碼。")
        if page_index < 0 or page_index >= document.page_count:
            raise ValueError("頁碼超出範圍。")
        page = document[page_index]
        rect = fitz.Rect(x, y, x + width, y + height)
        page.insert_image(rect, filename=str(image_path))
        document.save(str(target), garbage=4, deflate=True)
    finally:
        document.close()


def add_signature_image(
    source: Path,
    target: Path,
    image_path: Path,
    page_index: int,
    x: float,
    y: float,
    width: float,
    height: float,
    password: str = "",
) -> None:
    """Alias for :func:`add_image_stamp` — place a signature image on a page."""

    add_image_stamp(source, target, image_path, page_index, x, y, width, height, password)


def add_text_stamp(
    source: Path,
    target: Path,
    text: str,
    page_index: int,
    x: float,
    y: float,
    width: float,
    height: float,
    color_rgb: tuple[float, float, float] = (0.8, 0.0, 0.0),
    password: str = "",
) -> None:
    """Draw a bordered text stamp on a PDF page using PyMuPDF."""

    ensure_pymupdf_available()
    stamp_text = (text or "").strip()
    if not stamp_text:
        raise ValueError("圖章文字不可為空。")

    document = fitz.open(str(source))
    try:
        if document.is_encrypted:
            if not password or document.authenticate(password) == 0:
                raise ValueError(f"{source.name} 已加密，請輸入密碼。")
        if page_index < 0 or page_index >= document.page_count:
            raise ValueError("頁碼超出範圍。")
        page = document[page_index]
        rect = fitz.Rect(x, y, x + width, y + height)
        page.draw_rect(rect, color=color_rgb, width=2)
        fontsize = max(8.0, min(height * 0.55, width / max(len(stamp_text), 1) * 0.75))
        rc = page.insert_textbox(
            rect,
            stamp_text,
            fontsize=fontsize,
            color=color_rgb,
            align=fitz.TEXT_ALIGN_CENTER,
        )
        if rc < 0:
            page.insert_textbox(
                rect,
                stamp_text,
                fontsize=max(6.0, fontsize * 0.7),
                color=color_rgb,
                align=fitz.TEXT_ALIGN_CENTER,
            )
        document.save(str(target), garbage=4, deflate=True)
    finally:
        document.close()


def compress_pdf_advanced(
    source: Path,
    target: Path,
    image_dpi: int = 100,
    jpeg_quality: int = 60,
    password: str = "",
) -> tuple[int, int]:
    """Re-write a PDF with embedded images re-sampled via PyMuPDF."""

    ensure_pymupdf_available()
    old_size = source.stat().st_size if source.exists() else 0
    document = fitz.open(str(source))
    try:
        if document.is_encrypted:
            if not password or document.authenticate(password) == 0:
                raise ValueError(f"{source.name} 已加密，請輸入密碼。")
        document.rewrite_images(
            dpi_threshold=image_dpi,
            dpi_target=image_dpi,
            quality=jpeg_quality,
            lossy=True,
        )
        document.save(str(target), garbage=4, deflate=True, clean=True)
    finally:
        document.close()
    new_size = target.stat().st_size if target.exists() else 0
    return old_size, new_size


def compare_pdf_text(
    left: Path,
    right: Path,
    target_report: Path,
    left_password: str = "",
    right_password: str = "",
) -> int:
    """Write a UTF-8 page-by-page text comparison report; return differing page count."""

    left_reader = open_reader(left, left_password)
    right_reader = open_reader(right, right_password)
    left_count = len(left_reader.pages)
    right_count = len(right_reader.pages)
    max_pages = max(left_count, right_count)
    diff_count = 0
    lines = [
        "Victor PDF Tools Box - Text Compare",
        f"Left: {left.name}",
        f"Right: {right.name}",
        "",
    ]

    for index in range(max_pages):
        left_text = (
            (left_reader.pages[index].extract_text() or "").strip() if index < left_count else ""
        )
        right_text = (
            (right_reader.pages[index].extract_text() or "").strip()
            if index < right_count
            else ""
        )
        if left_text != right_text:
            diff_count += 1
            lines.append(f"--- Page {index + 1} DIFF ---")
            lines.append("[Left]")
            lines.append(left_text or "(empty)")
            lines.append("[Right]")
            lines.append(right_text or "(empty)")
            lines.append("")

    if diff_count == 0:
        lines.append("All pages match.")
    target_report.write_text("\n".join(lines), encoding="utf-8")
    return diff_count


def split_pdf_by_bookmarks(source: Path, target_zip: Path, password: str = "") -> int:
    """Split a PDF into one file per top-level bookmark range, packed in a ZIP."""

    reader = open_reader(source, password)
    page_count = len(reader.pages)
    items = extract_outline(source, password)
    top_level = [item for item in items if item.level == 0]
    if not top_level:
        raise ValueError("PDF 沒有書籤，無法依書籤拆分。")

    sorted_items = sorted(top_level, key=lambda item: item.page_index)
    ranges: list[tuple[str, int, int]] = []
    for index, item in enumerate(sorted_items):
        start = item.page_index
        if index + 1 < len(sorted_items):
            end = sorted_items[index + 1].page_index - 1
        else:
            end = page_count - 1
        if end < start:
            end = start
        ranges.append((item.title, start, end))

    stem = safe_output_name(source.stem)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        generated: list[Path] = []
        for part_index, (title, start, end) in enumerate(ranges, start=1):
            writer = PdfWriter()
            for page_index in range(start, end + 1):
                writer.add_page(reader.pages[page_index])
            part = temp_path / safe_output_name(f"{part_index:03d}-{stem}-{title}.pdf")
            write_pdf(writer, part)
            generated.append(part)
        with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in generated:
                archive.write(item, item.name)
    return len(generated)


def apply_text_markups_for_query(
    source: Path,
    target: Path,
    query: str,
    kind: str = "highlight",
    color_rgb: tuple[float, float, float] = (1.0, 0.92, 0.23),
    password: str = "",
    case_sensitive: bool = False,
) -> int:
    """Search for ``query`` and add highlight/underline/strikeout annotations."""

    if not (query or "").strip():
        raise ValueError("請輸入要標註的搜尋文字。")
    if kind not in TEXT_MARKUP_KINDS:
        raise ValueError(f"不支援的標註類型：{kind}，請使用 highlight、underline 或 strikeout。")
    ensure_pymupdf_available()

    annot_adders = {
        "highlight": lambda page, rect: page.add_highlight_annot(rect),
        "underline": lambda page, rect: page.add_underline_annot(rect),
        "strikeout": lambda page, rect: page.add_strikeout_annot(rect),
    }
    add_annot = annot_adders[kind]

    document = fitz.open(str(source))
    match_count = 0
    try:
        if document.is_encrypted:
            if not password or document.authenticate(password) == 0:
                raise ValueError(f"{source.name} 已加密，請輸入密碼。")
        for page in document:
            for rect in _pymupdf_search_rects(page, query, case_sensitive):
                annotation = add_annot(page, rect)
                if annotation is not None:
                    annotation.set_colors(stroke=color_rgb)
                    annotation.update()
                    match_count += 1
        document.save(str(target), garbage=4, deflate=True)
    finally:
        document.close()
    return match_count


def flatten_form_fields(source: Path, target: Path, password: str = "") -> int:
    """Flatten PDF form widgets into page content when present."""

    ensure_pymupdf_available()
    document = fitz.open(str(source))
    field_count = 0
    try:
        if document.is_encrypted:
            if not password or document.authenticate(password) == 0:
                raise ValueError(f"{source.name} 已加密，請輸入密碼。")
        for page in document:
            for _widget in page.widgets() or []:
                field_count += 1
        if field_count:
            document.bake(widgets=True, annots=False)
        document.save(str(target), garbage=4, deflate=True)
    finally:
        document.close()
    return field_count


def secure_redact_query(
    source: Path,
    target: Path,
    query: str,
    password: str = "",
    case_sensitive: bool = False,
) -> int:
    """Search for ``query`` and permanently redact all matches via PyMuPDF."""

    if not (query or "").strip():
        raise ValueError("請輸入要遮蔽的搜尋文字。")
    ensure_pymupdf_available()

    document = fitz.open(str(source))
    match_count = 0
    try:
        if document.is_encrypted:
            if not password or document.authenticate(password) == 0:
                raise ValueError(f"{source.name} 已加密，請輸入密碼。")
        for page in document:
            rects = _pymupdf_search_rects(page, query, case_sensitive)
            for rect in rects:
                page.add_redact_annot(rect, fill=(0, 0, 0))
                match_count += 1
            if rects:
                page.apply_redactions()
        if match_count == 0:
            raise ValueError(f"找不到要遮蔽的文字：{query.strip()}")
        document.save(str(target), garbage=4, deflate=True)
    finally:
        document.close()
    return match_count
