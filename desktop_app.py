from __future__ import annotations

import re
import threading
from copy import copy
from dataclasses import dataclass
from pathlib import Path
from tkinter import END, BOTH, LEFT, RIGHT, X, Y, filedialog, messagebox
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
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
    from tkinterdnd2 import DND_FILES, TkinterDnD

    BaseTk = TkinterDnD.Tk
    DND_AVAILABLE = True
except Exception:
    BaseTk = tk.Tk
    DND_FILES = None
    DND_AVAILABLE = False


PDF_TYPES = [("PDF files", "*.pdf")]
IMAGE_TYPES = [("Image files", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp")]
PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
THUMB_WIDTH = 150
THUMB_HEIGHT = 210
THUMB_COLUMNS = 4
ANNOT_PREVIEW_MAX_WIDTH = 760
ANNOT_PREVIEW_MAX_HEIGHT = 760


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
            raise ValueError(f"頁碼超出範圍：{page + 1}，本文件共有 {page_count} 頁。")
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
            NameObject("/DA"): TextStringObject(f"/Helv {font_size} Tf 0 0 0 rg"),
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


class DragListbox(tk.Listbox):
    def __init__(self, master, on_reorder, **kwargs):
        super().__init__(master, **kwargs)
        self.on_reorder = on_reorder
        self._drag_index: int | None = None
        self.bind("<Button-1>", self._set_drag_index)
        self.bind("<B1-Motion>", self._drag)

    def _set_drag_index(self, event):
        self._drag_index = self.nearest(event.y)

    def _drag(self, event):
        target = self.nearest(event.y)
        if self._drag_index is None or target == self._drag_index:
            return
        self.on_reorder(self._drag_index, target)
        self.selection_clear(0, END)
        self.selection_set(target)
        self._drag_index = target


class VictorPdfToolsApp(BaseTk):
    def __init__(self):
        super().__init__()
        self.title("Victor PDF Tools Box")
        self.geometry("1040x720")
        self.minsize(900, 620)
        self.page_items: list[PageItem] = []
        self.file_items: list[Path] = []
        self.selected_page_index: int | None = None
        self.selected_page_indexes: set[int] = set()
        self.thumbnail_drag_index: int | None = None
        self.thumbnail_refs: list[ImageTk.PhotoImage] = []
        self.thumbnail_cards: dict[int, tk.Frame] = {}
        self.thumbnail_cache: dict[tuple[str, int], Image.Image] = {}
        self.preview_mode = tk.BooleanVar(value=False)
        self.annotation_pdf_path: Path | None = None
        self.annotation_preview_photo: ImageTk.PhotoImage | None = None
        self.annotation_preview_size: tuple[int, int] = (0, 0)
        self.annotation_page_size: tuple[float, float] = (0.0, 0.0)
        self.annotation_page_count = 0
        self._build_style()
        self._build_ui()

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", padding=(12, 7))
        style.configure("Primary.TButton", background="#0f766e", foreground="#ffffff")
        style.configure("Header.TLabel", font=("Microsoft JhengHei UI", 18, "bold"))
        style.configure("Muted.TLabel", foreground="#637083")

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill=BOTH, expand=True)

        header = ttk.Frame(root)
        header.pack(fill=X, pady=(0, 16))
        ttk.Label(header, text="Victor PDF Tools Box", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="本機處理 PDF 文件，適合公司內部財務、審計及合併報表工作。可直接拖放檔案到清單。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        tabs = ttk.Notebook(root)
        tabs.pack(fill=BOTH, expand=True)

        self.arrange_tab = ttk.Frame(tabs, padding=14)
        self.batch_tab = ttk.Frame(tabs, padding=14)
        self.annotation_tab = ttk.Frame(tabs, padding=14)
        tabs.add(self.arrange_tab, text="拖曳頁面重排 / 組合")
        tabs.add(self.annotation_tab, text="文字標註 / 覆蓋")
        tabs.add(self.batch_tab, text="常用 PDF 工具")

        self._build_arrange_tab()
        self._build_annotation_tab()
        self._build_batch_tab()

        self.status = tk.StringVar(value="準備就緒")
        ttk.Label(root, textvariable=self.status, style="Muted.TLabel").pack(anchor="w", pady=(12, 0))

    def _build_arrange_tab(self) -> None:
        left = ttk.Frame(self.arrange_tab)
        left.pack(side=LEFT, fill=BOTH, expand=True)

        controls = ttk.Frame(left)
        controls.pack(fill=X, pady=(0, 10))
        ttk.Button(controls, text="加入 PDF 並展開頁面", command=self.add_pdf_pages).pack(side=LEFT, padx=(0, 8))
        ttk.Button(controls, text="移除選取頁面", command=self.remove_selected_pages).pack(side=LEFT, padx=(0, 8))
        ttk.Button(controls, text="清空", command=self.clear_pages).pack(side=LEFT, padx=(0, 8))
        ttk.Checkbutton(
            controls,
            text="大圖示模式",
            variable=self.preview_mode,
            command=self.toggle_preview_mode,
        ).pack(side=LEFT)

        self.page_area = ttk.Frame(left)
        self.page_area.pack(side=LEFT, fill=BOTH, expand=True)
        self.page_list = DragListbox(
            self.page_area,
            on_reorder=self.reorder_page_item,
            selectmode=tk.EXTENDED,
            activestyle="dotbox",
            height=22,
        )
        self.page_scroll = ttk.Scrollbar(self.page_area, orient="vertical", command=self.page_list.yview)
        self.page_list.configure(yscrollcommand=self.page_scroll.set)
        self.page_list.pack(side=LEFT, fill=BOTH, expand=True)
        self.page_scroll.pack(side=RIGHT, fill=Y)
        self.page_list.bind("<<ListboxSelect>>", self.on_page_list_select)
        self.enable_drop(self.page_list, self.drop_pdf_pages)

        self.thumbnail_canvas = tk.Canvas(self.page_area, background="#f6f8fb", highlightthickness=0)
        self.thumbnail_scroll = ttk.Scrollbar(self.page_area, orient="vertical", command=self.thumbnail_canvas.yview)
        self.thumbnail_canvas.configure(yscrollcommand=self.thumbnail_scroll.set)
        self.thumbnail_frame = ttk.Frame(self.thumbnail_canvas)
        self.thumbnail_window = self.thumbnail_canvas.create_window((0, 0), window=self.thumbnail_frame, anchor="nw")
        self.thumbnail_frame.bind(
            "<Configure>",
            lambda _event: self.thumbnail_canvas.configure(scrollregion=self.thumbnail_canvas.bbox("all")),
        )
        self.thumbnail_canvas.bind(
            "<Configure>",
            lambda event: self.thumbnail_canvas.itemconfigure(self.thumbnail_window, width=event.width),
        )
        self.enable_drop(self.thumbnail_canvas, self.drop_pdf_pages)
        self.enable_drop(self.thumbnail_frame, self.drop_pdf_pages)

        right = ttk.Frame(self.arrange_tab, padding=(18, 0, 0, 0))
        right.pack(side=RIGHT, fill=Y)
        ttk.Label(right, text="頁面排序").pack(anchor="w", pady=(0, 8))
        ttk.Button(right, text="上移", command=lambda: self.move_selected_page(-1)).pack(fill=X, pady=(0, 8))
        ttk.Button(right, text="下移", command=lambda: self.move_selected_page(1)).pack(fill=X, pady=(0, 12))
        ttk.Label(right, text="頁面旋轉").pack(anchor="w", pady=(0, 8))
        ttk.Button(right, text="選取頁左轉", command=lambda: self.rotate_selected_pages(270)).pack(fill=X, pady=(0, 8))
        ttk.Button(right, text="選取頁右轉", command=lambda: self.rotate_selected_pages(90)).pack(fill=X, pady=(0, 18))
        ttk.Button(right, text="儲存最新版 PDF", style="Primary.TButton", command=self.export_arranged_pdf).pack(fill=X, pady=(0, 10))
        ttk.Button(right, text="擷取選取 - 合併", command=self.extract_selected_merged).pack(fill=X, pady=(0, 8))
        ttk.Button(right, text="擷取選取 - 單獨", command=self.extract_selected_separate).pack(fill=X, pady=(0, 18))
        ttk.Label(
            right,
            text="提示：Ctrl+點擊可多選縮圖。縮圖上的左轉/右轉可直接旋轉該頁，儲存最新版 PDF 會套用排列和旋轉。",
            style="Muted.TLabel",
            wraplength=210,
        ).pack(anchor="w", pady=(16, 0))

    def _build_batch_tab(self) -> None:
        top = ttk.Frame(self.batch_tab)
        top.pack(fill=X, pady=(0, 12))
        ttk.Button(top, text="加入 PDF", command=self.add_pdf_files).pack(side=LEFT, padx=(0, 8))
        ttk.Button(top, text="加入圖片", command=self.add_image_files).pack(side=LEFT, padx=(0, 8))
        ttk.Button(top, text="移除選取檔案", command=self.remove_selected_files).pack(side=LEFT, padx=(0, 8))
        ttk.Button(top, text="上移", command=lambda: self.move_selected_file(-1)).pack(side=LEFT, padx=(0, 8))
        ttk.Button(top, text="下移", command=lambda: self.move_selected_file(1)).pack(side=LEFT, padx=(0, 8))
        ttk.Button(top, text="清空", command=self.clear_files).pack(side=LEFT)

        middle = ttk.Frame(self.batch_tab)
        middle.pack(fill=BOTH, expand=True)

        file_frame = ttk.Frame(middle)
        file_frame.pack(side=LEFT, fill=BOTH, expand=True)
        self.file_list = DragListbox(
            file_frame,
            on_reorder=self.reorder_file_item,
            selectmode=tk.EXTENDED,
            activestyle="dotbox",
            height=22,
        )
        file_scroll = ttk.Scrollbar(file_frame, orient="vertical", command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=file_scroll.set)
        self.file_list.pack(side=LEFT, fill=BOTH, expand=True)
        file_scroll.pack(side=RIGHT, fill=Y)
        self.enable_drop(self.file_list, self.drop_files)

        form = ttk.Frame(middle, padding=(18, 0, 0, 0))
        form.pack(side=RIGHT, fill=Y)
        ttk.Label(form, text="工具").pack(anchor="w")
        self.operation = tk.StringVar(value="merge")
        operations = [
            ("合併 PDF", "merge"),
            ("抽取頁碼", "extract"),
            ("刪除頁碼", "delete"),
            ("旋轉頁面", "rotate"),
            ("加密 PDF", "encrypt"),
            ("解除密碼", "decrypt"),
            ("基礎壓縮", "compress"),
            ("抽取文字", "extract_text"),
            ("圖片轉 PDF", "images_to_pdf"),
            ("PDF 資訊", "info"),
            ("加頁碼 / Footer", "add_page_numbers"),
            ("加水印 / 印章", "watermark"),
            ("刪除空白頁", "remove_blank_pages"),
            ("清理 Metadata", "clean_metadata"),
        ]
        for text, value in operations:
            ttk.Radiobutton(form, text=text, value=value, variable=self.operation).pack(anchor="w")

        ttk.Label(form, text="頁碼 / 範圍").pack(anchor="w", pady=(14, 4))
        self.pages_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.pages_var, width=28).pack(fill=X)

        ttk.Label(form, text="原 PDF 密碼（如適用）").pack(anchor="w", pady=(12, 4))
        self.password_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.password_var, show="*", width=28).pack(fill=X)

        ttk.Label(form, text="新密碼（加密用）").pack(anchor="w", pady=(12, 4))
        self.new_password_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.new_password_var, show="*", width=28).pack(fill=X)

        ttk.Label(form, text="旋轉角度").pack(anchor="w", pady=(12, 4))
        self.angle_var = tk.StringVar(value="90")
        ttk.Combobox(form, textvariable=self.angle_var, values=["90", "180", "270"], state="readonly", width=25).pack(fill=X)

        ttk.Label(form, text="文字 / 模板").pack(anchor="w", pady=(12, 4))
        self.batch_text_var = tk.StringVar(value="CONFIDENTIAL")
        ttk.Entry(form, textvariable=self.batch_text_var, width=28).pack(fill=X)
        ttk.Label(
            form,
            text="頁碼模板可用 {page} / {total}",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        ttk.Label(form, text="空白頁靈敏度").pack(anchor="w", pady=(12, 4))
        self.blank_threshold_var = tk.IntVar(value=25)
        ttk.Spinbox(form, from_=1, to=1000, textvariable=self.blank_threshold_var, width=10).pack(anchor="w")

        ttk.Button(form, text="處理並另存", style="Primary.TButton", command=self.run_operation).pack(fill=X, pady=(18, 0))

    def _build_annotation_tab(self) -> None:
        left = ttk.Frame(self.annotation_tab)
        left.pack(side=LEFT, fill=BOTH, expand=True)

        top = ttk.Frame(left)
        top.pack(fill=X, pady=(0, 10))
        ttk.Button(top, text="載入 PDF", command=self.load_annotation_pdf).pack(side=LEFT, padx=(0, 8))
        ttk.Label(top, text="頁碼").pack(side=LEFT, padx=(8, 4))
        self.annotation_page_var = tk.IntVar(value=1)
        self.annotation_page_spin = ttk.Spinbox(
            top,
            from_=1,
            to=1,
            width=6,
            textvariable=self.annotation_page_var,
            command=self.render_annotation_preview,
        )
        self.annotation_page_spin.pack(side=LEFT)
        ttk.Button(top, text="更新預覽", command=self.render_annotation_preview).pack(side=LEFT, padx=(8, 0))

        self.annotation_canvas = tk.Canvas(left, background="#f6f8fb", highlightthickness=1, highlightbackground="#dce3ec")
        self.annotation_canvas.pack(fill=BOTH, expand=True)
        self.annotation_canvas.bind("<Button-1>", self.set_annotation_position_from_click)
        self.enable_drop(self.annotation_canvas, self.drop_annotation_pdf)

        right = ttk.Frame(self.annotation_tab, padding=(18, 0, 0, 0))
        right.pack(side=RIGHT, fill=Y)
        ttk.Label(right, text="標註文字").pack(anchor="w")
        self.annotation_text = tk.Text(right, width=32, height=5, wrap="word")
        self.annotation_text.pack(fill=X, pady=(4, 10))

        self.annotation_cover_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="先用白底覆蓋原文字", variable=self.annotation_cover_var).pack(anchor="w", pady=(0, 10))

        ttk.Label(right, text="X / Y 位置").pack(anchor="w")
        xy = ttk.Frame(right)
        xy.pack(fill=X, pady=(4, 10))
        self.annotation_x_var = tk.DoubleVar(value=72.0)
        self.annotation_y_var = tk.DoubleVar(value=720.0)
        ttk.Entry(xy, textvariable=self.annotation_x_var, width=10).pack(side=LEFT, padx=(0, 6))
        ttk.Entry(xy, textvariable=self.annotation_y_var, width=10).pack(side=LEFT)

        ttk.Label(right, text="字體大小").pack(anchor="w")
        self.annotation_font_size_var = tk.IntVar(value=12)
        ttk.Spinbox(right, from_=6, to=72, textvariable=self.annotation_font_size_var, width=10).pack(anchor="w", pady=(4, 10))

        ttk.Label(right, text="覆蓋框 / 文字框寬高").pack(anchor="w")
        wh = ttk.Frame(right)
        wh.pack(fill=X, pady=(4, 10))
        self.annotation_width_var = tk.DoubleVar(value=220.0)
        self.annotation_height_var = tk.DoubleVar(value=32.0)
        ttk.Entry(wh, textvariable=self.annotation_width_var, width=10).pack(side=LEFT, padx=(0, 6))
        ttk.Entry(wh, textvariable=self.annotation_height_var, width=10).pack(side=LEFT)

        ttk.Label(right, text="PDF 密碼（如適用）").pack(anchor="w")
        self.annotation_password_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.annotation_password_var, show="*", width=28).pack(fill=X, pady=(4, 16))

        ttk.Button(right, text="套用並另存 PDF", style="Primary.TButton", command=self.save_annotation_pdf).pack(fill=X)
        ttk.Label(
            right,
            text="用法：載入 PDF 後，在左邊預覽點擊要放文字的位置。這是標註/覆蓋模式，不會真正改寫底層原文字。",
            style="Muted.TLabel",
            wraplength=230,
        ).pack(anchor="w", pady=(16, 0))

    def load_annotation_pdf(self) -> None:
        path = filedialog.askopenfilename(title="選擇 PDF", filetypes=PDF_TYPES)
        if not path:
            return
        self.set_annotation_pdf(Path(path))

    def drop_annotation_pdf(self, event) -> None:
        paths = [path for path in self.dropped_paths(event) if path.suffix.lower() in PDF_SUFFIXES]
        if not paths:
            self.set_status("請拖放 PDF 到預覽區。")
            return
        self.set_annotation_pdf(paths[0])

    def set_annotation_pdf(self, path: Path) -> None:
        try:
            reader = open_reader(path, self.annotation_password_var.get())
            self.annotation_pdf_path = path
            self.annotation_page_count = len(reader.pages)
            self.annotation_page_spin.configure(to=max(self.annotation_page_count, 1))
            self.annotation_page_var.set(1)
            self.render_annotation_preview()
            self.set_status(f"已載入 {path.name}，共 {self.annotation_page_count} 頁。")
        except Exception as exc:
            self.show_error(exc)

    def render_annotation_preview(self) -> None:
        if self.annotation_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        if not PDF_RENDER_AVAILABLE or pdfium is None:
            self.set_status("PDF 預覽元件未啟用，仍可手動輸入 X/Y。")
            return
        try:
            page_number = int(self.annotation_page_var.get())
            page_number = min(max(page_number, 1), self.annotation_page_count)
            self.annotation_page_var.set(page_number)
            document = pdfium.PdfDocument(str(self.annotation_pdf_path), password=self.annotation_password_var.get() or None)
            page = document.get_page(page_number - 1)
            page_width, page_height = page.get_size()
            scale = min(ANNOT_PREVIEW_MAX_WIDTH / page_width, ANNOT_PREVIEW_MAX_HEIGHT / page_height, 1.25)
            image = page.render(scale=scale).to_pil().convert("RGB")
            page.close()
            document.close()

            self.annotation_page_size = (float(page_width), float(page_height))
            self.annotation_preview_size = image.size
            self.annotation_preview_photo = ImageTk.PhotoImage(image)
            self.draw_annotation_preview()
        except Exception as exc:
            self.show_error(exc)

    def draw_annotation_preview(self) -> None:
        self.annotation_canvas.delete("all")
        if self.annotation_preview_photo is None:
            return
        image_width, image_height = self.annotation_preview_size
        x_offset, y_offset = 12, 12
        self.annotation_canvas.create_image(x_offset, y_offset, image=self.annotation_preview_photo, anchor="nw")
        self.annotation_canvas.configure(scrollregion=(0, 0, image_width + 24, image_height + 24))

        page_width, page_height = self.annotation_page_size
        if page_width <= 0 or page_height <= 0:
            return
        x = self.annotation_x_var.get() / page_width * image_width + x_offset
        y = (page_height - self.annotation_y_var.get()) / page_height * image_height + y_offset
        self.annotation_canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#0f766e", outline="#ffffff", width=2)
        self.annotation_canvas.create_line(x - 12, y, x + 12, y, fill="#0f766e", width=2)
        self.annotation_canvas.create_line(x, y - 12, x, y + 12, fill="#0f766e", width=2)

    def set_annotation_position_from_click(self, event) -> None:
        page_width, page_height = self.annotation_page_size
        image_width, image_height = self.annotation_preview_size
        if page_width <= 0 or page_height <= 0 or image_width <= 0 or image_height <= 0:
            return
        x_offset, y_offset = 12, 12
        image_x = min(max(event.x - x_offset, 0), image_width)
        image_y = min(max(event.y - y_offset, 0), image_height)
        pdf_x = image_x / image_width * page_width
        pdf_y = page_height - (image_y / image_height * page_height)
        self.annotation_x_var.set(round(pdf_x, 1))
        self.annotation_y_var.set(round(pdf_y, 1))
        self.draw_annotation_preview()
        self.set_status(f"已設定文字位置：X {pdf_x:.1f}, Y {pdf_y:.1f}")

    def save_annotation_pdf(self) -> None:
        if self.annotation_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        target = filedialog.asksaveasfilename(
            title="另存標註 PDF",
            defaultextension=".pdf",
            initialfile="annotated.pdf",
            filetypes=PDF_TYPES,
        )
        if not target:
            return
        text = self.annotation_text.get("1.0", "end").strip()
        self.run_in_thread(
            lambda: add_text_overlay_annotation(
                source=self.annotation_pdf_path,
                target=Path(target),
                page_index=int(self.annotation_page_var.get()) - 1,
                x=float(self.annotation_x_var.get()),
                y=float(self.annotation_y_var.get()),
                text=text,
                font_size=int(self.annotation_font_size_var.get()),
                cover_original=bool(self.annotation_cover_var.get()),
                cover_width=float(self.annotation_width_var.get()),
                cover_height=float(self.annotation_height_var.get()),
                password=self.annotation_password_var.get(),
            ),
            "正在套用文字標註...",
        )

    def add_pdf_pages(self) -> None:
        paths = filedialog.askopenfilenames(title="選擇 PDF", filetypes=PDF_TYPES)
        if not paths:
            return
        self.add_pdf_pages_from_paths([Path(path) for path in paths])

    def add_pdf_pages_from_paths(self, paths: list[Path]) -> None:
        try:
            added = 0
            for pdf_path in paths:
                if pdf_path.suffix.lower() not in PDF_SUFFIXES:
                    continue
                reader = open_reader(pdf_path, self.password_var.get())
                for index in range(len(reader.pages)):
                    self.page_items.append(PageItem(pdf_path, index, f"{pdf_path.name} - Page {index + 1}"))
                    added += 1
            self.refresh_page_list()
            self.refresh_thumbnails()
            self.set_status(f"已加入 {added} 頁。")
        except Exception as exc:
            self.show_error(exc)

    def refresh_page_list(self) -> None:
        self.page_list.delete(0, END)
        for item in self.page_items:
            self.page_list.insert(END, page_item_label(item))
        self.sync_page_list_selection()

    def refresh_thumbnails(self) -> None:
        for child in self.thumbnail_frame.winfo_children():
            child.destroy()
        self.thumbnail_refs.clear()
        self.thumbnail_cards.clear()
        if not self.page_items:
            return

        for index, item in enumerate(self.page_items):
            image = self.thumbnail_for_page(item, index)
            photo = ImageTk.PhotoImage(image)
            self.thumbnail_refs.append(photo)

            card = tk.Frame(
                self.thumbnail_frame,
                background=self.thumbnail_background(index),
                borderwidth=1,
                relief="solid",
                padx=8,
                pady=8,
            )
            row, col = divmod(index, THUMB_COLUMNS)
            card.thumbnail_index = index
            card.grid(row=row, column=col, padx=8, pady=8, sticky="n")
            self.thumbnail_cards[index] = card
            button = tk.Button(
                card,
                image=photo,
                relief="flat",
            )
            button.thumbnail_index = index
            button.pack()
            label = tk.Label(
                card,
                text=page_item_label(item),
                width=22,
                wraplength=THUMB_WIDTH,
                justify="center",
                background=card["background"],
            )
            label.thumbnail_index = index
            label.pack(pady=(6, 0))
            rotate_bar = tk.Frame(card, background=card["background"])
            rotate_bar.thumbnail_index = index
            rotate_bar.pack(fill=X, pady=(6, 0))
            left_button = tk.Button(
                rotate_bar,
                text="左轉",
                width=6,
                command=lambda selected=index: self.rotate_page_at(selected, 270),
            )
            right_button = tk.Button(
                rotate_bar,
                text="右轉",
                width=6,
                command=lambda selected=index: self.rotate_page_at(selected, 90),
            )
            left_button.thumbnail_index = index
            right_button.thumbnail_index = index
            left_button.pack(side=LEFT, padx=(0, 4))
            right_button.pack(side=LEFT)
            for widget in (card, button, label, rotate_bar):
                widget.bind("<ButtonPress-1>", lambda event, selected=index: self.start_thumbnail_drag(event, selected))
                widget.bind("<B1-Motion>", self.track_thumbnail_drag)
                widget.bind("<ButtonRelease-1>", self.finish_thumbnail_drag)

    def thumbnail_for_page(self, item: PageItem, index: int) -> Image.Image:
        cache_key = (str(item.pdf_path), item.page_index, item.rotation)
        cached = self.thumbnail_cache.get(cache_key)
        if cached is not None:
            return cached
        if PDF_RENDER_AVAILABLE and pdfium is not None:
            try:
                document = pdfium.PdfDocument(str(item.pdf_path), password=self.password_var.get() or None)
                page = document.get_page(item.page_index)
                bitmap = page.render(scale=0.25)
                image = bitmap.to_pil().convert("RGB")
                page.close()
                document.close()
                image.thumbnail((THUMB_WIDTH, THUMB_HEIGHT), Image.Resampling.LANCZOS)
                canvas = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), "white")
                x = (THUMB_WIDTH - image.width) // 2
                y = (THUMB_HEIGHT - image.height) // 2
                canvas.paste(image, (x, y))
                if item.rotation:
                    canvas = canvas.rotate(item.rotation, expand=False, fillcolor="white")
                self.thumbnail_cache[cache_key] = canvas
                return canvas
            except Exception:
                pass
        placeholder = self.placeholder_thumbnail(index)
        self.thumbnail_cache[cache_key] = placeholder
        return placeholder

    def thumbnail_background(self, index: int) -> str:
        return "#d9eee9" if index in self.selected_page_indexes else "#ffffff"

    def sync_page_list_selection(self) -> None:
        self.page_list.selection_clear(0, END)
        for index in sorted(self.selected_page_indexes):
            if index < len(self.page_items):
                self.page_list.selection_set(index)
        if self.selected_page_index is not None and self.selected_page_index < len(self.page_items):
            self.page_list.see(self.selected_page_index)

    def update_thumbnail_selection_display(self) -> None:
        for index, card in self.thumbnail_cards.items():
            background = self.thumbnail_background(index)
            card.configure(background=background)
            for child in card.winfo_children():
                try:
                    child.configure(background=background)
                except tk.TclError:
                    pass

    def placeholder_thumbnail(self, index: int) -> Image.Image:
        image = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), "#ffffff")
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, THUMB_WIDTH - 1, THUMB_HEIGHT - 1), outline="#9aa6b2", width=2)
        draw.text((20, 82), f"Page {index + 1}", fill="#182232")
        draw.text((20, 108), "Preview", fill="#637083")
        return image

    def toggle_preview_mode(self) -> None:
        if self.preview_mode.get():
            self.page_list.pack_forget()
            self.page_scroll.pack_forget()
            self.thumbnail_canvas.pack(side=LEFT, fill=BOTH, expand=True)
            self.thumbnail_scroll.pack(side=RIGHT, fill=Y)
            self.refresh_thumbnails()
        else:
            self.thumbnail_canvas.pack_forget()
            self.thumbnail_scroll.pack_forget()
            self.page_list.pack(side=LEFT, fill=BOTH, expand=True)
            self.page_scroll.pack(side=RIGHT, fill=Y)

    def on_page_list_select(self, _event=None) -> None:
        selected = list(self.page_list.curselection())
        self.selected_page_indexes = set(selected)
        self.selected_page_index = selected[-1] if selected else None
        self.update_thumbnail_selection_display()

    def select_page(self, index: int, additive: bool = False) -> None:
        if additive:
            if index in self.selected_page_indexes:
                self.selected_page_indexes.remove(index)
            else:
                self.selected_page_indexes.add(index)
        else:
            self.selected_page_indexes = {index}
        self.selected_page_index = index
        self.sync_page_list_selection()
        self.update_thumbnail_selection_display()

    def start_thumbnail_drag(self, event, index: int) -> None:
        self.thumbnail_drag_index = index
        additive = bool(event.state & 0x0004)
        self.select_page(index, additive=additive)
        self.set_status(f"正在拖曳 Page {index + 1}；放到另一頁上即可重新排序。")

    def track_thumbnail_drag(self, event) -> None:
        target = self.thumbnail_index_at(event.x_root, event.y_root)
        if target is not None and target != self.thumbnail_drag_index:
            self.set_status(f"放手後會移到 Page {target + 1} 位置。")

    def finish_thumbnail_drag(self, event) -> None:
        source = self.thumbnail_drag_index
        self.thumbnail_drag_index = None
        if source is None:
            return
        target = self.thumbnail_index_at(event.x_root, event.y_root)
        if target is None:
            self.set_status("未移動頁面。")
            return
        if target != source:
            self.reorder_page_item(source, target)
            self.set_status(f"已把頁面移到第 {target + 1} 位。")
        else:
            self.set_status(f"已選取 {len(self.selected_page_indexes)} 頁。")

    def thumbnail_index_at(self, x_root: int, y_root: int) -> int | None:
        widget = self.winfo_containing(x_root, y_root)
        while widget is not None:
            index = getattr(widget, "thumbnail_index", None)
            if index is not None:
                return index
            if widget is self.thumbnail_frame:
                return None
            widget = getattr(widget, "master", None)
        return None

    def reorder_page_item(self, source: int, target: int) -> None:
        selected_before = set(self.selected_page_indexes)
        item = self.page_items.pop(source)
        self.page_items.insert(target, item)
        remapped: set[int] = set()
        for index in selected_before:
            if index == source:
                remapped.add(target)
            elif source < target and source < index <= target:
                remapped.add(index - 1)
            elif target < source and target <= index < source:
                remapped.add(index + 1)
            else:
                remapped.add(index)
        self.selected_page_indexes = remapped
        self.selected_page_index = target if source in selected_before or not remapped else sorted(remapped)[-1]
        self.refresh_page_list()
        self.refresh_thumbnails()

    def move_selected_page(self, direction: int) -> None:
        selected = self.selected_page_index
        if selected is None and self.selected_page_indexes:
            selected = sorted(self.selected_page_indexes)[-1]
        if selected is None:
            self.set_status("請選取一頁來上移或下移。")
            return
        source = selected
        target = source + direction
        if target < 0 or target >= len(self.page_items):
            return
        self.reorder_page_item(source, target)
        self.page_list.selection_set(target)

    def rotate_page_at(self, index: int, angle: int) -> None:
        if index < 0 or index >= len(self.page_items):
            return
        item = self.page_items[index]
        self.page_items[index] = PageItem(
            pdf_path=item.pdf_path,
            page_index=item.page_index,
            label=item.label,
            rotation=(item.rotation + angle) % 360,
        )
        self.selected_page_indexes = {index}
        self.selected_page_index = index
        self.refresh_page_list()
        self.refresh_thumbnails()
        self.set_status(f"已旋轉第 {index + 1} 頁。按「儲存最新版 PDF」輸出新檔。")

    def rotate_selected_pages(self, angle: int) -> None:
        indexes = self.get_selected_page_indexes()
        if not indexes:
            self.set_status("請先選取要旋轉的頁面。")
            return
        for index in indexes:
            item = self.page_items[index]
            self.page_items[index] = PageItem(
                pdf_path=item.pdf_path,
                page_index=item.page_index,
                label=item.label,
                rotation=(item.rotation + angle) % 360,
            )
        self.refresh_page_list()
        self.refresh_thumbnails()
        self.set_status(f"已旋轉 {len(indexes)} 頁。按「儲存最新版 PDF」輸出新檔。")

    def remove_selected_pages(self) -> None:
        selected = self.get_selected_page_indexes()
        for index in reversed(selected):
            self.page_items.pop(index)
        self.selected_page_indexes.clear()
        self.selected_page_index = None
        self.refresh_page_list()
        self.refresh_thumbnails()

    def clear_pages(self) -> None:
        self.page_items.clear()
        self.selected_page_indexes.clear()
        self.selected_page_index = None
        self.thumbnail_cache.clear()
        self.refresh_page_list()
        self.refresh_thumbnails()

    def get_selected_page_indexes(self) -> list[int]:
        if self.selected_page_indexes:
            return sorted(index for index in self.selected_page_indexes if index < len(self.page_items))
        return list(self.page_list.curselection())

    def export_arranged_pdf(self) -> None:
        if not self.page_items:
            self.set_status("請先加入 PDF 頁面。")
            return
        target = filedialog.asksaveasfilename(
            title="儲存組合 PDF",
            defaultextension=".pdf",
            initialfile="arranged-pages.pdf",
            filetypes=PDF_TYPES,
        )
        if not target:
            return
        self.run_in_thread(lambda: self._export_arranged_pdf(Path(target)), "正在匯出組合 PDF...")

    def _export_arranged_pdf(self, target: Path) -> None:
        write_page_items_merged(self.page_items, list(range(len(self.page_items))), target, self.password_var.get())

    def extract_selected_merged(self) -> None:
        indexes = self.get_selected_page_indexes()
        if not indexes:
            self.set_status("請先選取要擷取的頁面。")
            return
        target = filedialog.asksaveasfilename(
            title="擷取選取頁面並合併",
            defaultextension=".pdf",
            initialfile="extracted-selected-pages.pdf",
            filetypes=PDF_TYPES,
        )
        if not target:
            return
        self.run_in_thread(
            lambda: write_page_items_merged(self.page_items, indexes, Path(target), self.password_var.get()),
            f"正在擷取 {len(indexes)} 頁並合併...",
        )

    def extract_selected_separate(self) -> None:
        indexes = self.get_selected_page_indexes()
        if not indexes:
            self.set_status("請先選取要擷取的頁面。")
            return
        folder = filedialog.askdirectory(title="選擇單獨匯出資料夾")
        if not folder:
            return
        self.run_in_thread(
            lambda: write_page_items_separately(self.page_items, indexes, Path(folder), self.password_var.get()),
            f"正在擷取 {len(indexes)} 頁為獨立 PDF...",
        )

    def add_pdf_files(self) -> None:
        self.add_files(PDF_TYPES)

    def add_image_files(self) -> None:
        self.add_files(IMAGE_TYPES)

    def add_files(self, filetypes) -> None:
        paths = filedialog.askopenfilenames(title="選擇檔案", filetypes=filetypes)
        self.add_files_from_paths([Path(path) for path in paths])

    def add_files_from_paths(self, paths: list[Path]) -> None:
        supported = PDF_SUFFIXES | IMAGE_SUFFIXES
        added = 0
        skipped = 0
        for path in paths:
            if path.is_file() and path.suffix.lower() in supported:
                self.file_items.append(path)
                added += 1
            else:
                skipped += 1
        self.refresh_file_list()
        if skipped:
            self.set_status(f"已加入 {added} 個檔案，略過 {skipped} 個不支援項目。")
        else:
            self.set_status(f"已加入 {added} 個檔案。")

    def refresh_file_list(self) -> None:
        self.file_list.delete(0, END)
        for path in self.file_items:
            self.file_list.insert(END, str(path))

    def reorder_file_item(self, source: int, target: int) -> None:
        item = self.file_items.pop(source)
        self.file_items.insert(target, item)
        self.refresh_file_list()

    def move_selected_file(self, direction: int) -> None:
        selected = list(self.file_list.curselection())
        if len(selected) != 1:
            self.set_status("請選取一個檔案來上移或下移。")
            return
        source = selected[0]
        target = source + direction
        if target < 0 or target >= len(self.file_items):
            return
        self.reorder_file_item(source, target)
        self.file_list.selection_set(target)

    def remove_selected_files(self) -> None:
        for index in reversed(self.file_list.curselection()):
            self.file_items.pop(index)
        self.refresh_file_list()

    def clear_files(self) -> None:
        self.file_items.clear()
        self.refresh_file_list()

    def enable_drop(self, widget, handler) -> None:
        if not DND_AVAILABLE:
            self.set_status("拖放支援未啟用；請安裝 tkinterdnd2 或使用加入檔案按鈕。")
            return
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", handler)

    def dropped_paths(self, event) -> list[Path]:
        return [Path(item) for item in self.tk.splitlist(event.data)]

    def drop_pdf_pages(self, event) -> None:
        paths = [path for path in self.dropped_paths(event) if path.suffix.lower() in PDF_SUFFIXES]
        if not paths:
            self.set_status("請拖放 PDF 檔案到頁面清單。")
            return
        self.add_pdf_pages_from_paths(paths)

    def drop_files(self, event) -> None:
        self.add_files_from_paths(self.dropped_paths(event))

    def run_operation(self) -> None:
        operation = self.operation.get()
        extension = ".txt" if operation in {"extract_text", "info"} else ".pdf"
        target = filedialog.asksaveasfilename(
            title="另存輸出檔案",
            defaultextension=extension,
            initialfile=safe_output_name(f"{operation}{extension}"),
            filetypes=[("Output file", f"*{extension}")],
        )
        if not target:
            return
        self.run_in_thread(lambda: self._run_operation(operation, Path(target)), "正在處理...")

    def _run_operation(self, operation: str, target: Path) -> None:
        if not self.file_items:
            raise ValueError("請先加入檔案。")
        password = self.password_var.get()
        if operation == "merge":
            writer = PdfWriter()
            for path in self.file_items:
                reader = open_reader(path, password)
                for page in reader.pages:
                    writer.add_page(page)
            write_pdf(writer, target)
            return

        if operation == "images_to_pdf":
            images = [Image.open(path).convert("RGB") for path in self.file_items]
            try:
                images[0].save(target, save_all=True, append_images=images[1:], resolution=150.0)
            finally:
                for image in images:
                    image.close()
            return

        reader = open_reader(self.file_items[0], password)
        if operation == "extract":
            pages = parse_pages(self.pages_var.get(), len(reader.pages))
            writer = PdfWriter()
            for index in pages:
                writer.add_page(reader.pages[index])
            write_pdf(writer, target)
        elif operation == "delete":
            delete_pages = set(parse_pages(self.pages_var.get(), len(reader.pages)))
            writer = PdfWriter()
            for index, page in enumerate(reader.pages):
                if index not in delete_pages:
                    writer.add_page(page)
            if not writer.pages:
                raise ValueError("不能刪除全部頁面。")
            write_pdf(writer, target)
        elif operation == "rotate":
            page_spec = self.pages_var.get().strip()
            rotate_pages = set(parse_pages(page_spec, len(reader.pages))) if page_spec else set(range(len(reader.pages)))
            angle = int(self.angle_var.get())
            writer = PdfWriter()
            for index, page in enumerate(reader.pages):
                if index in rotate_pages:
                    page.rotate(angle)
                writer.add_page(page)
            write_pdf(writer, target)
        elif operation == "encrypt":
            new_password = self.new_password_var.get()
            if not new_password:
                raise ValueError("請輸入新密碼。")
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            writer.encrypt(new_password)
            write_pdf(writer, target)
        elif operation == "decrypt":
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            write_pdf(writer, target)
        elif operation == "compress":
            writer = PdfWriter()
            for page in reader.pages:
                page.compress_content_streams()
                writer.add_page(page)
            write_pdf(writer, target)
        elif operation == "extract_text":
            lines = []
            for index, page in enumerate(reader.pages, start=1):
                lines.append(f"--- Page {index} ---")
                lines.append((page.extract_text() or "").strip())
                lines.append("")
            target.write_text("\n".join(lines), encoding="utf-8")
        elif operation == "info":
            metadata = reader.metadata or {}
            lines = [
                "Victor PDF Tools Box - PDF Info",
                f"File: {self.file_items[0]}",
                f"Pages: {len(reader.pages)}",
                f"Encrypted: {reader.is_encrypted}",
                "",
                "Metadata:",
            ]
            for key, value in metadata.items():
                lines.append(f"{key}: {value}")
            target.write_text("\n".join(lines), encoding="utf-8")
        elif operation == "add_page_numbers":
            template = self.batch_text_var.get().strip() or "Page {page} of {total}"
            add_page_numbers(self.file_items[0], target, template, password)
        elif operation == "watermark":
            add_watermark(self.file_items[0], target, self.batch_text_var.get(), password)
        elif operation == "remove_blank_pages":
            removed = remove_blank_pages(
                self.file_items[0],
                target,
                threshold=int(self.blank_threshold_var.get()),
                password=password,
            )
            self.after(0, lambda: self.set_status(f"完成，已移除 {removed} 頁空白頁。"))
        elif operation == "clean_metadata":
            clean_metadata(self.file_items[0], target, password)
        else:
            raise ValueError(f"未知工具：{operation}")

    def run_in_thread(self, action, busy_message: str) -> None:
        self.set_status(busy_message)

        def worker():
            try:
                action()
            except Exception as exc:
                self.after(0, lambda: self.show_error(exc))
            else:
                self.after(0, lambda: self.set_status("完成。"))
                self.after(0, lambda: messagebox.showinfo("完成", "文件已處理完成。"))

        threading.Thread(target=worker, daemon=True).start()

    def set_status(self, message: str) -> None:
        self.status.set(message)

    def show_error(self, exc: Exception) -> None:
        self.set_status("發生錯誤。")
        messagebox.showerror("Victor PDF Tools Box", str(exc))


if __name__ == "__main__":
    VictorPdfToolsApp().mainloop()
