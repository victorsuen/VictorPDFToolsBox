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
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    ContentStream,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
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


def block_right(block: TextBlock) -> float:
    return block.x + block.width


def block_bottom(block: TextBlock) -> float:
    return block.y - block.height


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


def extract_page_text_blocks(source: Path, page_index: int, password: str = "") -> list[TextBlock]:
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
) -> int:
    normalized_query = (query or "").strip().lower()
    if not normalized_query:
        raise ValueError("請輸入要批量遮蔽的搜尋文字。")

    reader = open_reader(source, password)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    match_count = 0
    for page_index, page in enumerate(writer.pages):
        blocks = extract_page_text_blocks(source, page_index, password)
        for block in blocks:
            if normalized_query in block.text.lower():
                add_annotation_to_page(writer, page, redaction_annotation_for_block(block))
                match_count += 1
    if match_count == 0:
        raise ValueError(f"找不到要遮蔽的文字：{query.strip()}")
    write_pdf(writer, target)
    return match_count


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
