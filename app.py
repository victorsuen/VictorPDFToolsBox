from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from PIL import Image
from pypdf import PdfReader, PdfWriter

from pdf_core import pdf_to_images


BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / "workspace"
UPLOAD_DIR = WORK_DIR / "uploads"
OUTPUT_DIR = WORK_DIR / "outputs"
MAX_UPLOAD_MB = 250

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("VICTOR_PDF_SECRET", "local-dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


@dataclass(frozen=True)
class ToolCard:
    slug: str
    title: str
    description: str
    file_label: str
    multiple: bool = False
    accepts_images: bool = False


TOOLS = [
    ToolCard("merge", "合併 PDF", "把多份 PDF 按上傳次序合併成一份。", "PDF files", True),
    ToolCard("split", "逐頁拆分", "把每一頁拆成獨立 PDF，並打包成 ZIP。", "PDF file"),
    ToolCard("extract", "抽取頁碼", "輸入頁碼或範圍，例如 1,3,5-8。", "PDF file"),
    ToolCard("delete", "刪除頁碼", "刪除指定頁碼後輸出新 PDF。", "PDF file"),
    ToolCard("rotate", "旋轉頁面", "全部或指定頁面旋轉 90 / 180 / 270 度。", "PDF file"),
    ToolCard("encrypt", "加密 PDF", "用密碼保護 PDF，適合敏感文件傳閱。", "PDF file"),
    ToolCard("decrypt", "解除密碼", "輸入已知密碼後輸出未加密版本。", "PDF file"),
    ToolCard("compress", "基礎壓縮", "壓縮內容 stream；不會上傳外部服務。", "PDF file"),
    ToolCard("extract_text", "抽取文字", "把 PDF 可讀文字抽出成 TXT。", "PDF file"),
    ToolCard("images_to_pdf", "圖片轉 PDF", "把 JPG / PNG / TIFF 等圖片合併成 PDF。", "Image files", True, True),
    ToolCard("pdf_to_images", "PDF 轉圖片", "把 PDF 頁面輸出成 PNG 圖片，並打包成 ZIP。", "PDF file"),
    ToolCard("info", "PDF 資訊", "查看頁數、是否加密、文件 metadata。", "PDF file"),
]


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def clean_filename(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(name).name).strip()
    return safe or f"file-{uuid4().hex}"


def save_uploaded_files(field_name: str, allowed_extensions: set[str]) -> list[Path]:
    ensure_dirs()
    files = request.files.getlist(field_name)
    saved: list[Path] = []
    for item in files:
        if not item or not item.filename:
            continue
        suffix = Path(item.filename).suffix.lower()
        if suffix not in allowed_extensions:
            raise ValueError(f"不支援的檔案格式：{item.filename}")
        target = UPLOAD_DIR / f"{uuid4().hex}-{clean_filename(item.filename)}"
        item.save(target)
        saved.append(target)
    if not saved:
        raise ValueError("請先選擇檔案。")
    return saved


def output_path(filename: str) -> Path:
    ensure_dirs()
    return OUTPUT_DIR / f"{uuid4().hex}-{clean_filename(filename)}"


def first_pdf() -> Path:
    return save_uploaded_files("files", PDF_EXTENSIONS)[0]


def open_reader(path: Path, password: str | None = None) -> PdfReader:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        if not password:
            raise ValueError("PDF 已加密，請輸入密碼。")
        result = reader.decrypt(password)
        if result == 0:
            raise ValueError("密碼不正確，無法讀取 PDF。")
    return reader


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
            raise ValueError(f"頁碼超出範圍：{page + 1}，本文件共有 {page_count} 頁。")
        if page not in deduped:
            deduped.append(page)
    return deduped


def copy_pages(reader: PdfReader, page_indexes: Iterable[int]) -> PdfWriter:
    writer = PdfWriter()
    for index in page_indexes:
        writer.add_page(reader.pages[index])
    return writer


def write_pdf(writer: PdfWriter, filename: str) -> Path:
    target = output_path(filename)
    with target.open("wb") as stream:
        writer.write(stream)
    return target


def send_output(path: Path, download_name: str):
    return send_file(path, as_attachment=True, download_name=download_name)


def build_zip(files: list[Path], filename: str) -> Path:
    target = output_path(filename)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in files:
            archive.write(item, item.name)
    return target


def handle_merge() -> tuple[Path, str]:
    pdfs = save_uploaded_files("files", PDF_EXTENSIONS)
    if len(pdfs) < 2:
        raise ValueError("合併 PDF 至少需要兩個檔案。")
    writer = PdfWriter()
    for pdf in pdfs:
        reader = open_reader(pdf, request.form.get("password") or None)
        for page in reader.pages:
            writer.add_page(page)
    return write_pdf(writer, "merged.pdf"), "merged.pdf"


def handle_split() -> tuple[Path, str]:
    pdf = first_pdf()
    reader = open_reader(pdf, request.form.get("password") or None)
    generated: list[Path] = []
    with tempfile.TemporaryDirectory(dir=OUTPUT_DIR) as temp_dir:
        temp_path = Path(temp_dir)
        for index, page in enumerate(reader.pages, start=1):
            writer = PdfWriter()
            writer.add_page(page)
            part = temp_path / f"page-{index:04d}.pdf"
            with part.open("wb") as stream:
                writer.write(stream)
            generated.append(part)
        zip_path = build_zip(generated, "split-pages.zip")
    return zip_path, "split-pages.zip"


def handle_extract() -> tuple[Path, str]:
    pdf = first_pdf()
    reader = open_reader(pdf, request.form.get("password") or None)
    pages = parse_pages(request.form.get("pages", ""), len(reader.pages))
    return write_pdf(copy_pages(reader, pages), "extracted-pages.pdf"), "extracted-pages.pdf"


def handle_delete() -> tuple[Path, str]:
    pdf = first_pdf()
    reader = open_reader(pdf, request.form.get("password") or None)
    to_delete = set(parse_pages(request.form.get("pages", ""), len(reader.pages)))
    keep = [index for index in range(len(reader.pages)) if index not in to_delete]
    if not keep:
        raise ValueError("不能刪除全部頁面。")
    return write_pdf(copy_pages(reader, keep), "deleted-pages.pdf"), "deleted-pages.pdf"


def handle_rotate() -> tuple[Path, str]:
    pdf = first_pdf()
    reader = open_reader(pdf, request.form.get("password") or None)
    angle = int(request.form.get("angle", "90"))
    if angle not in {90, 180, 270}:
        raise ValueError("旋轉角度只支援 90、180、270。")
    page_spec = (request.form.get("pages") or "").strip()
    rotate_pages = set(parse_pages(page_spec, len(reader.pages))) if page_spec else set(range(len(reader.pages)))

    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index in rotate_pages:
            page.rotate(angle)
        writer.add_page(page)
    return write_pdf(writer, "rotated.pdf"), "rotated.pdf"


def handle_encrypt() -> tuple[Path, str]:
    pdf = first_pdf()
    password = request.form.get("new_password", "")
    if not password:
        raise ValueError("請輸入新密碼。")
    reader = open_reader(pdf, request.form.get("password") or None)
    writer = copy_pages(reader, range(len(reader.pages)))
    writer.encrypt(password)
    return write_pdf(writer, "encrypted.pdf"), "encrypted.pdf"


def handle_decrypt() -> tuple[Path, str]:
    pdf = first_pdf()
    reader = open_reader(pdf, request.form.get("password") or None)
    writer = copy_pages(reader, range(len(reader.pages)))
    return write_pdf(writer, "decrypted.pdf"), "decrypted.pdf"


def handle_compress() -> tuple[Path, str]:
    pdf = first_pdf()
    reader = open_reader(pdf, request.form.get("password") or None)
    writer = PdfWriter()
    for page in reader.pages:
        page.compress_content_streams()
        writer.add_page(page)
    return write_pdf(writer, "compressed.pdf"), "compressed.pdf"


def handle_extract_text() -> tuple[Path, str]:
    pdf = first_pdf()
    reader = open_reader(pdf, request.form.get("password") or None)
    pieces = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pieces.append(f"--- Page {index} ---\n{text.strip()}\n")
    target = output_path("extracted-text.txt")
    target.write_text("\n".join(pieces), encoding="utf-8")
    return target, "extracted-text.txt"


def handle_pdf_to_images() -> tuple[Path, str]:
    pdf = first_pdf()
    target = output_path("pdf-images.zip")
    page_spec = request.form.get("pages", "")
    pdf_to_images(pdf, target, request.form.get("password") or "", pages_spec=page_spec)
    return target, "pdf-images.zip"


def handle_images_to_pdf() -> tuple[Path, str]:
    images = save_uploaded_files("files", IMAGE_EXTENSIONS)
    converted: list[Image.Image] = []
    for image_path in images:
        image = Image.open(image_path)
        if image.mode in {"RGBA", "P"}:
            image = image.convert("RGB")
        converted.append(image)
    if not converted:
        raise ValueError("請選擇圖片。")

    target = output_path("images.pdf")
    first, rest = converted[0], converted[1:]
    first.save(target, save_all=True, append_images=rest, resolution=150.0)
    for image in converted:
        image.close()
    return target, "images.pdf"


def handle_info() -> tuple[Path, str]:
    pdf = first_pdf()
    reader = open_reader(pdf, request.form.get("password") or None)
    metadata = reader.metadata or {}
    lines = [
        "Victor PDF Tools Box - PDF Info",
        f"File: {pdf.name}",
        f"Pages: {len(reader.pages)}",
        f"Encrypted: {reader.is_encrypted}",
        "",
        "Metadata:",
    ]
    for key, value in metadata.items():
        lines.append(f"{key}: {value}")
    target = output_path("pdf-info.txt")
    target.write_text("\n".join(lines), encoding="utf-8")
    return target, "pdf-info.txt"


HANDLERS = {
    "merge": handle_merge,
    "split": handle_split,
    "extract": handle_extract,
    "delete": handle_delete,
    "rotate": handle_rotate,
    "encrypt": handle_encrypt,
    "decrypt": handle_decrypt,
    "compress": handle_compress,
    "extract_text": handle_extract_text,
    "images_to_pdf": handle_images_to_pdf,
    "pdf_to_images": handle_pdf_to_images,
    "info": handle_info,
}


@app.route("/")
def index():
    return render_template("index.html", tools=TOOLS, max_upload_mb=MAX_UPLOAD_MB)


@app.route("/tool/<slug>", methods=["GET", "POST"])
def tool(slug: str):
    card = next((item for item in TOOLS if item.slug == slug), None)
    if not card:
        flash("找不到指定工具。", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        try:
            handler = HANDLERS[slug]
            target, download_name = handler()
            return send_output(target, download_name)
        except Exception as exc:
            flash(str(exc), "error")

    return render_template("tool.html", tool=card, max_upload_mb=MAX_UPLOAD_MB)


@app.route("/maintenance/clean", methods=["POST"])
def clean_workspace():
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    ensure_dirs()
    flash("暫存檔已清理。", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    ensure_dirs()
    debug_mode = os.environ.get("VICTOR_PDF_DEBUG", "").lower() in {"1", "true", "yes"}
    app.run(host="127.0.0.1", port=5055, debug=debug_mode)
