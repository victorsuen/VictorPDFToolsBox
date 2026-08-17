from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QByteArray, QEvent, QMimeData, QPoint, QRect, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QDrag, QDragEnterEvent, QDropEvent, QFont, QIcon, QIntValidator, QKeySequence, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from document_workspace import DocumentWorkspace
from audit_log import append_audit_event, audit_log_path, read_audit_events
from flow_layout import FlowLayout, prevent_button_clip
from pdf_core import (
    IMAGE_SUFFIXES,
    MARKUP_COLOR_PRESETS,
    OCR_LANGUAGE_OPTIONS,
    OFFICE_DIALOG_FILTER,
    OFFICE_SUFFIXES,
    PDF_RENDER_AVAILABLE,
    PDF_SUFFIXES,
    PYMUPDF_AVAILABLE,
    BookmarkItem,
    EraseMark,
    MarkupAnnotation,
    PageItem,
    TextBlock,
    add_bates_numbering,
    add_page_numbers,
    ANNOTATION_COLOR_PRESETS,
    ANNOTATION_FILL_PRESETS,
    add_text_overlay_annotations,
    add_watermark,
    WATERMARK_COLORS,
    WATERMARK_POSITIONS,
    WATERMARK_ROTATIONS,
    apply_erase_marks,
    apply_erase_then_text_overlays,
    apply_markup_annotations,
    apply_outline,
    BATES_POSITIONS,
    CALLOUT_KINDS,
    callout_box_from_pointer,
    callout_layout,
    comment_box_from_pointer,
    comment_polyline,
    crop_pdf_pages,
    extract_outline,
    resolve_annotation_fill,
    rgb_to_hex,
    text_contains_cjk,
    apply_text_markups_for_query,
    clean_metadata,
    compress_pdf,
    compress_pdf_advanced,
    compare_pdf_text,
    compare_pdf_visual,
    decrypt_pdf,
    flatten_form_fields,
    insert_pdf_pages,
    add_image_stamp,
    add_signature_image,
    add_text_stamp,
    replace_pdf_pages,
    secure_redact_query,
    split_pdf_by_bookmarks,
    delete_pdf_pages,
    encrypt_pdf,
    encrypt_pdf_with_permissions,
    extract_pdf_pages,
    extract_pdf_page_indexes,
    apply_edits_and_extract_pages,
    extract_page_text_blocks,
    extract_pdf_text,
    font_key_for_pdf_font,
    images_to_pdf,
    office_files_to_pdf,
    merge_pdf_files,
    last_ocr_language,
    ocr_language_short_label,
    ocr_pdf_to_searchable_pdf,
    ocr_pdf_to_text,
    pdf_to_docx,
    pdf_to_images,
    pdf_to_xlsx,
    open_reader,
    paint_callout_markup,
    page_item_label,
    parse_pages,
    pdfium,
    redact_matching_text_blocks_overlay,
    redact_text_block_secure,
    redact_text_block_overlay,
    remove_blank_pages,
    PYMUPDF_AVAILABLE,
    replace_text_block_seamless,
    replace_text_block_content_stream,
    replace_text_block_overlay,
    rotate_pdf_pages,
    safe_output_name,
    suggested_pdf_name_for_source,
    suggested_pdf_path_for_source,
    split_pdf_advanced,
    split_pdf_to_zip,
    text_matches_query,
    write_page_items_merged,
    write_page_items_separately,
    write_pdf_info,
)

TOOL_OPERATIONS = [
    ("merge", "合併 PDF"),
    ("split", "逐頁拆分 (ZIP)"),
    ("split_advanced", "進階拆分 (多檔 ZIP)"),
    ("extract", "抽取頁碼"),
    ("delete", "刪除頁碼"),
    ("rotate", "旋轉頁面"),
    ("encrypt", "加密 PDF"),
    ("encrypt_permissions", "加密 + 權限控制"),
    ("bates", "Bates 編號"),
    ("decrypt", "解除密碼"),
    ("compress", "基礎壓縮"),
    ("extract_text", "抽取文字"),
    ("ocr_text", "OCR 抽文字"),
    ("ocr_searchable_pdf", "掃描 PDF 轉可搜尋 PDF"),
    ("images_to_pdf", "圖片轉 PDF"),
    ("pdf_to_images", "PDF 轉圖片"),
    ("info", "PDF 資訊"),
    ("add_page_numbers", "加頁碼 / Footer"),
    ("watermark", "加水印 / 印章"),
    ("remove_blank_pages", "刪除空白頁"),
    ("clean_metadata", "清理 Metadata"),
    ("insert_pages", "插入頁面"),
    ("replace_pages", "取代頁面"),
    ("compress_advanced", "進階壓縮"),
    ("compare_text", "比對 PDF 文字"),
    ("compare_visual", "視覺比對 PDF"),
    ("split_bookmarks", "依書籤拆分"),
    ("stamp_image", "影像印章 / 簽名"),
    ("text_stamp", "文字圖章"),
    ("flatten_forms", "壓平表單"),
    ("search_markup", "搜尋並螢光"),
    ("secure_redact", "安全塗銷關鍵字"),
]

PDF_OUTPUT_OPERATIONS = frozenset(
    {
        "merge",
        "extract",
        "delete",
        "rotate",
        "encrypt",
        "encrypt_permissions",
        "bates",
        "decrypt",
        "compress",
        "images_to_pdf",
        "add_page_numbers",
        "watermark",
        "remove_blank_pages",
        "clean_metadata",
        "ocr_searchable_pdf",
        "insert_pages",
        "replace_pages",
        "compress_advanced",
        "compare_visual",
        "stamp_image",
        "text_stamp",
        "flatten_forms",
        "search_markup",
        "secure_redact",
    }
)

FOLDER_REVEAL_OPERATIONS = frozenset(
    {
        "split",
        "split_advanced",
        "extract_text",
        "ocr_text",
        "info",
        "pdf_to_images",
        "compare_text",
        "split_bookmarks",
    }
)

# Tools that can run once per PDF when batch mode is enabled (output to a folder).
BATCHABLE_OPERATIONS = frozenset(
    {
        "rotate",
        "encrypt",
        "encrypt_permissions",
        "decrypt",
        "compress",
        "compress_advanced",
        "add_page_numbers",
        "watermark",
        "remove_blank_pages",
        "clean_metadata",
        "bates",
        "flatten_forms",
        "search_markup",
        "secure_redact",
        "extract_text",
        "info",
        "delete",
        "extract",
        "ocr_text",
        "ocr_searchable_pdf",
    }
)

SETTINGS_ORG = "VictorSuen"
SETTINGS_APP = "VictorPDFToolsBox"
DOCUMENT_TAB_TITLE_MAX = 18


def tool_output_extension(operation: str) -> str:
    if operation == "pdf_to_word":
        return ".docx"
    if operation == "pdf_to_excel":
        return ".xlsx"
    if operation in {"extract_text", "ocr_text", "info", "compare_text"}:
        return ".txt"
    if operation in {"split", "split_advanced", "split_bookmarks"}:
        return ".zip"
    return ".pdf"


def document_tab_title(name: str, max_chars: int = DOCUMENT_TAB_TITLE_MAX) -> str:
    """Shorten long PDF names so multiple document tabs stay visible."""

    filename = Path(name).name or name
    if len(filename) <= max_chars:
        return filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".pdf"
    keep = max(4, max_chars - len(suffix) - 1)
    return f"{stem[:keep]}…{suffix}"


def configure_count_progress_bar(bar: QProgressBar) -> None:
    bar.setAlignment(Qt.AlignCenter)
    bar.setTextVisible(True)
    bar.setFormat("%v / %m")
    font = QFont("Segoe UI")
    font.setStyleHint(QFont.SansSerif)
    bar.setFont(font)


def reveal_output(path: Path) -> None:
    target = path.resolve()
    if not target.exists():
        return
    if sys.platform == "win32":
        if target.is_dir():
            os.startfile(str(target))
        else:
            subprocess.Popen(["explorer", "/select,", str(target)])
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)])
        return
    subprocess.Popen(["xdg-open", str(target if target.is_dir() else target.parent)])


def open_output_file(path: Path) -> None:
    target = path.resolve()
    if not target.exists() or target.is_dir():
        return
    if sys.platform == "win32":
        os.startfile(str(target))
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
        return
    subprocess.Popen(["xdg-open", str(target)])

THUMB_SIZE = QSize(195, 292)
ICON_SIZE = QSize(165, 215)
THUMB_RENDER_BATCH = 8
THUMB_RENDER_DELAY_MS = 16
THUMB_RENDER_SCALE = 0.22
THUMB_PRIORITY_COUNT = 24
ANNOT_PREVIEW_MAX_WIDTH = 1100
ANNOT_PREVIEW_MAX_HEIGHT = 1100
ANNOT_PREVIEW_OFFSET = 12
ADVANCED_THUMB_ICON_SIZE = QSize(168, 216)
ADVANCED_THUMB_MAX_SIZE = (168, 216)
ADVANCED_THUMB_PANEL_WIDTH = 220
ADVANCED_THUMB_PANEL_MIN_WIDTH = 160
ADVANCED_THUMB_PANEL_MAX_WIDTH = 420
ADVANCED_THUMB_BATCH_SIZE = 6
ADVANCED_THUMB_DELAY_MS = 20
ADVANCED_PREVIEW_ZOOM_MIN = 0.7
ADVANCED_PREVIEW_ZOOM_MAX = 3.5
ADVANCED_PREVIEW_ZOOM_STEP = 0.25
ANNOTATION_BOX_PAD_X = 12.0
ANNOTATION_BOX_PAD_Y = 10.0
ANNOTATION_HANDLE_SIZE = 9
WINDOW_MIN_SIZE = QSize(880, 560)
WINDOW_DEFAULT_SIZE = QSize(1180, 760)


def preferred_window_geometry(default: QSize = WINDOW_DEFAULT_SIZE) -> QRect:
    """Return a centered window rect that fits the available screen area."""

    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return QRect(80, 60, default.width(), default.height())
    available = screen.availableGeometry()
    soft_min_w = min(WINDOW_MIN_SIZE.width(), available.width())
    soft_min_h = min(WINDOW_MIN_SIZE.height(), available.height())
    width = min(default.width(), max(soft_min_w, int(available.width() * 0.92)))
    height = min(default.height(), max(soft_min_h, int(available.height() * 0.88)))
    width = min(max(width, soft_min_w), available.width())
    height = min(max(height, soft_min_h), available.height())
    x = available.x() + max((available.width() - width) // 2, 0)
    y = available.y() + max((available.height() - height) // 2, 0)
    return QRect(x, y, width, height)


def wrap_side_panel(panel: QWidget, max_width: int = 330) -> QScrollArea:
    """Put a tall side panel in a scroll area so the window can shrink."""

    panel.setMinimumWidth(max(240, max_width - 24))
    panel.setMaximumWidth(max_width)
    scroll = QScrollArea()
    scroll.setWidget(panel)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setMinimumWidth(max_width)
    scroll.setMaximumWidth(max_width + 8)
    scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    return scroll


FONT_SIZE_PRESETS = ("8", "10", "12", "14", "16", "18", "24", "36", "48", "72")
FONT_SIZE_MIN = 6
FONT_SIZE_MAX = 144


def combo_font_size(combo: QComboBox, default: int = 12) -> int:
    try:
        value = int(str(combo.currentText()).strip())
    except (TypeError, ValueError):
        value = default
    value = min(max(value, FONT_SIZE_MIN), FONT_SIZE_MAX)
    text = str(value)
    if str(combo.currentText()).strip() != text:
        combo.blockSignals(True)
        combo.setEditText(text)
        combo.blockSignals(False)
    return value


def configure_font_size_combo(combo: QComboBox, default: str, on_change) -> None:
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    combo.clear()
    for size in FONT_SIZE_PRESETS:
        combo.addItem(size)
    combo.setCurrentText(default)
    combo.setValidator(QIntValidator(FONT_SIZE_MIN, FONT_SIZE_MAX, combo))
    combo.setToolTip(f"可選預設值，或直接輸入 {FONT_SIZE_MIN}–{FONT_SIZE_MAX}")
    combo.activated.connect(lambda *_args: on_change())
    line = combo.lineEdit()
    if line is not None:
        line.setPlaceholderText(f"{FONT_SIZE_MIN}–{FONT_SIZE_MAX}")
        line.editingFinished.connect(on_change)


def is_delete_key(event) -> bool:
    if event.modifiers() & ~Qt.KeypadModifier:
        return False
    return event.key() in (Qt.Key_Delete, Qt.Key_Backspace)


def rect_chrome_contains(rect: QRect, point: QPoint, thickness: int = 10) -> bool:
    if rect.width() < 2 or rect.height() < 2:
        return False
    outer = rect.adjusted(-3, -3, 3, 3)
    inner = rect.adjusted(thickness, thickness, -thickness, -thickness)
    if inner.width() < 6 or inner.height() < 6:
        return outer.contains(point)
    return outer.contains(point) and not inner.contains(point)


def arm_box_delete(preview) -> None:
    preview.pending_box_delete = True
    preview.setFocus(Qt.MouseFocusReason)


def annotation_text_pixel_width(font, text: str) -> float:
    if not text:
        return 0.0
    if hasattr(font, "getlength"):
        try:
            return float(font.getlength(text))
        except Exception:
            pass
    try:
        bbox = font.getbbox(text)
        return float(bbox[2] - bbox[0])
    except Exception:
        return float(len(text) * 8)


def annotation_font_line_height(font, font_size: float) -> float:
    try:
        bbox = font.getbbox("Hg中")
        measured = float(bbox[3] - bbox[1])
        if measured > 1:
            return max(measured * 1.18, float(font_size) * 1.15)
    except Exception:
        pass
    return float(font_size) * 1.35


def wrap_annotation_text(text: str, font, max_width: float) -> list[str]:
    """Wrap CJK and Latin text so it stays inside max_width."""

    lines: list[str] = []
    limit = max(float(max_width), 8.0)
    for paragraph in text.replace("\r", "").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            trial = current + char
            if current and annotation_text_pixel_width(font, trial) > limit:
                lines.append(current)
                current = char
            else:
                current = trial
        if current:
            lines.append(current)
    return lines or [""]


def annotation_handle_rects(box: QRect, size: int = ANNOTATION_HANDLE_SIZE) -> dict[str, QRect]:
    if box.width() < 2 or box.height() < 2:
        return {}
    half = size // 2
    left, top = box.x(), box.y()
    right, bottom = left + box.width(), top + box.height()
    cx, cy = (left + right) // 2, (top + bottom) // 2
    return {
        "nw": QRect(left - half, top - half, size, size),
        "n": QRect(cx - half, top - half, size, size),
        "ne": QRect(right - half, top - half, size, size),
        "e": QRect(right - half, cy - half, size, size),
        "se": QRect(right - half, bottom - half, size, size),
        "s": QRect(cx - half, bottom - half, size, size),
        "sw": QRect(left - half, bottom - half, size, size),
        "w": QRect(left - half, cy - half, size, size),
    }


def point_near_segment(point: QPoint, start: QPoint, end: QPoint, tolerance: int = 10) -> bool:
    dx = end.x() - start.x()
    dy = end.y() - start.y()
    length2 = dx * dx + dy * dy
    px, py = point.x(), point.y()
    if length2 < 1:
        return (px - start.x()) ** 2 + (py - start.y()) ** 2 <= tolerance * tolerance
    t = max(0.0, min(1.0, ((px - start.x()) * dx + (py - start.y()) * dy) / length2))
    qx = start.x() + t * dx
    qy = start.y() + t * dy
    return (px - qx) ** 2 + (py - qy) ** 2 <= tolerance * tolerance


class ToolFileList(QListWidget):
    filesDropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile()]
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class PreviewImageLabel(QLabel):
    """Base preview label that does not force the main window to grow."""

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setStyleSheet("background: #f6f8fb; border: 1px solid #dce3ec;")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def minimumSizeHint(self) -> QSize:
        return QSize(120, 120)

    def sizeHint(self) -> QSize:
        pixmap = self.pixmap()
        if pixmap is not None and not pixmap.isNull():
            return pixmap.size()
        return QSize(320, 400)

    def set_preview_pixmap(self, pixmap: QPixmap) -> None:
        self.setPixmap(pixmap)
        self.resize(pixmap.size())


class AnnotationPreviewLabel(PreviewImageLabel):
    positionClicked = Signal(QPoint)
    rectDrawn = Signal(QPoint, QPoint)
    boxResized = Signal(str, QPoint, QPoint)
    boxMoved = Signal(QPoint, QPoint)
    pointerMoved = Signal(QPoint)
    elbowMoved = Signal(QPoint)
    boxInteractionFinished = Signal()
    pointerInteractionFinished = Signal()
    elbowInteractionFinished = Signal()
    copyRequested = Signal()
    pasteRequested = Signal()
    undoRequested = Signal()
    deleteRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.band_color = QColor(43, 106, 158)
        self.box_rect = QRect()
        self.pointer_rect = QRect()
        self.elbow_p1 = QPoint()
        self.elbow_p2 = QPoint()
        self.handles_enabled = False
        self.pointer_enabled = False
        self.elbow_enabled = False
        self.pending_box_delete = False
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self._mode: str | None = None
        self._handle: str | None = None

    def _handle_at(self, point: QPoint) -> str | None:
        if not self.handles_enabled:
            return None
        for name, rect in annotation_handle_rects(self.box_rect).items():
            hit = rect.adjusted(-2, -2, 2, 2)
            if hit.contains(point):
                return name
        return None

    def _hit_pointer(self, point: QPoint) -> bool:
        if not self.pointer_enabled or self.pointer_rect.width() < 1:
            return False
        return self.pointer_rect.contains(point)

    def _hit_elbow(self, point: QPoint) -> bool:
        if not self.elbow_enabled:
            return False
        return point_near_segment(point, self.elbow_p1, self.elbow_p2, 12)

    def _box_contains(self, point: QPoint) -> bool:
        if not self.handles_enabled or self.box_rect.width() < 2:
            return False
        return self.box_rect.adjusted(-2, -2, 2, 2).contains(point)

    def _cursor_for_point(self, point: QPoint):
        handle = self._handle_at(point)
        if handle in {"n", "s"}:
            return Qt.SizeVerCursor
        if handle in {"e", "w"}:
            return Qt.SizeHorCursor
        if handle in {"nw", "se"}:
            return Qt.SizeFDiagCursor
        if handle in {"ne", "sw"}:
            return Qt.SizeBDiagCursor
        if self._hit_pointer(point):
            return Qt.PointingHandCursor
        if self._hit_elbow(point):
            return Qt.SizeHorCursor
        if self._box_contains(point):
            return Qt.SizeAllCursor
        if self.pointer_enabled:
            return Qt.PointingHandCursor
        return Qt.CrossCursor

    def mousePressEvent(self, event) -> None:
        point = event.position().toPoint()
        handle = self._handle_at(point)
        self._start = point
        self._current = point
        self.pending_box_delete = False
        if handle:
            self._mode = "resize"
            self._handle = handle
            arm_box_delete(self)
        elif self._hit_pointer(point):
            self._mode = "pointer"
            self._handle = None
        elif self._hit_elbow(point):
            self._mode = "elbow"
            self._handle = None
        elif rect_chrome_contains(self.box_rect, point) or self._box_contains(point):
            self._mode = "move"
            self._handle = None
            arm_box_delete(self)
        elif self.pointer_enabled:
            self._mode = "pointer"
            self._handle = None
        else:
            self._mode = "place"
            self._handle = None
        self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        point = event.position().toPoint()
        self.setCursor(QCursor(self._cursor_for_point(point)))
        if self._start is not None:
            self._current = point
            if self._mode == "resize" and self._handle:
                self.boxResized.emit(self._handle, self._start, point)
            elif self._mode == "move":
                self.boxMoved.emit(self._start, point)
            elif self._mode == "pointer":
                self.pointerMoved.emit(point)
            elif self._mode == "elbow":
                self.elbowMoved.emit(point)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._start is not None:
            start = self._start
            end = event.position().toPoint()
            mode = self._mode
            handle = self._handle
            self._start = None
            self._current = None
            self._mode = None
            self._handle = None
            self.update()
            if mode == "resize" and handle:
                self.boxResized.emit(handle, start, end)
                self.boxInteractionFinished.emit()
            elif mode == "move":
                self.boxMoved.emit(start, end)
                self.boxInteractionFinished.emit()
            elif mode == "pointer":
                self.pointerMoved.emit(end)
                self.pointerInteractionFinished.emit()
            elif mode == "elbow":
                self.elbowMoved.emit(end)
                self.elbowInteractionFinished.emit()
            elif (start - end).manhattanLength() <= 4:
                self.positionClicked.emit(end)
            else:
                self.rectDrawn.emit(start, end)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Copy):
            self.copyRequested.emit()
            event.accept()
            return
        if event.matches(QKeySequence.Paste):
            self.pasteRequested.emit()
            event.accept()
            return
        if event.matches(QKeySequence.Undo):
            self.undoRequested.emit()
            event.accept()
            return
        if is_delete_key(event):
            self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def leaveEvent(self, event) -> None:
        if self._start is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._mode == "place" and self._start is not None and self._current is not None:
            painter = QPainter(self)
            painter.setPen(QPen(self.band_color, 2, Qt.DashLine))
            painter.drawLine(self._start, self._current)
            painter.end()


class TextEditPreviewLabel(PreviewImageLabel):
    positionClicked = Signal(QPoint)
    inlineEdited = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.inline_edit = QLineEdit(self)
        self.inline_edit.hide()
        self.inline_edit.setFrame(False)
        self.inline_edit.textEdited.connect(self.inlineEdited.emit)

    def mousePressEvent(self, event) -> None:
        if self.inline_edit.isVisible() and self.inline_edit.geometry().contains(event.position().toPoint()):
            super().mousePressEvent(event)
            return
        self.positionClicked.emit(event.position().toPoint())
        super().mousePressEvent(event)

    def hide_inline_editor(self) -> None:
        self.inline_edit.hide()
        self.inline_edit.clearFocus()


class ErasePreviewLabel(PreviewImageLabel):
    strokePoint = Signal(QPoint)
    strokeFinished = Signal()
    rectDrawn = Signal(QPoint, QPoint)
    pointClicked = Signal(QPoint)
    boxResized = Signal(str, QPoint, QPoint)
    boxMoved = Signal(QPoint, QPoint)
    boxInteractionFinished = Signal()
    inlineEdited = Signal(str)
    copyRequested = Signal()
    pasteRequested = Signal()
    undoRequested = Signal()
    deleteRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.tool = "brush"
        self.brush_radius_px = 16.0
        self.cover_color = QColor(255, 255, 255)
        self.box_rect = QRect()
        self.handles_enabled = False
        self.pending_box_delete = False
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self._hover: QPoint | None = None
        self._mode: str | None = None
        self._handle: str | None = None
        self.inline_edit = QTextEdit(self)
        self.inline_edit.setFrameShape(QFrame.NoFrame)
        self.inline_edit.setAcceptRichText(False)
        self.inline_edit.setPlaceholderText("在此輸入文字")
        self.inline_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.inline_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.inline_edit.setStyleSheet("QTextEdit { background: transparent; padding: 2px 4px; }")
        self.inline_edit.hide()
        self.inline_edit.textChanged.connect(lambda: self.inlineEdited.emit(self.inline_edit.toPlainText()))
        self.inline_edit.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.inline_edit:
            if event.type() == QEvent.MouseButtonPress:
                parent_pt = obj.mapToParent(event.position().toPoint())
                if self._handle_at(parent_pt) or rect_chrome_contains(self.box_rect, parent_pt):
                    self.hide_inline_editor()
                    arm_box_delete(self)
                    return True
                self.pending_box_delete = False
            elif event.type() in (QEvent.KeyPress, QEvent.ShortcutOverride) and event.matches(QKeySequence.Undo):
                if event.type() == QEvent.ShortcutOverride:
                    event.accept()
                    return True
                self.undoRequested.emit()
                return True
            elif event.type() == QEvent.KeyPress:
                if event.matches(QKeySequence.Copy):
                    self.copyRequested.emit()
                    return True
                if event.matches(QKeySequence.Paste):
                    self.pasteRequested.emit()
                    return True
                if self.pending_box_delete and is_delete_key(event):
                    self.deleteRequested.emit()
                    return True
                if event.text():
                    self.pending_box_delete = False
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Copy):
            self.copyRequested.emit()
            event.accept()
            return
        if event.matches(QKeySequence.Paste):
            self.pasteRequested.emit()
            event.accept()
            return
        if event.matches(QKeySequence.Undo):
            self.undoRequested.emit()
            event.accept()
            return
        if is_delete_key(event):
            self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _handle_at(self, point: QPoint) -> str | None:
        if not self.handles_enabled:
            return None
        for name, rect in annotation_handle_rects(self.box_rect).items():
            if rect.adjusted(-2, -2, 2, 2).contains(point):
                return name
        return None

    def _box_contains(self, point: QPoint) -> bool:
        if not self.handles_enabled or self.box_rect.width() < 2:
            return False
        return self.box_rect.adjusted(-2, -2, 2, 2).contains(point)

    def show_inline_editor(
        self,
        rect: QRect,
        text: str,
        font_size: int = 12,
        *,
        focus: bool = False,
        bold: bool = False,
        color_rgb: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        pad = 10
        self.inline_edit.setGeometry(rect.adjusted(pad, pad, -pad, -pad))
        font = self.inline_edit.font()
        font.setPointSize(max(int(font_size * 0.75), 8))
        font.setBold(bold)
        self.inline_edit.setFont(font)
        color = QColor.fromRgbF(*color_rgb)
        self.inline_edit.setStyleSheet(
            f"QTextEdit {{ background: transparent; padding: 2px 4px; color: {color.name()}; }}"
        )
        if self.inline_edit.toPlainText() != text:
            self.inline_edit.blockSignals(True)
            self.inline_edit.setPlainText(text)
            self.inline_edit.blockSignals(False)
        self.inline_edit.show()
        if focus:
            self.inline_edit.setFocus()

    def hide_inline_editor(self) -> None:
        self.inline_edit.hide()
        self.inline_edit.clearFocus()

    def mousePressEvent(self, event) -> None:
        point = event.position().toPoint()
        self._start = point
        self._current = point
        self._hover = point
        self._handle = None
        self._mode = None
        if self.tool == "text":
            handle = self._handle_at(point)
            self.pending_box_delete = False
            if handle:
                self._mode = "resize"
                self._handle = handle
                self.hide_inline_editor()
                arm_box_delete(self)
            elif rect_chrome_contains(self.box_rect, point):
                self._mode = "select"
                self.hide_inline_editor()
                arm_box_delete(self)
            elif self._box_contains(point):
                self._mode = "move"
                self.hide_inline_editor()
            else:
                self._mode = "place"
        elif self.tool == "brush":
            self.strokePoint.emit(self._start)
        self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        point = event.position().toPoint()
        self._hover = point
        if self._start is not None:
            self._current = point
            if self.tool == "brush":
                self.strokePoint.emit(self._current)
            elif self._mode == "resize" and self._handle:
                self.boxResized.emit(self._handle, self._start, point)
            elif self._mode == "move":
                self.boxMoved.emit(self._start, point)
        self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._start is not None:
            start = self._start
            end = event.position().toPoint()
            self._hover = end
            mode = self._mode
            handle = self._handle
            self._start = None
            self._current = None
            self._mode = None
            self._handle = None
            self.update()
            if self.tool == "brush":
                self.strokeFinished.emit()
            elif mode == "resize" and handle:
                self.boxResized.emit(handle, start, end)
                self.boxInteractionFinished.emit()
            elif mode == "move":
                if (start - end).manhattanLength() > 4:
                    self.boxMoved.emit(start, end)
                self.boxInteractionFinished.emit()
            elif mode == "select":
                arm_box_delete(self)
            elif (start - end).manhattanLength() > 4:
                self.rectDrawn.emit(start, end)
            elif self.tool == "text":
                self.pointClicked.emit(end)
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        if hasattr(event, "position"):
            self._hover = event.position().toPoint()
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._start is None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        fill = QColor(self.cover_color)
        if self.tool == "brush" and self._hover is not None:
            radius = max(int(round(self.brush_radius_px)), 4)
            fill.setAlpha(70)
            outline = QColor("#111827") if self.cover_color.lightness() > 160 else QColor("#f8fafc")
            painter.setBrush(fill)
            painter.setPen(QPen(outline, 3))
            painter.drawEllipse(self._hover, radius, radius)
            painter.setPen(QPen(outline, 2))
            painter.drawLine(self._hover.x() - 5, self._hover.y(), self._hover.x() + 5, self._hover.y())
            painter.drawLine(self._hover.x(), self._hover.y() - 5, self._hover.x(), self._hover.y() + 5)
        elif self.tool == "rect" and self._start is not None and self._current is not None:
            fill.setAlpha(170)
            painter.setBrush(fill)
            painter.setPen(QPen(QColor("#111827"), 2))
            painter.drawRect(QRect(self._start, self._current).normalized())
        elif self.tool == "text" and self._mode == "place" and self._start is not None and self._current is not None:
            painter.setBrush(QColor(255, 255, 255, 40))
            painter.setPen(QPen(QColor("#128576"), 2, Qt.DashLine))
            painter.drawRect(QRect(self._start, self._current).normalized())
        if self.tool == "text" and self.handles_enabled and self.box_rect.width() > 1:
            painter.setPen(QPen(QColor("#128576"), 1))
            painter.setBrush(QColor("#ffffff"))
            for handle in annotation_handle_rects(self.box_rect).values():
                painter.drawRect(handle)
        painter.end()


class MarkupPreviewLabel(PreviewImageLabel):
    """Preview label that supports rubber-band rectangle drawing and clicks."""

    rectDrawn = Signal(QPoint, QPoint)
    pointClicked = Signal(QPoint)
    copyRequested = Signal()
    pasteRequested = Signal()
    undoRequested = Signal()
    deleteRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)
        self.band_color = QColor(18, 133, 118)
        self.pending_box_delete = False
        self._start: QPoint | None = None
        self._current: QPoint | None = None

    def mousePressEvent(self, event) -> None:
        self._start = event.position().toPoint()
        self._current = self._start
        self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._start is not None:
            self._current = event.position().toPoint()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._start is not None:
            start = self._start
            end = event.position().toPoint()
            self._start = None
            self._current = None
            self.update()
            if (start - end).manhattanLength() <= 4:
                self.pointClicked.emit(end)
            else:
                self.rectDrawn.emit(start, end)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Copy):
            self.copyRequested.emit()
            event.accept()
            return
        if event.matches(QKeySequence.Paste):
            self.pasteRequested.emit()
            event.accept()
            return
        if event.matches(QKeySequence.Undo):
            self.undoRequested.emit()
            event.accept()
            return
        if is_delete_key(event):
            self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._start is not None and self._current is not None:
            painter = QPainter(self)
            pen = QPen(self.band_color, 2, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(QRect(self._start, self._current).normalized())
            painter.end()


class PdfDropPanel(QWidget):
    filesDropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile()]
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class PageGrid(QListWidget):
    filesDropped = Signal(list)
    # Emitted on a manual drag-reorder with the selected source rows and the
    # target insertion index.
    reorderRequested = Signal(list, int)

    def __init__(self) -> None:
        super().__init__()
        self._press_pos: QPoint | None = None
        self._press_row = -1
        self._dragging = False
        self._drag_rows: list[int] = []
        self._cursor_pos: QPoint | None = None
        self._indicator_index = -1
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setViewMode(QListWidget.IconMode)
        self.setMovement(QListWidget.Static)
        self.setResizeMode(QListWidget.Adjust)
        self.setWrapping(True)
        self.setSpacing(24)
        self.setIconSize(ICON_SIZE)
        self.setGridSize(THUMB_SIZE)
        self.setUniformItemSizes(True)
        # Reordering is handled manually via mouse events (see mousePressEvent /
        # mouseMoveEvent / mouseReleaseEvent) instead of Qt's drag-and-drop.
        # Qt's built-in DnD reorder is unreliable in IconMode (drops get a "no
        # drop" cursor), so we drive it ourselves for a predictable experience.
        # Qt DnD is kept only for accepting external file drops.
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QListWidget.DropOnly)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setStyleSheet(
            """
            QListWidget {
                border: 1px solid #c8c5bd;
                background: #f7f7f4;
                padding: 18px;
            }
            QListWidget::item {
                background: #ffffff;
                border: 1px solid #d2d2d2;
                border-radius: 8px;
                padding: 10px;
                margin: 4px;
            }
            QListWidget::item:selected {
                background: #d9f0ea;
                border: 2px solid #128576;
                color: #10201d;
            }
            """
        )

    # --- external file drops -------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile()]
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    # --- manual drag-reorder -------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            item = self.itemAt(self._press_pos)
            self._press_row = self.row(item) if item is not None else -1
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (event.buttons() & Qt.LeftButton) and self._press_pos is not None and self._press_row >= 0:
            if not self._dragging:
                moved = (event.position().toPoint() - self._press_pos).manhattanLength()
                if moved >= QApplication.startDragDistance():
                    rows = sorted(self.row(item) for item in self.selectedItems())
                    if self._press_row not in rows:
                        rows = [self._press_row]
                    self._dragging = True
                    self._drag_rows = rows
                    self.setCursor(Qt.ClosedHandCursor)
            if self._dragging:
                self._cursor_pos = event.position().toPoint()
                self._indicator_index = self.insertion_index_at(self._cursor_pos)
                self.viewport().update()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            target = self.insertion_index_at(event.position().toPoint())
            rows = list(self._drag_rows)
            self._reset_drag_state()
            if rows:
                self.reorderRequested.emit(rows, target)
            return
        self._press_pos = None
        self._press_row = -1
        super().mouseReleaseEvent(event)

    def _reset_drag_state(self) -> None:
        self._dragging = False
        self._drag_rows = []
        self._cursor_pos = None
        self._indicator_index = -1
        self._press_pos = None
        self._press_row = -1
        self.unsetCursor()
        self.viewport().update()

    def insertion_index_at(self, point: QPoint) -> int:
        if self.count() == 0:
            return 0
        item = self.itemAt(point)
        if item is None:
            # Past the last item / empty area: find the nearest item to decide.
            nearest = self._nearest_row(point)
            if nearest < 0:
                return self.count()
            rect = self.visualItemRect(self.item(nearest))
            if point.y() > rect.bottom() or (point.y() >= rect.top() and point.x() > rect.center().x()):
                return nearest + 1
            return nearest
        row = self.row(item)
        rect = self.visualItemRect(item)
        if point.x() > rect.center().x():
            return row + 1
        return row

    def _nearest_row(self, point: QPoint) -> int:
        best_row = -1
        best_distance = None
        for row in range(self.count()):
            center = self.visualItemRect(self.item(row)).center()
            distance = (center - point).manhattanLength()
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_row = row
        return best_row

    def insertion_line_geometry(self, index: int) -> tuple[int, int, int] | None:
        if index < 0 or self.count() == 0:
            return None
        gap = max(self.spacing() // 2, 4)
        if index >= self.count():
            rect = self.visualItemRect(self.item(self.count() - 1))
            return rect.right() + gap, rect.top(), rect.bottom()
        rect = self.visualItemRect(self.item(index))
        return rect.left() - gap, rect.top(), rect.bottom()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._dragging:
            return
        painter = QPainter(self.viewport())
        geometry = self.insertion_line_geometry(self._indicator_index)
        if geometry is not None:
            x, top, bottom = geometry
            pen = QPen(QColor("#128576"))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawLine(x, top, x, bottom)
        if self._cursor_pos is not None and self._drag_rows:
            source_item = self.item(self._drag_rows[0])
            if source_item is not None:
                preview = source_item.icon().pixmap(ICON_SIZE).scaled(
                    96, 126, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                painter.setOpacity(0.75)
                painter.drawPixmap(self._cursor_pos.x() + 10, self._cursor_pos.y() + 10, preview)
        painter.end()


class PdfDropTabWidget(QTabWidget):
    filesDropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.has_pdf_urls(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self.has_pdf_urls(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if self.has_pdf_urls(event):
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile()]
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def has_pdf_urls(self, event) -> bool:
        if not event.mimeData().hasUrls():
            return False
        return any(Path(url.toLocalFile()).suffix.lower() == ".pdf" for url in event.mimeData().urls())


class MergeSourceList(QListWidget):
    beforeInternalMove = Signal()

    def dropEvent(self, event: QDropEvent) -> None:
        if event.source() is self:
            self.beforeInternalMove.emit()
        super().dropEvent(event)


class MergeFilesDialog(QDialog):
    def __init__(self, main_window: "VictorPdfToolsQt") -> None:
        super().__init__(main_window)
        self.main_window = main_window
        self.undo_stack: list[list[tuple[str, list[PageItem]]]] = []
        self.setWindowTitle("合併文件")
        self.setGeometry(preferred_window_geometry(QSize(760, 520)))

        layout = QVBoxLayout(self)
        self.hint_label = QLabel("選擇要合併的文件，然後拖拉圖示調整文件順序。")
        self.hint_label.setObjectName("muted")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        controls = QHBoxLayout()
        main_window.add_button(controls, "加入目前 Tab", self.add_current_tab)
        main_window.add_button(controls, "加入所有已開 Tab", self.add_open_tabs)
        main_window.add_button(controls, "加入外部 PDF", self.add_external_pdf)
        main_window.add_button(controls, "移除選取", self.remove_selected, "danger")
        main_window.add_button(controls, "復原", self.undo_last)
        main_window.add_button(controls, "清空清單", self.clear_sources, "danger")
        controls.addStretch(1)
        layout.addLayout(controls)

        self.source_list = MergeSourceList()
        self.source_list.setDragEnabled(True)
        self.source_list.setAcceptDrops(True)
        self.source_list.setDropIndicatorShown(True)
        self.source_list.setDefaultDropAction(Qt.MoveAction)
        self.source_list.setDragDropMode(QListWidget.InternalMove)
        self.source_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.source_list.setViewMode(QListWidget.IconMode)
        self.source_list.setMovement(QListWidget.Snap)
        self.source_list.setResizeMode(QListWidget.Adjust)
        self.source_list.setWrapping(True)
        self.source_list.setSpacing(14)
        self.source_list.setIconSize(ICON_SIZE)
        self.source_list.setGridSize(THUMB_SIZE)
        self.source_list.setStyleSheet(
            """
            QListWidget {
                border: 1px solid #c8c5bd;
                background: #f7f7f4;
                padding: 18px;
            }
            QListWidget::item {
                background: #ffffff;
                border: 1px solid #d2d2d2;
                border-radius: 8px;
                padding: 10px;
                margin: 4px;
            }
            QListWidget::item:selected {
                background: #d9f0ea;
                border: 2px solid #128576;
                color: #10201d;
            }
            """
        )
        self.source_list.beforeInternalMove.connect(self.push_undo)
        self.source_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.source_list.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.source_list, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        undo_action = QAction("復原", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self.undo_last)
        self.addAction(undo_action)

        remove_action = QAction("移除選取", self)
        remove_action.setShortcut("Delete")
        remove_action.triggered.connect(self.remove_selected)
        self.addAction(remove_action)

    def snapshot_sources(self) -> list[tuple[str, list[PageItem]]]:
        snapshot: list[tuple[str, list[PageItem]]] = []
        for index in range(self.source_list.count()):
            item = self.source_list.item(index)
            title = item.text().split("\n", 1)[0]
            snapshot.append((title, list(item.data(Qt.UserRole))))
        return snapshot

    def restore_snapshot(self, snapshot: list[tuple[str, list[PageItem]]]) -> None:
        self.source_list.clear()
        for title, items in snapshot:
            self._add_source_item(title, items)
        self.update_hint()

    def push_undo(self) -> None:
        self.undo_stack.append(self.snapshot_sources())

    def undo_last(self) -> None:
        if not self.undo_stack:
            QMessageBox.information(self, "合併文件", "沒有可復原的動作。")
            return
        self.restore_snapshot(self.undo_stack.pop())

    def update_hint(self) -> None:
        count = self.source_list.count()
        if count == 0:
            self.hint_label.setText("尚未加入文件。可用上方按鈕加入，或拖入外部 PDF。")
            return
        self.hint_label.setText(
            f"已加入 {count} 個文件。點選文件後可按「移除選取」、Delete 或右鍵移除；Ctrl+Z 可復原上一個動作。"
        )

    def show_context_menu(self, position) -> None:
        item = self.source_list.itemAt(position)
        if item is None:
            return
        if item not in self.source_list.selectedItems():
            self.source_list.clearSelection()
            item.setSelected(True)
        menu = QMenu(self)
        menu.addAction("移除選取", self.remove_selected)
        menu.addAction("復原", self.undo_last)
        menu.exec(self.source_list.mapToGlobal(position))

    def add_current_tab(self) -> None:
        grid = self.main_window.current_grid()
        if not isinstance(grid, PageGrid):
            return
        self.push_undo()
        self.add_grid_source(grid, record_undo=False)
        self.update_hint()

    def add_open_tabs(self, *, silent_if_empty: bool = False) -> None:
        grids = [
            self.main_window.document_tabs.widget(index)
            for index in range(self.main_window.document_tabs.count())
        ]
        grids = [grid for grid in grids if isinstance(grid, PageGrid)]
        if not any(self.main_window.workspaces.get(grid, {}).get("items") for grid in grids):
            if not silent_if_empty:
                QMessageBox.information(self, "合併文件", "目前沒有可加入的文件 Tab。")
            return
        self.push_undo()
        for grid in grids:
            self.add_grid_source(grid, record_undo=False)
        self.update_hint()

    def add_external_pdf(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "加入外部 PDF", "", "PDF files (*.pdf)")
        if not files:
            return
        self.push_undo()
        added = 0
        for raw_path in files:
            path = Path(raw_path)
            try:
                reader = open_reader(path, self.main_window.password_input.text())
            except Exception as exc:
                self.main_window.show_error(exc)
                continue
            items = [PageItem(path, page_index, f"{path.name} - Page {page_index + 1}") for page_index in range(len(reader.pages))]
            self._add_source_item(path.name, items)
            added += 1
        if added == 0:
            self.undo_stack.pop()
        else:
            self.update_hint()

    def add_grid_source(self, grid: PageGrid, *, record_undo: bool = True) -> None:
        workspace = self.main_window.workspaces.get(grid)
        if not workspace or not workspace["items"]:
            return
        if record_undo:
            self.push_undo()
        title = self.main_window.document_tabs.tabText(self.main_window.document_tabs.indexOf(grid))
        self._add_source_item(title, list(workspace["items"]))
        if record_undo:
            self.update_hint()

    def add_source(self, title: str, items: list[PageItem], *, record_undo: bool = True) -> None:
        if not items:
            return
        if record_undo:
            self.push_undo()
        self._add_source_item(title, items)
        if record_undo:
            self.update_hint()

    def _add_source_item(self, title: str, items: list[PageItem]) -> None:
        list_item = QListWidgetItem(self.main_window.placeholder_icon, f"{title}\n{len(items)} 頁")
        list_item.setData(Qt.UserRole, items)
        list_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        list_item.setSizeHint(THUMB_SIZE)
        self.source_list.addItem(list_item)

    def remove_selected(self) -> None:
        selected = self.source_list.selectedItems()
        if not selected:
            QMessageBox.information(self, "合併文件", "請先點選要移除的文件。")
            return
        self.push_undo()
        for item in selected:
            self.source_list.takeItem(self.source_list.row(item))
        self.update_hint()

    def clear_sources(self) -> None:
        if self.source_list.count() == 0:
            return
        self.push_undo()
        self.source_list.clear()
        self.update_hint()

    def page_items(self) -> list[PageItem]:
        items: list[PageItem] = []
        for index in range(self.source_list.count()):
            items.extend(self.source_list.item(index).data(Qt.UserRole))
        return items


class PagePreviewDialog(QDialog):
    def __init__(self, parent: "VictorPdfToolsQt", item: PageItem, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setGeometry(preferred_window_geometry(QSize(900, 720)))

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignCenter)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        image = parent.render_page_preview(item)
        pixmap = QPixmap.fromImage(ImageQt(image))
        label.setPixmap(pixmap)
        label.resize(pixmap.size())
        scroll.setWidget(label)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class AuditLogDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("處理紀錄")
        self.resize(820, 440)
        layout = QVBoxLayout(self)
        hint = QLabel("本機處理紀錄（最新在上）。不會上傳任何檔案。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["時間", "操作", "來源", "輸出", "說明"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        refresh = QPushButton("重新整理")
        refresh.clicked.connect(self.reload)
        open_file = QPushButton("開啟紀錄檔")
        open_file.clicked.connect(self._open_log_file)
        close_btn = QPushButton("關閉")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(refresh)
        buttons.addWidget(open_file)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)
        self.reload()

    def reload(self) -> None:
        events = read_audit_events(500)
        self.table.setRowCount(len(events))
        for row, event in enumerate(events):
            values = [event.timestamp, event.operation, event.source, event.target, event.detail]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        if events:
            self.table.resizeColumnsToContents()

    def _open_log_file(self) -> None:
        path = audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")
        reveal_output(path)


class VictorPdfToolsQt(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Victor PDF Tools Box")
        self.setAcceptDrops(True)

        self.workspaces: dict[PageGrid, dict] = {}
        self.page_grid: PageGrid | None = None
        self.page_items: list[PageItem] = []
        self.thumbnail_cache: dict[tuple[str, int, int], QIcon] = {}
        self._pdfium_docs: dict[str, object] = {}
        self.page_clipboard: list[PageItem] = []
        self.tool_file_items: list[Path] = []
        self.office_file_items: list[Path] = []
        self.pdf_office_file_items: list[Path] = []
        self._last_tool_status_message = ""
        self._tool_aux_path: Path | None = None
        self.annotation_pdf_path: Path | None = None
        self.annotation_page_count = 0
        self.annotation_page_size = (0.0, 0.0)
        self.annotation_preview_image: Image.Image | None = None
        self.annotation_color_rgb = (0.0, 0.0, 0.0)
        self.annotation_fill_rgb = (1.0, 1.0, 1.0)
        self.annotation_fill_none = False
        self.annotation_box_pdf: tuple[float, float] | None = None
        self.annotation_box_locked = False
        self.annotation_items: list[dict] = []
        self._annotation_placed = False
        self._annotation_manual_size = False
        self._fitting_annotation_box = False
        self._annotation_resize_snapshot: tuple[float, float, float, float] | None = None
        self._annotation_clipboard: dict | None = None
        self._annotation_undo_stack: list[dict] = []
        self._restoring_annotation = False
        self._markup_clipboard: MarkupAnnotation | None = None
        self._markup_undo_stack: list[list[tuple[int, MarkupAnnotation]]] = []
        self._syncing_advanced_page = False
        self._advanced_thumb_pending: list[int] = []
        self._advanced_thumb_generation = 0
        self._advanced_thumb_timer = QTimer(self)
        self._advanced_thumb_timer.setSingleShot(True)
        self._advanced_thumb_timer.timeout.connect(self._render_next_advanced_thumb_batch)
        self._advanced_thumb_resize_timer = QTimer(self)
        self._advanced_thumb_resize_timer.setSingleShot(True)
        self._advanced_thumb_resize_timer.timeout.connect(self._refresh_advanced_thumbs_for_width)
        self.advanced_preview_zoom = 1.15
        self.text_edit_pdf_path: Path | None = None
        self.text_edit_page_count = 0
        self.text_edit_blocks: list[TextBlock] = []
        self.bookmark_pdf_path: Path | None = None
        self.bookmark_page_count = 0
        self.bookmark_items: list[BookmarkItem] = []
        self.markup_pdf_path: Path | None = None
        self.markup_page_count = 0
        self.markup_page_size = (0.0, 0.0)
        self.markup_preview_image: Image.Image | None = None
        self.markup_items: list[tuple[int, MarkupAnnotation]] = []
        self.markup_color_rgb = MARKUP_COLOR_PRESETS["yellow"]
        self.markup_fill_rgb = (1.0, 1.0, 1.0)
        self.markup_fill_none = False
        self.crop_pdf_path: Path | None = None
        self.crop_page_count = 0
        self.crop_page_size = (0.0, 0.0)
        self.crop_preview_image: Image.Image | None = None
        self.crop_rect: tuple[float, float, float, float] | None = None
        self.erase_pdf_path: Path | None = None
        self.erase_page_count = 0
        self.erase_page_size = (0.0, 0.0)
        self.erase_preview_image: Image.Image | None = None
        self.erase_marks: list[EraseMark] = []
        self._erase_live_points: list[tuple[float, float]] = []
        self._erase_text_selected: int | None = None
        self._erase_text_clipboard: dict | None = None
        self._erase_undo_stack: list[tuple] = []
        self._erase_text_seq = 0
        self._erase_syncing_text = False
        self._erase_resize_snapshot: tuple[float, float, float, float] | None = None
        self._erase_last_click: QPoint | None = None
        self.erase_text_color_rgb_value = (0.0, 0.0, 0.0)
        self._broadcasting_advanced_pdf = False
        self.text_edit_preview_image: Image.Image | None = None
        self.placeholder_icon = QIcon(QPixmap.fromImage(ImageQt(self.placeholder_thumbnail(None))))

        self.stats_label = QLabel("總頁數：0　已選取：0")
        self.stats_label.setObjectName("muted")
        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("例如 1-12,15-18；留空則用選取頁")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("如 PDF 已加密，在此輸入密碼")

        self.build_ui()
        self.install_shortcuts()
        self._install_editor_box_delete_disarm()
        self.setStatusBar(QStatusBar())
        self.create_document_tab("未命名")
        self.apply_startup_geometry()
        self.set_status("可把 PDF 拖進「組織」加入全頁縮圖；雙擊縮圖可大圖預覽。進階編輯請用「文件工作台」。")

    def apply_startup_geometry(self) -> None:
        """Fit the first open size to the usable desktop, and keep the window resizable."""

        geometry = preferred_window_geometry()
        # Soft minimum: never larger than the available desktop.
        self.setMinimumSize(
            min(WINDOW_MIN_SIZE.width(), geometry.width()),
            min(WINDOW_MIN_SIZE.height(), geometry.height()),
        )
        self.setGeometry(geometry)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.has_pdf_urls(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self.has_pdf_urls(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if self.has_pdf_urls(event):
            paths = self.paths_from_drop_event(event)
            pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() == ".pdf"]
            if not pdf_paths:
                event.ignore()
                return
            workspace_index = self.main_tabs.indexOf(self._workspace_tab)
            open_in_workspace = self.main_tabs.currentIndex() == workspace_index
            self.add_files_from_paths([str(path) for path in pdf_paths])
            if open_in_workspace:
                self.main_tabs.setCurrentIndex(workspace_index)
                self.document_workspace.open_path(pdf_paths[0])
                extra = f"；另加入 {len(pdf_paths) - 1} 個檔案。" if len(pdf_paths) > 1 else "。"
                self.set_status(f"已加入組織並在文件工作台開啟 {pdf_paths[0].name}{extra}")
            else:
                extra = f"；共 {len(pdf_paths)} 個檔案。" if len(pdf_paths) > 1 else "。"
                self.set_status(f"已拖入加入組織：{pdf_paths[0].name}{extra}")
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def _on_workspace_files_dropped(self, paths: list[str]) -> None:
        pdf_paths = [path for path in paths if Path(path).suffix.lower() == ".pdf"]
        if pdf_paths:
            self.add_files_from_paths(pdf_paths)

    def has_pdf_urls(self, event) -> bool:
        if not event.mimeData().hasUrls():
            return False
        return any(Path(url.toLocalFile()).suffix.lower() == ".pdf" for url in event.mimeData().urls())

    def paths_from_drop_event(self, event: QDropEvent) -> list[str]:
        return [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile()]

    def build_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #e9e7e1; color: #111; font-size: 10pt; }
            QLabel#title { font-size: 18pt; font-weight: 700; }
            QLabel#muted { color: #52697a; }
            QPushButton {
                min-height: 28px;
                padding: 4px 12px;
                border: 1px solid #9f9d96;
                border-radius: 6px;
                background: #f7f6f2;
            }
            QPushButton:hover { background: #ffffff; border-color: #128576; }
            QPushButton#primary { background: #128576; color: #ffffff; border-color: #0d6f63; }
            QPushButton#danger { color: #9d2828; }
            QLineEdit, QComboBox {
                min-height: 28px;
                padding: 2px 8px;
                border: 1px solid #aaa69d;
                border-radius: 6px;
                background: #ffffff;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QFrame#panel { border: 1px solid #c4c1b8; border-radius: 8px; }
            QTabWidget#documentTabs::pane {
                border: 1px solid #b7b3a8;
                border-radius: 6px;
                top: -1px;
                background: #f4f2ec;
            }
            QTabWidget#documentTabs QTabBar::tab {
                background: #ddd9cf;
                color: #222;
                border: 1px solid #b7b3a8;
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                min-width: 72px;
                max-width: 160px;
                min-height: 28px;
                padding: 6px 12px;
                margin-right: 3px;
            }
            QTabWidget#documentTabs QTabBar::tab:selected {
                background: #ffffff;
                color: #0d6f63;
                font-weight: 700;
                border-color: #128576;
            }
            QTabWidget#documentTabs QTabBar::tab:hover {
                background: #f7f6f2;
            }
            """
        )

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(4)

        title = QLabel("Victor PDF Tools Box")
        title.setObjectName("title")
        title.setStyleSheet("font-size: 13pt; font-weight: 700;")
        subtitle = QLabel("「組織」管理多份 PDF 的頁面；「文件工作台」打開一份 PDF 閱讀、註解和編輯。")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.main_tabs = tabs

        tabs.addTab(self.build_organize_tab(), "組織")

        workspace_tab = QWidget()
        workspace_layout = QVBoxLayout(workspace_tab)
        workspace_layout.setContentsMargins(0, 4, 0, 0)
        self.document_workspace = DocumentWorkspace()
        self.document_workspace.status_changed.connect(self.set_status)
        self.document_workspace.files_dropped.connect(self._on_workspace_files_dropped)
        workspace_layout.addWidget(self.document_workspace)
        self._workspace_tab = workspace_tab
        tabs.addTab(workspace_tab, "文件工作台")

        self._tools_tab = self.build_tools_tab()
        tabs.addTab(self._tools_tab, "常用工具")

        self._office_tab = self.build_office_convert_tab()
        tabs.addTab(self._office_tab, "Office 轉 PDF")

        self._pdf_office_tab = self.build_pdf_to_office_tab()
        tabs.addTab(self._pdf_office_tab, "PDF 轉 Office")

        advanced_root = PdfDropPanel()
        advanced_root.filesDropped.connect(self.drop_advanced_pdf)
        advanced_layout = QVBoxLayout(advanced_root)
        advanced_layout.setContentsMargins(0, 8, 0, 0)
        advanced_layout.setSpacing(6)
        share_hint = QLabel("將 PDF 拖到進階任一頁即可共用；拖左邊分隔線可拉寬縮圖。左側縮圖可換頁編輯，各工具都可改完多頁後才另存。")
        share_hint.setObjectName("muted")
        share_hint.setWordWrap(True)
        advanced_layout.addWidget(share_hint)
        self.advanced_thumb_panel = QFrame()
        self.advanced_thumb_panel.setObjectName("panel")
        self.advanced_thumb_panel.setMinimumWidth(ADVANCED_THUMB_PANEL_MIN_WIDTH)
        self.advanced_thumb_panel.setMaximumWidth(ADVANCED_THUMB_PANEL_MAX_WIDTH)
        thumb_layout = QVBoxLayout(self.advanced_thumb_panel)
        thumb_layout.setContentsMargins(8, 8, 8, 8)
        thumb_layout.setSpacing(6)
        thumb_title = QLabel("頁面（可拉寬）")
        thumb_layout.addWidget(thumb_title)
        self.advanced_page_list = QListWidget()
        self.advanced_page_list.setViewMode(QListWidget.ListMode)
        self.advanced_page_list.setFlow(QListView.TopToBottom)
        self.advanced_page_list.setWrapping(False)
        self.advanced_page_list.setMovement(QListWidget.Static)
        self.advanced_page_list.setIconSize(ADVANCED_THUMB_ICON_SIZE)
        self.advanced_page_list.setSpacing(6)
        self.advanced_page_list.setUniformItemSizes(True)
        self.advanced_page_list.setWordWrap(True)
        self.advanced_page_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.advanced_page_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.advanced_page_list.setStyleSheet(
            """
            QListWidget {
                background: #f7f6f2;
                border: none;
                padding: 4px;
            }
            QListWidget::item {
                background: #ffffff;
                border: 1px solid #d2d2d2;
                border-radius: 8px;
                padding: 4px;
                margin: 3px 1px;
                color: #222;
            }
            QListWidget::item:selected {
                background: #d9f0ea;
                border: 2px solid #128576;
            }
            """
        )
        self.advanced_page_list.currentRowChanged.connect(self._on_advanced_thumb_selected)
        thumb_layout.addWidget(self.advanced_page_list, 1)
        advanced_tabs = QTabWidget()
        advanced_tabs.addTab(self.build_annotation_tab(), "文字標註 / 覆蓋")
        advanced_tabs.addTab(self.build_markup_tab(), "螢光 / 圖形註解")
        advanced_tabs.addTab(self.build_crop_tab(), "裁切頁面")
        advanced_tabs.addTab(self.build_erase_tab(), "橡皮擦 / 遮擋")
        self._text_edit_tab = self.build_text_edit_tab()
        advanced_tabs.addTab(self._text_edit_tab, "文字編輯 Beta")
        advanced_tabs.addTab(self.build_bookmark_tab(), "書籤 / 目錄")
        self.advanced_tabs = advanced_tabs
        advanced_tabs.currentChanged.connect(self._on_advanced_subtab_changed)
        self.advanced_splitter = QSplitter(Qt.Horizontal)
        self.advanced_splitter.setChildrenCollapsible(False)
        self.advanced_splitter.addWidget(self.advanced_thumb_panel)
        self.advanced_splitter.addWidget(advanced_tabs)
        self.advanced_splitter.setStretchFactor(0, 0)
        self.advanced_splitter.setStretchFactor(1, 1)
        self.advanced_splitter.setSizes([ADVANCED_THUMB_PANEL_WIDTH, 980])
        self.advanced_splitter.splitterMoved.connect(self._on_advanced_splitter_moved)
        advanced_layout.addWidget(self.advanced_splitter, 1)
        self._advanced_tab = advanced_root
        tabs.addTab(advanced_root, "進階")

        tabs.setCurrentIndex(0)
        layout.addWidget(tabs, 1)
        self.setCentralWidget(root)

        self._build_window_menu()

        open_action = QAction("加入 PDF", self)
        open_action.triggered.connect(self.choose_pdf_files)
        self.addAction(open_action)
        self.load_output_preferences()

    def _build_window_menu(self) -> None:
        menu_bar = self.menuBar()
        window_menu = menu_bar.addMenu("視窗")
        show_organize = QAction("組織", self)
        show_organize.triggered.connect(lambda: self.main_tabs.setCurrentIndex(0))
        window_menu.addAction(show_organize)
        show_workspace = QAction("文件工作台", self)
        show_workspace.triggered.connect(lambda: self.main_tabs.setCurrentIndex(1))
        window_menu.addAction(show_workspace)
        show_tools = QAction("常用工具", self)
        show_tools.triggered.connect(lambda: self.main_tabs.setCurrentWidget(self._tools_tab))
        window_menu.addAction(show_tools)
        show_office = QAction("Office 轉 PDF", self)
        show_office.triggered.connect(lambda: self.main_tabs.setCurrentWidget(self._office_tab))
        window_menu.addAction(show_office)
        show_pdf_office = QAction("PDF 轉 Office", self)
        show_pdf_office.triggered.connect(lambda: self.main_tabs.setCurrentWidget(self._pdf_office_tab))
        window_menu.addAction(show_pdf_office)
        show_advanced = QAction("進階工具", self)
        show_advanced.triggered.connect(lambda: self.main_tabs.setCurrentWidget(self._advanced_tab))
        window_menu.addAction(show_advanced)

    def install_shortcuts(self) -> None:
        shortcuts = [
            ("Ctrl+C", self.copy_selected_pages),
            ("Ctrl+X", self.cut_selected_pages),
            ("Ctrl+V", self.paste_pages),
            ("Ctrl+Z", self.undo_last_action),
            ("Delete", self.remove_selected_pages),
        ]
        for key, callback in shortcuts:
            action = QAction(self)
            action.setShortcut(key)
            action.triggered.connect(callback)
            self.addAction(action)

    def _install_editor_box_delete_disarm(self) -> None:
        for name in ("annotation_text_input", "markup_note_input", "erase_text_input"):
            editor = getattr(self, name, None)
            if editor is not None:
                editor.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if isinstance(obj, (QLineEdit, QTextEdit)):
            if event.type() == QEvent.MouseButtonPress:
                inline = getattr(getattr(self, "erase_preview_label", None), "inline_edit", None)
                if obj is not inline:
                    self._clear_box_delete_arm()
            elif event.type() in (QEvent.KeyPress, QEvent.ShortcutOverride) and event.matches(QKeySequence.Undo) and self._box_undo_tab_active():
                if event.type() == QEvent.ShortcutOverride:
                    event.accept()
                    return True
                self.undo_last_action()
                return True
        return super().eventFilter(obj, event)

    def build_organize_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        toolbar = QWidget()
        self.organize_toolbar = toolbar
        controls = FlowLayout(toolbar, margin=0, hspacing=6, vspacing=6)
        self.add_button(controls, "加入 PDF", self.choose_pdf_files)
        self.add_button(controls, "在工作台開啟", self.open_current_pdf_in_workspace)
        self.add_button(controls, "複製頁", self.copy_selected_pages)
        self.add_button(controls, "剪下頁", self.cut_selected_pages)
        self.add_button(controls, "貼上頁", self.paste_pages)
        self.add_button(controls, "復原", self.undo_last_action)
        self.add_button(controls, "刪除頁", self.remove_selected_pages, "danger")
        self.add_button(controls, "清空目前 Tab", self.clear_pages)
        self.add_button(controls, "選取左轉", lambda: self.rotate_selected_pages(270))
        self.add_button(controls, "選取右轉", lambda: self.rotate_selected_pages(90))
        controls.addWidget(self.stats_label)
        left_layout.addWidget(toolbar)

        drag_hint = QLabel("提示：每個 PDF 會開成上方獨立 Tab；雙擊縮圖可大圖預覽，右鍵或上方按鈕可在工作台開啟此檔。")
        drag_hint.setObjectName("muted")
        drag_hint.setWordWrap(True)
        left_layout.addWidget(drag_hint)

        self.document_tabs = PdfDropTabWidget()
        self.document_tabs.setObjectName("documentTabs")
        self.document_tabs.filesDropped.connect(self.add_files_from_paths)
        self.document_tabs.setTabsClosable(True)
        self.document_tabs.setMovable(True)
        self.document_tabs.setDocumentMode(False)
        self.document_tabs.setUsesScrollButtons(True)
        self.document_tabs.tabBar().setElideMode(Qt.ElideMiddle)
        self.document_tabs.tabBar().setExpanding(False)
        self.document_tabs.currentChanged.connect(self.on_document_tab_changed)
        self.document_tabs.tabCloseRequested.connect(self.close_document_tab)
        left_layout.addWidget(self.document_tabs, 1)
        layout.addWidget(left, 1)

        side = QFrame()
        side.setObjectName("panel")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

        side_layout.addWidget(QLabel("頁面排序"))
        self.add_button(side_layout, "上移", lambda: self.move_selected_page(-1))
        self.add_button(side_layout, "下移", lambda: self.move_selected_page(1))
        save_button = self.add_button(side_layout, "儲存目前 Tab PDF", self.export_arranged_pdf, "primary")
        save_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.open_pdf_after_save_checkbox = QCheckBox("儲存 PDF 後開成新 Tab")
        self.open_pdf_after_save_checkbox.setChecked(True)
        self.open_pdf_after_save_checkbox.toggled.connect(self.save_output_preferences)
        side_layout.addWidget(self.open_pdf_after_save_checkbox)
        self.open_folder_after_export_checkbox = QCheckBox("匯出後開啟輸出資料夾")
        self.open_folder_after_export_checkbox.setChecked(True)
        self.open_folder_after_export_checkbox.toggled.connect(self.save_output_preferences)
        side_layout.addWidget(self.open_folder_after_export_checkbox)

        side_layout.addSpacing(12)
        side_layout.addWidget(QLabel("擷取頁碼範圍"))
        side_layout.addWidget(self.range_input)
        hint = QLabel("可輸入 1-12,15-18。留空時使用目前 Tab 已選取的縮圖頁面。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        side_layout.addWidget(hint)
        self.add_button(side_layout, "擷取選取 - 合併", self.extract_pages_merged)
        self.add_button(side_layout, "擷取選取 - 單獨", self.extract_pages_separate)
        self.add_button(side_layout, "合併文件...", self.open_merge_files_dialog)

        side_layout.addSpacing(12)
        side_layout.addWidget(QLabel("加密 PDF 密碼"))
        side_layout.addWidget(self.password_input)
        side_layout.addStretch(1)
        guide = QLabel("提示：每個 PDF 會開成獨立 Tab；縮圖可直接拖到目標位置插入重排。")
        guide.setWordWrap(True)
        guide.setObjectName("muted")
        side_layout.addWidget(guide)
        layout.addWidget(wrap_side_panel(side, 270))
        return tab

    def build_tools_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        toolbar = QWidget()
        controls = FlowLayout(toolbar, margin=0, hspacing=6, vspacing=6)
        self.add_button(controls, "加入 PDF", self.add_tool_pdf_files)
        self.add_button(controls, "加入圖片", self.add_tool_image_files)
        self.add_button(controls, "移除選取", self.remove_tool_files, "danger")
        self.add_button(controls, "上移", lambda: self.move_tool_file(-1))
        self.add_button(controls, "下移", lambda: self.move_tool_file(1))
        self.add_button(controls, "清空", self.clear_tool_files, "danger")
        layout.addWidget(toolbar)

        body = QHBoxLayout()
        body.setSpacing(14)

        self.tool_file_list = ToolFileList()
        self.tool_file_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.tool_file_list.filesDropped.connect(self.drop_tool_files)
        body.addWidget(self.tool_file_list, 1)

        form = QFrame()
        form.setObjectName("panel")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setSpacing(8)

        form_layout.addWidget(QLabel("工具"))
        self.tool_operation = QComboBox()
        for slug, title in TOOL_OPERATIONS:
            self.tool_operation.addItem(title, slug)
        form_layout.addWidget(self.tool_operation)

        form_layout.addWidget(QLabel("頁碼 / 範圍"))
        self.tool_pages_input = QLineEdit()
        self.tool_pages_input.setPlaceholderText("例如 1,3,5-8；旋轉留空代表全部")
        form_layout.addWidget(self.tool_pages_input)

        form_layout.addWidget(QLabel("原 PDF 密碼（如適用）"))
        self.tool_password_input = QLineEdit()
        self.tool_password_input.setEchoMode(QLineEdit.Password)
        form_layout.addWidget(self.tool_password_input)

        form_layout.addWidget(QLabel("新密碼（加密用）"))
        self.tool_new_password_input = QLineEdit()
        self.tool_new_password_input.setEchoMode(QLineEdit.Password)
        form_layout.addWidget(self.tool_new_password_input)

        form_layout.addWidget(QLabel("旋轉角度"))
        self.tool_angle_input = QComboBox()
        self.tool_angle_input.addItems(["90", "180", "270"])
        form_layout.addWidget(self.tool_angle_input)

        form_layout.addWidget(QLabel("圖片格式（PDF 轉圖片）"))
        self.tool_image_format_combo = QComboBox()
        self.tool_image_format_combo.addItem("PNG", "png")
        self.tool_image_format_combo.addItem("JPG", "jpg")
        self.tool_image_format_combo.addItem("WEBP", "webp")
        form_layout.addWidget(self.tool_image_format_combo)

        form_layout.addWidget(QLabel("圖片解析度 DPI"))
        self.tool_image_dpi_combo = QComboBox()
        for dpi in ("150", "200", "300"):
            self.tool_image_dpi_combo.addItem(dpi)
        self.tool_image_dpi_combo.setCurrentText("200")
        form_layout.addWidget(self.tool_image_dpi_combo)

        self.tool_images_zip_checkbox = QCheckBox("PDF 轉圖片時打包成 ZIP")
        form_layout.addWidget(self.tool_images_zip_checkbox)

        form_layout.addWidget(QLabel("OCR 語言"))
        self.tool_ocr_language_combo = QComboBox()
        for code, label in OCR_LANGUAGE_OPTIONS.items():
            self.tool_ocr_language_combo.addItem(label, code)
        self.tool_ocr_language_combo.setCurrentIndex(self.tool_ocr_language_combo.findData("auto"))
        form_layout.addWidget(self.tool_ocr_language_combo)

        form_layout.addWidget(QLabel("文字 / 模板"))
        self.tool_batch_text_input = QLineEdit("CONFIDENTIAL")
        self.tool_batch_text_input.setPlaceholderText("浮水印文字，或頁碼模板 {page} / {total}")
        form_layout.addWidget(self.tool_batch_text_input)
        template_hint = QLabel("頁碼模板可用 {page} / {total}；浮水印請輸入要蓋上的文字")
        template_hint.setObjectName("muted")
        template_hint.setWordWrap(True)
        form_layout.addWidget(template_hint)

        form_layout.addWidget(QLabel("浮水印位置"))
        self.tool_watermark_position_combo = QComboBox()
        for value, label in WATERMARK_POSITIONS.items():
            self.tool_watermark_position_combo.addItem(label, value)
        self.tool_watermark_position_combo.setCurrentIndex(self.tool_watermark_position_combo.findData("center"))
        form_layout.addWidget(self.tool_watermark_position_combo)
        wm_xy_row = QHBoxLayout()
        self.tool_watermark_x_input = QLineEdit("50")
        self.tool_watermark_x_input.setPlaceholderText("左 %")
        self.tool_watermark_x_input.setValidator(QIntValidator(0, 100, self))
        wm_xy_row.addWidget(QLabel("左 %"))
        wm_xy_row.addWidget(self.tool_watermark_x_input, 1)
        self.tool_watermark_y_input = QLineEdit("50")
        self.tool_watermark_y_input.setPlaceholderText("上 %")
        self.tool_watermark_y_input.setValidator(QIntValidator(0, 100, self))
        wm_xy_row.addWidget(QLabel("上 %"))
        wm_xy_row.addWidget(self.tool_watermark_y_input, 1)
        form_layout.addLayout(wm_xy_row)
        wm_style_row = QHBoxLayout()
        self.tool_watermark_rotation_combo = QComboBox()
        for angle, label in WATERMARK_ROTATIONS:
            self.tool_watermark_rotation_combo.addItem(label, angle)
        wm_style_row.addWidget(self.tool_watermark_rotation_combo, 1)
        self.tool_watermark_size_combo = QComboBox()
        configure_font_size_combo(self.tool_watermark_size_combo, "48", lambda: None)
        wm_style_row.addWidget(self.tool_watermark_size_combo)
        form_layout.addLayout(wm_style_row)
        wm_look_row = QHBoxLayout()
        self.tool_watermark_opacity_combo = QComboBox()
        for percent, alpha in (("15%", 0.15), ("25%", 0.25), ("35%", 0.35), ("50%", 0.5), ("70%", 0.7), ("100%", 1.0)):
            self.tool_watermark_opacity_combo.addItem(percent, alpha)
        self.tool_watermark_opacity_combo.setCurrentIndex(self.tool_watermark_opacity_combo.findData(0.25))
        wm_look_row.addWidget(QLabel("透明度"))
        wm_look_row.addWidget(self.tool_watermark_opacity_combo, 1)
        self.tool_watermark_color_combo = QComboBox()
        for key, (_rgb, label) in WATERMARK_COLORS.items():
            self.tool_watermark_color_combo.addItem(label, key)
        self.tool_watermark_color_combo.setCurrentIndex(self.tool_watermark_color_combo.findData("gray"))
        wm_look_row.addWidget(QLabel("顏色"))
        wm_look_row.addWidget(self.tool_watermark_color_combo, 1)
        form_layout.addLayout(wm_look_row)
        watermark_hint = QLabel("浮水印類似 Word：可自訂文字、九宮格／百分比位置、斜向或水平、大小與淡化程度。頁碼欄可指定套用頁面，留空為全部。")
        watermark_hint.setObjectName("muted")
        watermark_hint.setWordWrap(True)
        form_layout.addWidget(watermark_hint)

        form_layout.addWidget(QLabel("空白頁靈敏度"))
        self.tool_blank_threshold_combo = QComboBox()
        for value in ("10", "15", "25", "50", "100", "200", "500"):
            self.tool_blank_threshold_combo.addItem(value)
        self.tool_blank_threshold_combo.setCurrentText("25")
        form_layout.addWidget(self.tool_blank_threshold_combo)

        form_layout.addWidget(QLabel("進階拆分方式"))
        split_row = QHBoxLayout()
        self.tool_split_mode_combo = QComboBox()
        self.tool_split_mode_combo.addItem("每 N 頁一檔", "every")
        self.tool_split_mode_combo.addItem("依範圍各存一檔", "ranges")
        split_row.addWidget(self.tool_split_mode_combo, 1)
        self.tool_split_value_input = QLineEdit("1")
        self.tool_split_value_input.setPlaceholderText("每檔頁數，或範圍如 1-3,4-6")
        split_row.addWidget(self.tool_split_value_input, 1)
        form_layout.addLayout(split_row)

        form_layout.addWidget(QLabel("Bates 編號（前綴 / 起始 / 位數）"))
        bates_row = QHBoxLayout()
        self.tool_bates_prefix_input = QLineEdit()
        self.tool_bates_prefix_input.setPlaceholderText("前綴，如 ABC-")
        bates_row.addWidget(self.tool_bates_prefix_input, 2)
        self.tool_bates_start_input = QLineEdit("1")
        self.tool_bates_start_input.setFixedWidth(56)
        bates_row.addWidget(self.tool_bates_start_input)
        self.tool_bates_digits_combo = QComboBox()
        for digits in ("4", "5", "6", "7", "8"):
            self.tool_bates_digits_combo.addItem(digits)
        self.tool_bates_digits_combo.setCurrentText("6")
        bates_row.addWidget(self.tool_bates_digits_combo)
        form_layout.addLayout(bates_row)
        self.tool_bates_position_combo = QComboBox()
        for value, label in BATES_POSITIONS.items():
            self.tool_bates_position_combo.addItem(label, value)
        form_layout.addWidget(self.tool_bates_position_combo)

        form_layout.addWidget(QLabel("權限控制（加密 + 權限控制）"))
        self.tool_perm_print_checkbox = QCheckBox("允許列印")
        self.tool_perm_print_checkbox.setChecked(True)
        form_layout.addWidget(self.tool_perm_print_checkbox)
        self.tool_perm_copy_checkbox = QCheckBox("允許複製文字 / 圖形")
        self.tool_perm_copy_checkbox.setChecked(True)
        form_layout.addWidget(self.tool_perm_copy_checkbox)
        self.tool_perm_modify_checkbox = QCheckBox("允許修改 / 填表")
        self.tool_perm_modify_checkbox.setChecked(True)
        form_layout.addWidget(self.tool_perm_modify_checkbox)

        run_button = self.add_button(form_layout, "處理並另存", self.run_tool_operation, "primary")
        run_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.tool_open_pdf_tab_checkbox = QCheckBox("PDF 輸出後開成新 Tab")
        self.tool_open_pdf_tab_checkbox.setChecked(True)
        self.tool_open_pdf_tab_checkbox.toggled.connect(self.save_output_preferences)
        form_layout.addWidget(self.tool_open_pdf_tab_checkbox)
        self.tool_open_output_folder_checkbox = QCheckBox("ZIP / TXT 輸出後開啟資料夾")
        self.tool_open_output_folder_checkbox.setChecked(True)
        self.tool_open_output_folder_checkbox.toggled.connect(self.save_output_preferences)
        form_layout.addWidget(self.tool_open_output_folder_checkbox)

        self.tool_batch_checkbox = QCheckBox("批次處理清單中每個 PDF（輸出到資料夾）")
        self.tool_batch_checkbox.setChecked(False)
        form_layout.addWidget(self.tool_batch_checkbox)

        self.add_button(form_layout, "開啟處理紀錄", self.open_audit_log)

        hint = QLabel(
            "提示：可把 PDF / 圖片直接拖入左側清單。合併 / 圖片轉 PDF 本身支援多檔；"
            "其餘工具預設用第一個 PDF。勾選「批次處理」後，旋轉／壓縮／浮水印／頁碼／加密等會對清單每個 PDF 各輸出一份到資料夾。"
            "Word / Excel / PowerPoint 請到「Office 轉 PDF」分頁；PDF 轉 Word / Excel 請到「PDF 轉 Office」分頁。"
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form_layout.addWidget(hint)
        form_layout.addStretch(1)
        body.addWidget(wrap_side_panel(form, 310))
        layout.addLayout(body, 1)
        return tab

    def build_office_convert_tab(self) -> QWidget:
        tab = PdfDropPanel()
        tab.filesDropped.connect(self.drop_office_files)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        toolbar = QWidget()
        controls = FlowLayout(toolbar, margin=0, hspacing=6, vspacing=6)
        self.add_button(controls, "加入 Word / Excel / PPT", self.add_office_files)
        self.add_button(controls, "移除選取", self.remove_office_files, "danger")
        self.add_button(controls, "上移", lambda: self.move_office_file(-1))
        self.add_button(controls, "下移", lambda: self.move_office_file(1))
        self.add_button(controls, "清空", self.clear_office_files, "danger")
        layout.addWidget(toolbar)

        body = QHBoxLayout()
        body.setSpacing(14)

        self.office_file_list = ToolFileList()
        self.office_file_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.office_file_list.filesDropped.connect(self.drop_office_files)
        body.addWidget(self.office_file_list, 1)

        form = QFrame()
        form.setObjectName("panel")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setSpacing(8)

        form_layout.addWidget(QLabel("輸出方式"))
        self.office_output_mode = QComboBox()
        self.office_output_mode.addItem("合併成一份 PDF", "merge")
        self.office_output_mode.addItem("每個檔各存一份", "separate")
        form_layout.addWidget(self.office_output_mode)

        convert_button = self.add_button(form_layout, "轉換並另存 PDF", self.run_office_convert, "primary")
        convert_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.office_progress_label = QLabel("尚未開始轉換")
        self.office_progress_label.setObjectName("muted")
        self.office_progress_label.setWordWrap(True)
        form_layout.addWidget(self.office_progress_label)
        self.office_progress = QProgressBar()
        self.office_progress.setRange(0, 100)
        self.office_progress.setValue(0)
        configure_count_progress_bar(self.office_progress)
        form_layout.addWidget(self.office_progress)

        self.office_open_pdf_checkbox = QCheckBox("完成後開啟 PDF")
        self.office_open_pdf_checkbox.setChecked(True)
        self.office_open_pdf_checkbox.toggled.connect(self.save_output_preferences)
        form_layout.addWidget(self.office_open_pdf_checkbox)
        self.office_open_pdf_tab_checkbox = QCheckBox("PDF 輸出後開成新 Tab")
        self.office_open_pdf_tab_checkbox.setChecked(True)
        self.office_open_pdf_tab_checkbox.toggled.connect(self.save_output_preferences)
        form_layout.addWidget(self.office_open_pdf_tab_checkbox)
        self.office_open_output_folder_checkbox = QCheckBox("各存一份時開啟輸出資料夾")
        self.office_open_output_folder_checkbox.setChecked(True)
        self.office_open_output_folder_checkbox.toggled.connect(self.save_output_preferences)
        form_layout.addWidget(self.office_open_output_folder_checkbox)

        self.add_button(form_layout, "開啟處理紀錄", self.open_audit_log)

        hint = QLabel(
            "提示：把 Word（.doc / .docx）、Excel（.xls / .xlsx）或 PowerPoint（.ppt / .pptx）"
            "拖入左側清單。另存檔名會沿用原檔名。PowerPoint 在背景轉換，並依投影片畫面以 300 DPI 匯出，"
            "以免「另存 PDF」把立體字變成黑塊；PDF 內文字無法選取。"
            "轉換需已安裝 Microsoft Office 或 LibreOffice。"
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form_layout.addWidget(hint)
        form_layout.addStretch(1)
        body.addWidget(wrap_side_panel(form, 310))
        layout.addLayout(body, 1)
        return tab

    def build_pdf_to_office_tab(self) -> QWidget:
        tab = PdfDropPanel()
        tab.filesDropped.connect(self.drop_pdf_office_files)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        toolbar = QWidget()
        controls = FlowLayout(toolbar, margin=0, hspacing=6, vspacing=6)
        self.add_button(controls, "加入 PDF", self.add_pdf_office_files)
        self.add_button(controls, "移除選取", self.remove_pdf_office_files, "danger")
        self.add_button(controls, "上移", lambda: self.move_pdf_office_file(-1))
        self.add_button(controls, "下移", lambda: self.move_pdf_office_file(1))
        self.add_button(controls, "清空", self.clear_pdf_office_files, "danger")
        layout.addWidget(toolbar)

        body = QHBoxLayout()
        body.setSpacing(14)

        self.pdf_office_file_list = ToolFileList()
        self.pdf_office_file_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.pdf_office_file_list.filesDropped.connect(self.drop_pdf_office_files)
        body.addWidget(self.pdf_office_file_list, 1)

        form = QFrame()
        form.setObjectName("panel")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setSpacing(8)

        form_layout.addWidget(QLabel("輸出格式"))
        self.pdf_office_format_combo = QComboBox()
        self.pdf_office_format_combo.addItem("轉 Word（.docx）", "word")
        self.pdf_office_format_combo.addItem("轉 Excel（.xlsx）", "excel")
        form_layout.addWidget(self.pdf_office_format_combo)

        form_layout.addWidget(QLabel("頁碼 / 範圍"))
        self.pdf_office_pages_input = QLineEdit()
        self.pdf_office_pages_input.setPlaceholderText("例如 1,3,5-8；留空代表全部")
        form_layout.addWidget(self.pdf_office_pages_input)

        form_layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.pdf_office_password_input = QLineEdit()
        self.pdf_office_password_input.setEchoMode(QLineEdit.Password)
        form_layout.addWidget(self.pdf_office_password_input)

        form_layout.addWidget(QLabel("OCR 語言（掃描件）"))
        self.pdf_office_ocr_combo = QComboBox()
        for code, label in OCR_LANGUAGE_OPTIONS.items():
            self.pdf_office_ocr_combo.addItem(label, code)
        self.pdf_office_ocr_combo.setCurrentIndex(self.pdf_office_ocr_combo.findData("auto"))
        form_layout.addWidget(self.pdf_office_ocr_combo)

        form_layout.addWidget(QLabel("掃描件解析度 DPI"))
        self.pdf_office_dpi_combo = QComboBox()
        for dpi in ("150", "200", "300"):
            self.pdf_office_dpi_combo.addItem(dpi)
        self.pdf_office_dpi_combo.setCurrentText("300")
        form_layout.addWidget(self.pdf_office_dpi_combo)

        convert_button = self.add_button(form_layout, "轉換並另存", self.run_pdf_to_office, "primary")
        convert_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.pdf_office_progress_label = QLabel("尚未開始轉換")
        self.pdf_office_progress_label.setObjectName("muted")
        self.pdf_office_progress_label.setWordWrap(True)
        form_layout.addWidget(self.pdf_office_progress_label)
        self.pdf_office_progress = QProgressBar()
        self.pdf_office_progress.setRange(0, 100)
        self.pdf_office_progress.setValue(0)
        configure_count_progress_bar(self.pdf_office_progress)
        form_layout.addWidget(self.pdf_office_progress)

        self.pdf_office_open_file_checkbox = QCheckBox("完成後開啟檔案")
        self.pdf_office_open_file_checkbox.setChecked(True)
        self.pdf_office_open_file_checkbox.toggled.connect(self.save_output_preferences)
        form_layout.addWidget(self.pdf_office_open_file_checkbox)
        self.pdf_office_open_output_folder_checkbox = QCheckBox("多檔輸出時開啟資料夾")
        self.pdf_office_open_output_folder_checkbox.setChecked(True)
        self.pdf_office_open_output_folder_checkbox.toggled.connect(self.save_output_preferences)
        form_layout.addWidget(self.pdf_office_open_output_folder_checkbox)

        self.add_button(form_layout, "開啟處理紀錄", self.open_audit_log)

        hint = QLabel(
            "提示：把 PDF 拖入左側清單。有文字層的 PDF 轉 Word 會依座標重建雙欄、表格與標題，"
            "不是只抽出純文字（Microsoft Word 開啟部分中文字型會整段丟字，程式會改自行組版）。"
            "轉 Excel 會先找有框線的表，沒有框線則依欄位對齊抽出；掃描件用 OCR 座標重建欄位。"
            "左右中英對照會排成左右兩欄（英文／中文）。"
            "掃描件會逐頁 OCR，進度會顯示頁碼；雙欄頁可能稍慢，請勿強制結束。"
            "轉換結果是可再編輯草稿，版面不會與 Adobe 完全一致。"
            "Word / Excel / PowerPoint 轉 PDF 請到「Office 轉 PDF」分頁。"
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form_layout.addWidget(hint)
        form_layout.addStretch(1)
        body.addWidget(wrap_side_panel(form, 310))
        layout.addLayout(body, 1)
        return tab

    def build_annotation_tab(self) -> QWidget:
        tab = PdfDropPanel()
        self._annotation_tab = tab
        tab.filesDropped.connect(self.drop_annotation_pdf)
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(10)
        top = QHBoxLayout()
        self.add_button(top, "載入 PDF", self.load_annotation_pdf)
        top.addWidget(QLabel("頁碼"))
        self.annotation_page_input = QLineEdit("1")
        self.annotation_page_input.setFixedWidth(56)
        self.annotation_page_validator = QIntValidator(1, 1, self)
        self.annotation_page_input.setValidator(self.annotation_page_validator)
        self.annotation_page_input.editingFinished.connect(self.on_advanced_page_input_edited)
        top.addWidget(self.annotation_page_input)
        self.add_button(top, "上一頁", lambda: self.change_annotation_page(-1))
        self.add_button(top, "下一頁", lambda: self.change_annotation_page(1))
        self.add_button(top, "縮小", lambda: self.change_advanced_preview_zoom(-ADVANCED_PREVIEW_ZOOM_STEP))
        self.advanced_zoom_label = QLabel("115%")
        self.advanced_zoom_label.setFixedWidth(48)
        self.advanced_zoom_label.setAlignment(Qt.AlignCenter)
        top.addWidget(self.advanced_zoom_label)
        self.add_button(top, "放大", lambda: self.change_advanced_preview_zoom(ADVANCED_PREVIEW_ZOOM_STEP))
        self.add_button(top, "更新預覽", self.render_annotation_preview)
        top.addStretch(1)
        left.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.annotation_preview_label = AnnotationPreviewLabel()
        self.annotation_preview_label.positionClicked.connect(self.set_annotation_position_from_click)
        self.annotation_preview_label.rectDrawn.connect(self.set_annotation_from_drag)
        self.annotation_preview_label.boxResized.connect(self.resize_annotation_box_from_handle)
        self.annotation_preview_label.boxMoved.connect(self.move_annotation_box)
        self.annotation_preview_label.pointerMoved.connect(self.move_annotation_pointer)
        self.annotation_preview_label.elbowMoved.connect(self.move_annotation_elbow)
        self.annotation_preview_label.boxInteractionFinished.connect(self.finish_annotation_box_interaction)
        self.annotation_preview_label.pointerInteractionFinished.connect(self.finish_annotation_pointer_interaction)
        self.annotation_preview_label.elbowInteractionFinished.connect(self.finish_annotation_elbow_interaction)
        self.annotation_preview_label.copyRequested.connect(self.copy_annotation_box)
        self.annotation_preview_label.pasteRequested.connect(self.paste_annotation_box)
        self.annotation_preview_label.undoRequested.connect(self.undo_annotation_action)
        self.annotation_preview_label.deleteRequested.connect(self.delete_current_annotation_box)
        scroll.setWidget(self.annotation_preview_label)
        left.addWidget(scroll, 1)
        layout.addLayout(left, 1)

        side = QFrame()
        side.setObjectName("panel")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

        side_layout.addWidget(QLabel("文字外框"))
        self.annotation_shape_list = QListWidget()
        self.annotation_shape_list.setViewMode(QListWidget.IconMode)
        self.annotation_shape_list.setMovement(QListWidget.Static)
        self.annotation_shape_list.setResizeMode(QListWidget.Adjust)
        self.annotation_shape_list.setIconSize(QSize(88, 56))
        self.annotation_shape_list.setSpacing(6)
        self.annotation_shape_list.setFixedHeight(210)
        self.annotation_shape_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.annotation_shape_list.setStyleSheet(
            "QListWidget { background: #f7fafc; border: 1px solid #dce3ec; }"
            "QListWidget::item { padding: 4px; }"
            "QListWidget::item:selected { background: #d9eef0; border: 1px solid #128576; }"
        )
        for value, label in self.ANNOTATION_SHAPE_OPTIONS:
            item = QListWidgetItem(self._annotation_shape_icon(value), label)
            item.setData(Qt.UserRole, value)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            self.annotation_shape_list.addItem(item)
        self.annotation_shape_list.setCurrentRow(0)
        self.annotation_shape_list.currentItemChanged.connect(lambda *_args: self.on_annotation_shape_changed())
        side_layout.addWidget(self.annotation_shape_list)

        side_layout.addWidget(QLabel("標註文字"))
        self.annotation_text_input = QTextEdit()
        self.annotation_text_input.setPlaceholderText("輸入要覆蓋或加上的文字")
        self.annotation_text_input.setFixedHeight(90)
        side_layout.addWidget(self.annotation_text_input)

        self.annotation_cover_checkbox = QCheckBox("先用白底覆蓋原文字")
        self.annotation_cover_checkbox.setChecked(True)
        side_layout.addWidget(self.annotation_cover_checkbox)

        side_layout.addWidget(QLabel("字體"))
        self.annotation_font_combo = QComboBox()
        self.annotation_font_combo.addItem("中文（微軟雅黑／正黑體）", "cjk")
        self.annotation_font_combo.addItem("Helvetica", "helvetica")
        self.annotation_font_combo.addItem("Times New Roman", "times")
        self.annotation_font_combo.addItem("Courier", "courier")
        self.annotation_font_combo.setCurrentIndex(0)
        side_layout.addWidget(self.annotation_font_combo)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("大小"))
        self.annotation_font_size_combo = QComboBox()
        configure_font_size_combo(self.annotation_font_size_combo, "12", self.fit_annotation_box_to_text)
        style_row.addWidget(self.annotation_font_size_combo, 1)
        self.annotation_bold_checkbox = QCheckBox("粗體")
        style_row.addWidget(self.annotation_bold_checkbox)
        side_layout.addLayout(style_row)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("顏色"))
        self.annotation_color_combo = QComboBox()
        self.annotation_color_combo.addItem("黑色", "black")
        self.annotation_color_combo.addItem("紅色", "red")
        self.annotation_color_combo.addItem("藍色", "blue")
        self.annotation_color_combo.addItem("灰色", "gray")
        self.annotation_color_combo.addItem("自訂...", "custom")
        color_row.addWidget(self.annotation_color_combo, 1)
        self.annotation_color_button = QPushButton("選色")
        self.annotation_color_button.setFixedWidth(56)
        color_row.addWidget(self.annotation_color_button)
        side_layout.addLayout(color_row)

        fill_row = QHBoxLayout()
        fill_row.addWidget(QLabel("底色"))
        self.annotation_fill_combo = QComboBox()
        self.annotation_fill_combo.addItem("白色", "white")
        self.annotation_fill_combo.addItem("無底色", "none")
        self.annotation_fill_combo.addItem("淡黃", "yellow")
        self.annotation_fill_combo.addItem("淺藍", "blue")
        self.annotation_fill_combo.addItem("淺綠", "green")
        self.annotation_fill_combo.addItem("跟隨外框", "follow")
        self.annotation_fill_combo.addItem("自訂...", "custom")
        fill_row.addWidget(self.annotation_fill_combo, 1)
        self.annotation_fill_button = QPushButton("選色")
        self.annotation_fill_button.setFixedWidth(56)
        fill_row.addWidget(self.annotation_fill_button)
        side_layout.addLayout(fill_row)

        self.annotation_xy_label = QLabel("X / Y 位置")
        side_layout.addWidget(self.annotation_xy_label)
        xy = QHBoxLayout()
        self.annotation_x_input = QLineEdit("72")
        self.annotation_y_input = QLineEdit("720")
        xy.addWidget(self.annotation_x_input)
        xy.addWidget(self.annotation_y_input)
        side_layout.addLayout(xy)

        side_layout.addWidget(QLabel("覆蓋框 / 文字框寬高"))
        wh = QHBoxLayout()
        self.annotation_width_input = QLineEdit("220")
        self.annotation_height_input = QLineEdit("32")
        wh.addWidget(self.annotation_width_input)
        wh.addWidget(self.annotation_height_input)
        side_layout.addLayout(wh)

        self.add_button(side_layout, "加入此頁標註", self.queue_current_annotation)
        side_layout.addWidget(QLabel("已加入的標註（可跨頁，最後一次另存）"))
        self.annotation_item_list = QListWidget()
        self.annotation_item_list.setMinimumHeight(90)
        self.annotation_item_list.setMaximumHeight(140)
        side_layout.addWidget(self.annotation_item_list)
        annotation_list_buttons = QHBoxLayout()
        self.add_button(annotation_list_buttons, "復原", self.undo_annotation_action)
        self.add_button(annotation_list_buttons, "刪除選取", self.delete_current_annotation_box, "danger")
        self.add_button(annotation_list_buttons, "清空", self.clear_annotation_items)
        side_layout.addLayout(annotation_list_buttons)

        side_layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.annotation_password_input = QLineEdit()
        self.annotation_password_input.setEchoMode(QLineEdit.Password)
        side_layout.addWidget(self.annotation_password_input)

        save_button = self.add_button(side_layout, "套用並另存 PDF", self.save_annotation_pdf, "primary")
        save_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        changed_button = self.add_button(side_layout, "另存有修改的頁", self.save_changed_pages_pdf)
        changed_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.annotation_guide = QLabel("提示：左邊縮圖可換頁；點預覽放置文字框或附註。點選方塊後 Delete 刪除，Ctrl+C 複製、Ctrl+V 貼到其他位置，Ctrl+Z 或「復原」可還原。加入後換頁會把上一頁標註留在清單。全部改完再另存，或用「另存有修改的頁」只抽出有註解的頁。")
        self.annotation_guide.setObjectName("muted")
        self.annotation_guide.setWordWrap(True)
        side_layout.addWidget(self.annotation_guide)
        side_layout.addStretch(1)
        layout.addWidget(wrap_side_panel(side, 320))
        self.connect_annotation_preview_updates()
        return tab

    def connect_annotation_preview_updates(self) -> None:
        self.annotation_text_input.textChanged.connect(self.fit_annotation_box_to_text)
        self.annotation_cover_checkbox.toggled.connect(self.update_annotation_preview_display)
        self.annotation_font_combo.currentIndexChanged.connect(self.fit_annotation_box_to_text)
        self.annotation_bold_checkbox.toggled.connect(self.fit_annotation_box_to_text)
        self.annotation_color_combo.currentIndexChanged.connect(self.on_annotation_color_preset_changed)
        self.annotation_color_button.clicked.connect(self.choose_annotation_color)
        self.annotation_fill_combo.currentIndexChanged.connect(self.on_annotation_fill_preset_changed)
        self.annotation_fill_button.clicked.connect(self.choose_annotation_fill_color)
        self.annotation_x_input.textChanged.connect(self.update_annotation_preview_display)
        self.annotation_y_input.textChanged.connect(self.update_annotation_preview_display)
        self.annotation_width_input.editingFinished.connect(self.fit_annotation_box_to_text)
        self.annotation_width_input.textChanged.connect(self.update_annotation_preview_display)
        self.annotation_height_input.textChanged.connect(self.update_annotation_preview_display)

    def on_annotation_color_preset_changed(self) -> None:
        preset = self.annotation_color_combo.currentData()
        if preset == "custom":
            self.choose_annotation_color()
            return
        if preset in ANNOTATION_COLOR_PRESETS:
            self.annotation_color_rgb = ANNOTATION_COLOR_PRESETS[preset]
        self.update_annotation_preview_display()

    def choose_annotation_color(self) -> None:
        current = QColor.fromRgbF(*self.annotation_color_rgb)
        chosen = QColorDialog.getColor(current, self, "選擇文字顏色")
        if not chosen.isValid():
            return
        self.annotation_color_rgb = (chosen.redF(), chosen.greenF(), chosen.blueF())
        custom_index = self.annotation_color_combo.findData("custom")
        if custom_index >= 0:
            self.annotation_color_combo.setCurrentIndex(custom_index)
        self.update_annotation_preview_display()

    def on_annotation_fill_preset_changed(self) -> None:
        preset = self.annotation_fill_combo.currentData()
        if preset == "custom":
            self.choose_annotation_fill_color()
            return
        if preset == "none":
            self.annotation_fill_none = True
            self.annotation_fill_rgb = (1.0, 1.0, 1.0)
        elif preset == "follow":
            self.annotation_fill_none = False
            self.annotation_fill_rgb = None
        elif preset in ANNOTATION_FILL_PRESETS:
            self.annotation_fill_none = False
            self.annotation_fill_rgb = ANNOTATION_FILL_PRESETS[preset]
        self.update_annotation_preview_display()

    def choose_annotation_fill_color(self) -> None:
        current = QColor.fromRgbF(*(self.annotation_fill_rgb or (1.0, 1.0, 1.0)))
        chosen = QColorDialog.getColor(current, self, "選擇底色")
        if not chosen.isValid():
            return
        self.annotation_fill_none = False
        self.annotation_fill_rgb = (chosen.redF(), chosen.greenF(), chosen.blueF())
        custom_index = self.annotation_fill_combo.findData("custom")
        if custom_index >= 0:
            self.annotation_fill_combo.setCurrentIndex(custom_index)
        self.update_annotation_preview_display()

    def annotation_style_values(self) -> dict:
        try:
            rect_width = float(self.annotation_width_input.text())
            rect_height = float(self.annotation_height_input.text())
        except ValueError:
            rect_width, rect_height = 220.0, 32.0
        try:
            pdf_x = float(self.annotation_x_input.text())
            pdf_y = float(self.annotation_y_input.text())
        except ValueError:
            pdf_x, pdf_y = 72.0, 720.0
        shape = self.annotation_shape()
        if shape in CALLOUT_KINDS:
            pointer_x, pointer_y = pdf_x, pdf_y
            if self.annotation_box_locked and self.annotation_box_pdf is not None:
                box_x, box_y = self.annotation_box_pdf
            elif shape == "comment":
                box_x, box_y = comment_box_from_pointer(pointer_x, pointer_y, rect_width, rect_height)
            else:
                box_x, box_y = callout_box_from_pointer(pointer_x, pointer_y, rect_width, rect_height)
        else:
            box_x, box_y = pdf_x, pdf_y
            pointer_x, pointer_y = box_x + rect_width / 2.0, box_y - 16.0
        return {
            "text": self.annotation_text_input.toPlainText(),
            "cover": self.annotation_cover_checkbox.isChecked(),
            "font_key": self.annotation_font_combo.currentData() or "helvetica",
            "font_size": combo_font_size(self.annotation_font_size_combo, 12),
            "bold": self.annotation_bold_checkbox.isChecked(),
            "color_rgb": self.annotation_color_rgb,
            "fill_rgb": None if self.annotation_fill_none else self.annotation_fill_rgb,
            "fill_none": self.annotation_fill_none,
            "pdf_x": box_x,
            "pdf_y": box_y,
            "rect_width": rect_width,
            "rect_height": rect_height,
            "shape": shape,
            "pointer_x": pointer_x,
            "pointer_y": pointer_y,
        }

    def measure_annotation_text_box(
        self,
        text: str,
        font_size: int,
        bold: bool,
        font_key: str,
        box_width: float,
    ) -> tuple[float, float]:
        width = max(float(box_width), 80.0)
        font = self.annotation_preview_font(font_size, bold, font_key, text or "字")
        inner = max(width - ANNOTATION_BOX_PAD_X * 2, 16.0)
        lines = wrap_annotation_text(text.strip() or " ", font, inner)
        line_height = annotation_font_line_height(font, font_size)
        height = max(len(lines) * line_height + ANNOTATION_BOX_PAD_Y * 2, font_size * 1.8, 28.0)
        return width, height

    def fit_annotation_box_to_text(self) -> None:
        if self._fitting_annotation_box:
            return
        text = self.annotation_text_input.toPlainText()
        if not text.strip():
            self.update_annotation_preview_display()
            return
        try:
            width = float(self.annotation_width_input.text())
        except ValueError:
            width = 220.0
        try:
            current_height = float(self.annotation_height_input.text())
        except ValueError:
            current_height = 32.0
        font_size = combo_font_size(self.annotation_font_size_combo, 12)
        needed_width, needed_height = self.measure_annotation_text_box(
            text,
            font_size,
            self.annotation_bold_checkbox.isChecked(),
            self.annotation_font_combo.currentData() or "helvetica",
            width,
        )
        if self._annotation_manual_size:
            new_height = max(current_height, needed_height)
            new_width = max(width, 80.0)
        else:
            new_height = needed_height
            new_width = needed_width
        self._fitting_annotation_box = True
        try:
            if abs(new_height - current_height) > 0.4:
                self.annotation_height_input.blockSignals(True)
                self.annotation_height_input.setText(f"{new_height:.1f}")
                self.annotation_height_input.blockSignals(False)
            if abs(new_width - width) > 0.4:
                self.annotation_width_input.blockSignals(True)
                self.annotation_width_input.setText(f"{new_width:.1f}")
                self.annotation_width_input.blockSignals(False)
        finally:
            self._fitting_annotation_box = False
        self.update_annotation_preview_display()

    def annotation_image_box_rect(self, style: dict) -> QRect:
        page_width, page_height = self.annotation_page_size
        if self.annotation_preview_image is None or page_width <= 0 or page_height <= 0:
            return QRect()
        image_width, image_height = self.annotation_preview_image.size
        left = style["pdf_x"] / page_width * image_width
        top = (page_height - (style["pdf_y"] + style["rect_height"])) / page_height * image_height
        width = style["rect_width"] / page_width * image_width
        height = style["rect_height"] / page_height * image_height
        return QRect(int(round(left)), int(round(top)), max(int(round(width)), 1), max(int(round(height)), 1))

    def _annotation_image_delta_to_pdf(self, start: QPoint, current: QPoint) -> tuple[float, float]:
        page_width, page_height = self.annotation_page_size
        image_width, image_height = self.annotation_preview_image.size
        dx = (current.x() - start.x()) / image_width * page_width
        dy = -((current.y() - start.y()) / image_height * page_height)
        return dx, dy

    def _set_annotation_box_values(self, pdf_x: float, pdf_y: float, width: float, height: float) -> None:
        width = max(width, 80.0)
        font_size = combo_font_size(self.annotation_font_size_combo, 12)
        min_height = max(font_size * 1.8, 28.0)
        height = max(height, min_height)
        self.annotation_x_input.blockSignals(True)
        self.annotation_y_input.blockSignals(True)
        self.annotation_width_input.blockSignals(True)
        self.annotation_height_input.blockSignals(True)
        if self.annotation_shape() in CALLOUT_KINDS:
            self.annotation_box_pdf = (pdf_x, pdf_y)
            self.annotation_box_locked = True
        else:
            self.annotation_x_input.setText(f"{pdf_x:.1f}")
            self.annotation_y_input.setText(f"{pdf_y:.1f}")
        self.annotation_width_input.setText(f"{width:.1f}")
        self.annotation_height_input.setText(f"{height:.1f}")
        self.annotation_x_input.blockSignals(False)
        self.annotation_y_input.blockSignals(False)
        self.annotation_width_input.blockSignals(False)
        self.annotation_height_input.blockSignals(False)
        self.fit_annotation_box_to_text()

    def resize_annotation_box_from_handle(self, handle: str, start: QPoint, current: QPoint) -> None:
        if self.annotation_preview_image is None:
            return
        if self._annotation_resize_snapshot is None:
            self._push_annotation_undo()
            style = self.annotation_style_values()
            self._annotation_resize_snapshot = (
                style["pdf_x"],
                style["pdf_y"],
                style["rect_width"],
                style["rect_height"],
            )
        pdf_x, pdf_y, width, height = self._annotation_resize_snapshot
        dx, dy = self._annotation_image_delta_to_pdf(start, current)
        if "e" in handle:
            width += dx
        if "w" in handle:
            pdf_x += dx
            width -= dx
        if "n" in handle:
            height += dy
        if "s" in handle:
            pdf_y += dy
            height -= dy
        self._annotation_manual_size = True
        self._annotation_placed = True
        self._set_annotation_box_values(pdf_x, pdf_y, width, height)

    def move_annotation_box(self, start: QPoint, current: QPoint) -> None:
        if self.annotation_preview_image is None:
            return
        if self._annotation_resize_snapshot is None:
            self._push_annotation_undo()
            style = self.annotation_style_values()
            self._annotation_resize_snapshot = (
                style["pdf_x"],
                style["pdf_y"],
                style["rect_width"],
                style["rect_height"],
            )
        pdf_x, pdf_y, width, height = self._annotation_resize_snapshot
        dx, dy = self._annotation_image_delta_to_pdf(start, current)
        self._annotation_placed = True
        self._set_annotation_box_values(pdf_x + dx, pdf_y + dy, width, height)

    def finish_annotation_box_interaction(self) -> None:
        self._annotation_resize_snapshot = None
        self.set_status("已調整文字框。可繼續改文字，或拉邊框縮放。")

    def annotation_shape(self) -> str:
        item = self.annotation_shape_list.currentItem()
        if item is None:
            return "box"
        return str(item.data(Qt.UserRole) or "box")

    def set_annotation_shape(self, shape: str) -> None:
        for row in range(self.annotation_shape_list.count()):
            item = self.annotation_shape_list.item(row)
            if item is not None and item.data(Qt.UserRole) == shape:
                self.annotation_shape_list.setCurrentRow(row)
                return

    def on_annotation_shape_changed(self) -> None:
        is_plain = self.annotation_shape() == "box"
        self.annotation_cover_checkbox.setEnabled(is_plain)
        if self.annotation_shape() == "comment":
            self.annotation_cover_checkbox.setChecked(False)
            self.annotation_xy_label.setText("插入點（箭咀尖端）")
            self.annotation_guide.setText(
                "提示：選附註框後點預覽，方框會立刻出現。再輸入文字。"
                "拖下方橫線可左右伸長箭咀，拖藍色十字準星改插入點，拖框身可移動文字框。"
                "Ctrl+C／V 可複製貼上到其他位置，Ctrl+Z 還原。"
            )
        elif self.annotation_shape() in CALLOUT_KINDS:
            self.annotation_cover_checkbox.setChecked(False)
            self.annotation_xy_label.setText("插入點（箭咀尖端）")
            self.annotation_guide.setText(
                "提示：點預覽放置新標註。加入或換頁後，這一頁會是空白畫布，請再點一次放置。"
                "拖藍色十字準星（或點頁上其他文字）可單獨移動箭咀插入點，文字框不會跟著走。"
                "拖框身可改對話框位置，拖小方塊可拉大／拉小。Ctrl+C／V 複製貼上，Ctrl+Z 還原。"
            )
        elif is_plain:
            self.annotation_xy_label.setText("X / Y 位置")
            self.annotation_guide.setText(
                "提示：先選文字外框，再輸入文字；點左側預覽放置。選對話框／雲朵／標註框時，外框會包住這段文字。"
            )
        else:
            self.annotation_cover_checkbox.setChecked(False)
            self.annotation_xy_label.setText("X / Y 位置")
            self.annotation_guide.setText(
                "提示：此外框會包住上方輸入的文字。點預覽放置文字框左下角。"
            )
        if self.annotation_shape() not in CALLOUT_KINDS:
            self.annotation_box_locked = False
            self.annotation_box_pdf = None
        if (
            self.annotation_shape() == "comment"
            and self.annotation_preview_image is not None
            and not self._annotation_placed
            and not getattr(self, "_restoring_annotation", False)
        ):
            image_width, image_height = self.annotation_preview_image.size
            self.set_annotation_position_from_click(QPoint(max(image_width // 3, 48), max(image_height // 2, 48)))
            return
        self.fit_annotation_box_to_text()

    def _annotation_shape_icon(self, kind: str) -> QIcon:
        pixmap = QPixmap(88, 56)
        pixmap.fill(QColor("#ffffff"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#2b6a9e"), 2))
        painter.setBrush(QColor("#e8f3fb"))
        if kind == "comment":
            painter.drawRect(20, 6, 50, 22)
            painter.drawLine(45, 28, 45, 36)
            painter.drawLine(45, 36, 22, 36)
            painter.drawLine(22, 36, 22, 46)
            painter.setBrush(QColor("#2b6a9e"))
            painter.drawPolygon(QPolygon([QPoint(22, 50), QPoint(17, 42), QPoint(27, 42)]))
            painter.setPen(QColor("#1f3b54"))
            painter.drawText(QRect(20, 6, 50, 22), Qt.AlignCenter, "Aa")
        elif kind == "callout":
            painter.drawRect(18, 8, 52, 24)
            painter.drawLine(44, 32, 44, 46)
            painter.setBrush(QColor("#2b6a9e"))
            painter.drawPolygon(QPolygon([QPoint(44, 48), QPoint(39, 40), QPoint(49, 40)]))
            painter.setPen(QColor("#1f3b54"))
            painter.drawText(QRect(18, 8, 52, 24), Qt.AlignCenter, "Aa")
        elif kind == "speech":
            painter.drawRoundedRect(14, 6, 60, 26, 6, 6)
            painter.drawPolygon(QPolygon([QPoint(28, 32), QPoint(36, 32), QPoint(24, 48)]))
            painter.setPen(QColor("#1f3b54"))
            painter.drawText(QRect(14, 6, 60, 26), Qt.AlignCenter, "Aa")
        elif kind == "cloud":
            painter.drawEllipse(16, 10, 22, 16)
            painter.drawEllipse(28, 4, 28, 20)
            painter.drawEllipse(46, 10, 22, 16)
            painter.setBrush(QColor("#2b6a9e"))
            painter.drawPolygon(QPolygon([QPoint(44, 48), QPoint(38, 34), QPoint(50, 34)]))
            painter.setPen(QColor("#1f3b54"))
            painter.drawText(QRect(20, 8, 48, 20), Qt.AlignCenter, "Aa")
        elif kind == "rect":
            painter.drawRect(14, 10, 60, 32)
            painter.setPen(QColor("#1f3b54"))
            painter.drawText(QRect(14, 10, 60, 32), Qt.AlignCenter, "Aa")
        else:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#b7c4ce"), 1, Qt.DashLine))
            painter.drawRect(14, 10, 60, 32)
            painter.setPen(QColor("#1f3b54"))
            painter.drawText(QRect(14, 10, 60, 32), Qt.AlignCenter, "Aa")
        painter.end()
        return QIcon(pixmap)

    def annotation_preview_font(
        self,
        font_size_pt: float,
        bold: bool,
        font_key: str,
        text: str = "",
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        windows_fonts = Path("C:/Windows/Fonts")
        latin_files = {
            "helvetica": ("arialbd.ttf", "arial.ttf"),
            "times": ("timesbd.ttf", "times.ttf"),
            "courier": ("courbd.ttf", "cour.ttf"),
        }
        cjk_names = (
            ("msjhbd.ttc", "msjh.ttc") if bold else ("msjh.ttc", "msjhbd.ttc")
        ) + (("msyhbd.ttc", "msyh.ttc") if bold else ("msyh.ttc", "msyhbd.ttc")) + (
            "mingliu.ttc",
            "simsun.ttc",
        )
        need_cjk = font_key in {"cjk", "yahei", "mingliu"} or text_contains_cjk(text)
        candidates: list[Path] = []
        if need_cjk:
            candidates.extend(windows_fonts / name for name in cjk_names)
        bold_name, regular_name = latin_files.get(font_key, latin_files["helvetica"])
        candidates.append(windows_fonts / (bold_name if bold else regular_name))
        if not need_cjk:
            candidates.extend(windows_fonts / name for name in cjk_names)
        candidates.append(windows_fonts / ("arialbd.ttf" if bold else "arial.ttf"))
        size = max(int(font_size_pt), 8)
        for path in candidates:
            if path.exists():
                try:
                    return ImageFont.truetype(str(path), size=size, index=0)
                except Exception:
                    continue
        return ImageFont.load_default()

    def draw_annotation_overlay_on_image(
        self,
        image: Image.Image,
        style: dict,
        page_size: tuple[float, float] | None = None,
    ) -> Image.Image:
        page_width, page_height = page_size or self.annotation_page_size
        if page_width <= 0 or page_height <= 0:
            return image
        canvas = image.copy()
        image_width, image_height = canvas.size
        scale_x = image_width / page_width
        scale_y = image_height / page_height

        left = style["pdf_x"] * scale_x
        bottom = image_height - style["pdf_y"] * scale_y
        width = style["rect_width"] * scale_x
        height = style["rect_height"] * scale_y
        top = bottom - height
        right = left + width
        bottom = top + height
        text = style["text"].strip()
        shape = style.get("shape") or "box"

        def to_image(x: float, y: float) -> tuple[float, float]:
            return (x * scale_x, image_height - y * scale_y)

        if shape in CALLOUT_KINDS:
            overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            paint_callout_markup(
                ImageDraw.Draw(overlay),
                MarkupAnnotation(
                    kind=shape,
                    x0=style["pointer_x"],
                    y0=style["pointer_y"],
                    x1=style["pdf_x"],
                    y1=style["pdf_y"],
                    color_rgb=style["color_rgb"],
                    contents=text or "註解",
                    box_width=style["rect_width"],
                    box_height=style["rect_height"],
                    fill_rgb=style.get("fill_rgb"),
                    fill_none=bool(style.get("fill_none")),
                ),
                to_image,
                draw_text=False,
            )
            canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)
            draw = ImageDraw.Draw(canvas)
        else:
            draw = ImageDraw.Draw(canvas)
            if shape == "rect":
                fill_rgb = resolve_annotation_fill(
                    style["color_rgb"],
                    style.get("fill_rgb"),
                    bool(style.get("fill_none")),
                )
                outline = tuple(int(channel * 255) for channel in style["color_rgb"])
                if fill_rgb is None:
                    draw.rounded_rectangle((left, top, right, bottom), radius=4, outline=outline, width=2)
                else:
                    fill = tuple(int(channel * 255) for channel in fill_rgb)
                    draw.rounded_rectangle((left, top, right, bottom), radius=4, fill=fill, outline=outline, width=2)
            elif style["cover"]:
                draw.rectangle((left, top, right, bottom), fill="#ffffff", outline="#b7c4ce", width=1)

        if text:
            preview_font_size = max(style["font_size"] * scale_y * 0.92, 8)
            font = self.annotation_preview_font(
                preview_font_size, style["bold"], style["font_key"], text
            )
            pdf_font = self.annotation_preview_font(
                style["font_size"], style["bold"], style["font_key"], text
            )
            inner_width = max(style["rect_width"] - ANNOTATION_BOX_PAD_X * 2, 16.0)
            lines = wrap_annotation_text(text, pdf_font, inner_width)
            line_height = annotation_font_line_height(pdf_font, style["font_size"]) * scale_y
            text_color = rgb_to_hex(style["color_rgb"])
            pad_x = ANNOTATION_BOX_PAD_X * scale_x
            pad_y = ANNOTATION_BOX_PAD_Y * scale_y
            max_bottom = bottom - 4
            for index, line in enumerate(lines):
                text_y = top + pad_y + index * line_height
                if text_y > max_bottom:
                    break
                draw.text((left + pad_x, text_y), line, fill=text_color, font=font)
        elif shape in CALLOUT_KINDS:
            preview_font_size = max(style["font_size"] * scale_y * 0.92, 8)
            font = self.annotation_preview_font(preview_font_size, False, style["font_key"], "註解")
            draw.text(
                (left + ANNOTATION_BOX_PAD_X * scale_x, top + ANNOTATION_BOX_PAD_Y * scale_y),
                "註解",
                fill="#8a96a3",
                font=font,
            )
        return canvas.convert("RGB")

    # --- markup annotations (highlight / shapes / sticky notes) --------------
    ANNOTATION_SHAPE_OPTIONS = [
        ("box", "無外框"),
        ("rect", "矩形框"),
        ("comment", "附註框"),
        ("callout", "標註框"),
        ("speech", "對話框"),
        ("cloud", "雲朵"),
    ]

    MARKUP_TOOL_OPTIONS = [
        ("highlight", "螢光標示"),
        ("underline", "底線"),
        ("strikeout", "刪除線"),
        ("rect", "矩形框"),
        ("ellipse", "橢圓框"),
        ("line", "直線"),
        ("arrow", "箭頭"),
        ("comment", "附註框（折線箭咀）"),
        ("callout", "標註框（帶指引線）"),
        ("speech", "對話框"),
        ("cloud", "雲朵標註"),
        ("note", "便利貼"),
    ]

    MARKUP_COLOR_OPTIONS = [
        ("yellow", "黃色"),
        ("green", "綠色"),
        ("blue", "藍色"),
        ("pink", "粉紅"),
        ("red", "紅色"),
        ("black", "黑色"),
        ("custom", "自訂..."),
    ]

    def build_markup_tab(self) -> QWidget:
        tab = PdfDropPanel()
        self._markup_tab = tab
        tab.filesDropped.connect(self.drop_markup_pdf)
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(10)
        top = QHBoxLayout()
        self.add_button(top, "載入 PDF", self.load_markup_pdf)
        top.addWidget(QLabel("頁碼"))
        self.markup_page_input = QLineEdit("1")
        self.markup_page_input.setFixedWidth(56)
        self.markup_page_validator = QIntValidator(1, 1, self)
        self.markup_page_input.setValidator(self.markup_page_validator)
        self.markup_page_input.editingFinished.connect(self.on_advanced_page_input_edited)
        top.addWidget(self.markup_page_input)
        self.add_button(top, "上一頁", lambda: self.change_markup_page(-1))
        self.add_button(top, "下一頁", lambda: self.change_markup_page(1))
        self.add_button(top, "更新預覽", self.render_markup_preview)
        top.addStretch(1)
        left.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.markup_preview_label = MarkupPreviewLabel()
        self.markup_preview_label.rectDrawn.connect(self.add_markup_from_rect)
        self.markup_preview_label.pointClicked.connect(self.add_markup_from_point)
        self.markup_preview_label.copyRequested.connect(self.copy_markup_item)
        self.markup_preview_label.pasteRequested.connect(self.paste_markup_item)
        self.markup_preview_label.undoRequested.connect(self.undo_markup_action)
        self.markup_preview_label.deleteRequested.connect(self.delete_selected_markup)
        scroll.setWidget(self.markup_preview_label)
        left.addWidget(scroll, 1)
        layout.addLayout(left, 1)

        side = QFrame()
        side.setObjectName("panel")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

        side_layout.addWidget(QLabel("標註工具"))
        self.markup_tool_combo = QComboBox()
        for value, label in self.MARKUP_TOOL_OPTIONS:
            self.markup_tool_combo.addItem(label, value)
        side_layout.addWidget(self.markup_tool_combo)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("顏色"))
        self.markup_color_combo = QComboBox()
        for value, label in self.MARKUP_COLOR_OPTIONS:
            self.markup_color_combo.addItem(label, value)
        self.markup_color_combo.currentIndexChanged.connect(self.on_markup_color_preset_changed)
        color_row.addWidget(self.markup_color_combo, 1)
        self.markup_color_button = QPushButton("選色")
        self.markup_color_button.setFixedWidth(56)
        self.markup_color_button.clicked.connect(self.choose_markup_color)
        color_row.addWidget(self.markup_color_button)
        side_layout.addLayout(color_row)

        fill_row = QHBoxLayout()
        fill_row.addWidget(QLabel("底色"))
        self.markup_fill_combo = QComboBox()
        self.markup_fill_combo.addItem("白色", "white")
        self.markup_fill_combo.addItem("無底色", "none")
        self.markup_fill_combo.addItem("淡黃", "yellow")
        self.markup_fill_combo.addItem("淺藍", "blue")
        self.markup_fill_combo.addItem("淺綠", "green")
        self.markup_fill_combo.addItem("跟隨外框", "follow")
        self.markup_fill_combo.addItem("自訂...", "custom")
        self.markup_fill_combo.currentIndexChanged.connect(self.on_markup_fill_preset_changed)
        fill_row.addWidget(self.markup_fill_combo, 1)
        self.markup_fill_button = QPushButton("選色")
        self.markup_fill_button.setFixedWidth(56)
        self.markup_fill_button.clicked.connect(self.choose_markup_fill_color)
        fill_row.addWidget(self.markup_fill_button)
        side_layout.addLayout(fill_row)

        side_layout.addWidget(QLabel("註解文字（標註框 / 對話框 / 便利貼）"))
        self.markup_note_input = QLineEdit()
        self.markup_note_input.setPlaceholderText("例如：請核對此數字")
        side_layout.addWidget(self.markup_note_input)

        side_layout.addWidget(QLabel("已加入的標註"))
        self.markup_list = QListWidget()
        self.markup_list.setMinimumHeight(120)
        self.markup_list.setMaximumHeight(180)
        side_layout.addWidget(self.markup_list)

        list_buttons = QHBoxLayout()
        self.add_button(list_buttons, "復原", self.undo_markup_action)
        self.add_button(list_buttons, "刪除選取", self.delete_selected_markup, "danger")
        self.add_button(list_buttons, "清空", self.clear_markups)
        side_layout.addLayout(list_buttons)

        side_layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.markup_password_input = QLineEdit()
        self.markup_password_input.setEchoMode(QLineEdit.Password)
        side_layout.addWidget(self.markup_password_input)

        save_button = self.add_button(side_layout, "套用並另存 PDF", self.save_markup_pdf, "primary")
        save_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        changed_button = self.add_button(side_layout, "另存有修改的頁", self.save_changed_pages_pdf)
        changed_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        guide = QLabel(
            "提示：標註框／對話框／雲朵／附註請從要指出的位置拖到文字框；"
            "便利貼用單擊放置。點選後 Ctrl+C 複製、Ctrl+V 貼到其他位置，Ctrl+Z 或「復原」可還原。"
            "可跨頁加入多個標註，最後一次另存。"
        )
        guide.setObjectName("muted")
        guide.setWordWrap(True)
        side_layout.addWidget(guide)
        side_layout.addStretch(1)
        layout.addWidget(wrap_side_panel(side, 330))
        return tab

    def load_markup_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "載入 PDF", "", "PDF files (*.pdf)")
        if path:
            self.load_advanced_pdf_from_path(Path(path), self.markup_password_input.text())

    def drop_markup_pdf(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() in PDF_SUFFIXES]
        if not pdf_paths:
            self.set_status("請拖放 PDF 檔案到註解分頁。")
            return
        self.load_advanced_pdf_from_path(pdf_paths[0], self.markup_password_input.text())

    def set_markup_pdf(self, path: Path) -> None:
        try:
            reader = open_reader(path, self.markup_password_input.text())
        except Exception as exc:
            self.show_error(exc)
            return
        self.markup_pdf_path = path
        self.markup_page_count = len(reader.pages)
        self.markup_items = []
        self._markup_undo_stack = []
        self._markup_clipboard = None
        self.refresh_markup_list()
        self.markup_page_validator.setRange(1, max(self.markup_page_count, 1))
        self.markup_page_input.setText("1")
        self.render_markup_preview()
        self.set_status(f"已載入 {path.name}，共 {self.markup_page_count} 頁。")

    def change_markup_page(self, delta: int) -> None:
        if self.markup_pdf_path is None:
            return
        current = int(self.markup_page_input.text() or "1")
        target = min(max(current + delta, 1), max(self.markup_page_count, 1))
        if target != current:
            self.set_advanced_page(target - 1)

    def current_markup_page_index(self) -> int:
        return int(self.markup_page_input.text() or "1") - 1

    def render_markup_preview(self) -> None:
        if self.markup_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        if not PDF_RENDER_AVAILABLE or pdfium is None:
            self.set_status("PDF 預覽元件未啟用。")
            return
        try:
            page_number = min(max(int(self.markup_page_input.text() or "1"), 1), self.markup_page_count)
            self.markup_page_input.setText(str(page_number))
            document = pdfium.PdfDocument(str(self.markup_pdf_path), password=self.markup_password_input.text() or None)
            page = document.get_page(page_number - 1)
            page_width, page_height = page.get_size()
            scale = self.advanced_preview_scale(page_width, page_height)
            image = page.render(scale=scale).to_pil().convert("RGB")
            page.close()
            document.close()
            self.markup_page_size = (float(page_width), float(page_height))
            self.markup_preview_image = image
            self.update_markup_preview_display()
        except Exception as exc:
            self.show_error(exc)

    def update_markup_preview_display(self) -> None:
        if self.markup_preview_image is None:
            self.markup_preview_label.clear()
            return
        page_width, page_height = self.markup_page_size
        canvas = self.markup_preview_image.convert("RGBA")
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        image_width, image_height = canvas.size
        scale_x = image_width / page_width if page_width else 1.0
        scale_y = image_height / page_height if page_height else 1.0
        current_page = self.current_markup_page_index()

        def to_image(x: float, y: float) -> tuple[float, float]:
            return (x * scale_x, image_height - y * scale_y)

        for page_index, markup in self.markup_items:
            if page_index != current_page:
                continue
            red, green, blue = (int(max(0.0, min(c, 1.0)) * 255) for c in markup.color_rgb)
            ix0, iy0 = to_image(markup.x0, markup.y0)
            ix1, iy1 = to_image(markup.x1, markup.y1)
            box = (min(ix0, ix1), min(iy0, iy1), max(ix0, ix1), max(iy0, iy1))
            if markup.kind == "highlight":
                draw.rectangle(box, fill=(red, green, blue, 90))
            elif markup.kind == "underline":
                draw.line((box[0], box[3], box[2], box[3]), fill=(red, green, blue, 255), width=3)
            elif markup.kind == "strikeout":
                mid = (box[1] + box[3]) / 2
                draw.line((box[0], mid, box[2], mid), fill=(red, green, blue, 255), width=3)
            elif markup.kind == "rect":
                draw.rectangle(box, outline=(red, green, blue, 255), width=2)
            elif markup.kind == "ellipse":
                draw.ellipse(box, outline=(red, green, blue, 255), width=2)
            elif markup.kind in {"line", "arrow"}:
                draw.line((ix0, iy0, ix1, iy1), fill=(red, green, blue, 255), width=2)
                if markup.kind == "arrow":
                    self._draw_arrow_head(draw, ix0, iy0, ix1, iy1, (red, green, blue, 255))
            elif markup.kind == "note":
                draw.rectangle((ix0, iy0 - 16, ix0 + 16, iy0), fill=(red, green, blue, 230), outline=(60, 60, 60, 255))
                draw.text((ix0 + 4, iy0 - 15), "N", fill=(20, 20, 20, 255))
            elif markup.kind in CALLOUT_KINDS:
                paint_callout_markup(draw, markup, to_image)

        merged = Image.alpha_composite(canvas, overlay).convert("RGB")
        pixmap = QPixmap.fromImage(ImageQt(merged))
        self.markup_preview_label.set_preview_pixmap(pixmap)

    def _draw_arrow_head(self, draw, x0: float, y0: float, x1: float, y1: float, color) -> None:
        import math

        angle = math.atan2(y1 - y0, x1 - x0)
        length = 12
        for offset in (math.pi - 0.5, math.pi + 0.5):
            hx = x1 + length * math.cos(angle + offset)
            hy = y1 + length * math.sin(angle + offset)
            draw.line((x1, y1, hx, hy), fill=color, width=2)

    def _markup_item_image_rect(self, markup: MarkupAnnotation) -> QRect:
        page_width, page_height = self.markup_page_size
        image = self.markup_preview_image
        if image is None or page_width <= 0 or page_height <= 0:
            return QRect()
        image_width, image_height = image.size

        def to_img(x: float, y: float) -> QPoint:
            return QPoint(
                int(round(x / page_width * image_width)),
                int(round((page_height - y) / page_height * image_height)),
            )

        if markup.kind in CALLOUT_KINDS:
            layout = callout_layout(markup)
            return QRect(to_img(layout.left, layout.top), to_img(layout.right, layout.bottom)).normalized()
        if markup.kind == "note":
            origin = to_img(markup.x0, markup.y0)
            return QRect(origin.x(), origin.y() - 16, 16, 16)
        return QRect(to_img(markup.x0, markup.y0), to_img(markup.x1, markup.y1)).normalized()

    def _markup_text_item_at_point(self, point: QPoint) -> int | None:
        page = self.current_markup_page_index()
        for index in range(len(self.markup_items) - 1, -1, -1):
            page_index, markup = self.markup_items[index]
            if page_index != page:
                continue
            if markup.kind not in CALLOUT_KINDS | {"note"}:
                continue
            rect = self._markup_item_image_rect(markup)
            if rect_chrome_contains(rect, point) or rect.adjusted(-3, -3, 3, 3).contains(point):
                return index
        return None

    def markup_image_point_to_pdf(self, point: QPoint) -> tuple[float, float]:
        page_width, page_height = self.markup_page_size
        image = self.markup_preview_image
        if image is None or page_width <= 0 or page_height <= 0:
            return (0.0, 0.0)
        image_width, image_height = image.size
        ix = min(max(point.x(), 0), image_width)
        iy = min(max(point.y(), 0), image_height)
        pdf_x = ix / image_width * page_width
        pdf_y = page_height - (iy / image_height * page_height)
        return (pdf_x, pdf_y)

    def markup_current_color(self) -> tuple[float, float, float]:
        preset = self.markup_color_combo.currentData()
        if preset in MARKUP_COLOR_PRESETS:
            return MARKUP_COLOR_PRESETS[preset]
        return self.markup_color_rgb

    def on_markup_color_preset_changed(self) -> None:
        preset = self.markup_color_combo.currentData()
        if preset == "custom":
            self.choose_markup_color()
            return
        if preset in MARKUP_COLOR_PRESETS:
            self.markup_color_rgb = MARKUP_COLOR_PRESETS[preset]

    def choose_markup_color(self) -> None:
        current = QColor.fromRgbF(*self.markup_color_rgb)
        chosen = QColorDialog.getColor(current, self, "選擇標註顏色")
        if not chosen.isValid():
            return
        self.markup_color_rgb = (chosen.redF(), chosen.greenF(), chosen.blueF())
        custom_index = self.markup_color_combo.findData("custom")
        if custom_index >= 0:
            self.markup_color_combo.setCurrentIndex(custom_index)

    def on_markup_fill_preset_changed(self) -> None:
        preset = self.markup_fill_combo.currentData()
        if preset == "custom":
            self.choose_markup_fill_color()
            return
        if preset == "none":
            self.markup_fill_none = True
            self.markup_fill_rgb = (1.0, 1.0, 1.0)
        elif preset == "follow":
            self.markup_fill_none = False
            self.markup_fill_rgb = None
        elif preset in ANNOTATION_FILL_PRESETS:
            self.markup_fill_none = False
            self.markup_fill_rgb = ANNOTATION_FILL_PRESETS[preset]

    def choose_markup_fill_color(self) -> None:
        current = QColor.fromRgbF(*(self.markup_fill_rgb or (1.0, 1.0, 1.0)))
        chosen = QColorDialog.getColor(current, self, "選擇底色")
        if not chosen.isValid():
            return
        self.markup_fill_none = False
        self.markup_fill_rgb = (chosen.redF(), chosen.greenF(), chosen.blueF())
        custom_index = self.markup_fill_combo.findData("custom")
        if custom_index >= 0:
            self.markup_fill_combo.setCurrentIndex(custom_index)

    def _markup_fill_values(self) -> tuple[tuple[float, float, float] | None, bool]:
        if self.markup_fill_none:
            return None, True
        return self.markup_fill_rgb, False

    def add_markup_from_rect(self, start: QPoint, end: QPoint) -> None:
        if self.markup_preview_image is None:
            self.set_status("請先載入 PDF 並更新預覽。")
            return
        kind = self.markup_tool_combo.currentData() or "highlight"
        if kind == "note":
            self.add_markup_from_point(start)
            return
        x0, y0 = self.markup_image_point_to_pdf(start)
        x1, y1 = self.markup_image_point_to_pdf(end)
        contents = self.markup_note_input.text().strip()
        if kind in CALLOUT_KINDS:
            contents = contents or "註解"
        fill_rgb, fill_none = self._markup_fill_values()
        markup = MarkupAnnotation(
            kind=kind,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            color_rgb=self.markup_current_color(),
            contents=contents,
            fill_rgb=fill_rgb,
            fill_none=fill_none,
        )
        self._push_markup_undo()
        self.markup_items.append((self.current_markup_page_index(), markup))
        if kind in {"note"} | CALLOUT_KINDS:
            self.markup_note_input.clear()
        self.refresh_markup_list()
        self.update_markup_preview_display()
        self.set_status(f"已加入標註：{self._markup_label(markup)}")

    def add_markup_from_point(self, point: QPoint) -> None:
        if self.markup_preview_image is None:
            self.set_status("請先載入 PDF 並更新預覽。")
            return
        hit = self._markup_text_item_at_point(point)
        if hit is not None:
            self.markup_list.setCurrentRow(hit)
            arm_box_delete(self.markup_preview_label)
            self.set_status("已選取標註，按 Delete 刪除。")
            return
        kind = self.markup_tool_combo.currentData() or "highlight"
        if kind not in {"note"} | CALLOUT_KINDS:
            self.set_status("此工具需要拖曳：從要指出的位置拉到文字框。")
            return
        x0, y0 = self.markup_image_point_to_pdf(point)
        fill_rgb, fill_none = self._markup_fill_values()
        if kind in CALLOUT_KINDS:
            markup = MarkupAnnotation(
                kind=kind,
                x0=x0,
                y0=y0,
                x1=x0 + 140.0,
                y1=y0 + 50.0,
                color_rgb=self.markup_current_color(),
                contents=self.markup_note_input.text().strip() or "註解",
                fill_rgb=fill_rgb,
                fill_none=fill_none,
            )
        else:
            markup = MarkupAnnotation(
                kind="note",
                x0=x0,
                y0=y0,
                x1=x0,
                y1=y0,
                color_rgb=self.markup_current_color(),
                contents=self.markup_note_input.text().strip() or "備註",
                fill_rgb=fill_rgb,
                fill_none=fill_none,
            )
        self._push_markup_undo()
        self.markup_items.append((self.current_markup_page_index(), markup))
        self.markup_note_input.clear()
        self.refresh_markup_list()
        self.update_markup_preview_display()
        self.set_status(f"已加入標註：{self._markup_label(markup)}")

    def _markup_label(self, markup: MarkupAnnotation) -> str:
        names = dict(self.MARKUP_TOOL_OPTIONS)
        return names.get(markup.kind, markup.kind)

    def refresh_markup_list(self) -> None:
        self.markup_list.clear()
        for page_index, markup in self.markup_items:
            label = f"第 {page_index + 1} 頁 · {self._markup_label(markup)}"
            if markup.contents and markup.kind in {"note"} | CALLOUT_KINDS:
                label += f"：{markup.contents[:12]}"
            self.markup_list.addItem(label)

    def delete_selected_markup(self) -> None:
        row = self.markup_list.currentRow()
        if not (0 <= row < len(self.markup_items)):
            page = self.current_markup_page_index()
            row = next(
                (
                    index
                    for index in range(len(self.markup_items) - 1, -1, -1)
                    if self.markup_items[index][0] == page
                ),
                -1,
            )
        if not (0 <= row < len(self.markup_items)):
            self.set_status("請先選取要刪除的標註。")
            return
        self._push_markup_undo()
        self.markup_items.pop(row)
        self.refresh_markup_list()
        self.update_markup_preview_display()
        self._clear_box_delete_arm()
        self.set_status("已刪除標註。")

    def clear_markups(self) -> None:
        if not self.markup_items:
            return
        self._push_markup_undo()
        self.markup_items = []
        self.refresh_markup_list()
        self.update_markup_preview_display()
        self.set_status("已清空標註。")

    def _clone_markup_items(self) -> list[tuple[int, MarkupAnnotation]]:
        return [(page_index, replace(markup)) for page_index, markup in self.markup_items]

    def _push_markup_undo(self) -> None:
        self._markup_undo_stack.append(self._clone_markup_items())
        if len(self._markup_undo_stack) > 40:
            self._markup_undo_stack.pop(0)

    def undo_markup_action(self) -> None:
        if not self._markup_undo_stack:
            self.set_status("沒有可復原的標註動作。")
            return
        self.markup_items = self._markup_undo_stack.pop()
        self.refresh_markup_list()
        self.update_markup_preview_display()
        self.set_status("已復原標註。")

    def copy_markup_item(self) -> None:
        row = self.markup_list.currentRow() if hasattr(self, "markup_list") else -1
        if 0 <= row < len(self.markup_items):
            _page, markup = self.markup_items[row]
        elif self.markup_items:
            page = self.current_markup_page_index()
            on_page = [item for item in self.markup_items if item[0] == page]
            _page, markup = on_page[-1] if on_page else self.markup_items[-1]
        else:
            self.set_status("請先加入標註後再複製。")
            return
        self._markup_clipboard = replace(markup)
        QApplication.clipboard().setText(markup.contents or "")
        self.set_status("已複製標註。到其他位置按 Ctrl+V 貼上。")

    def paste_markup_item(self) -> None:
        if self._markup_clipboard is None:
            self.set_status("請先點選標註後按 Ctrl+C。")
            return
        self._push_markup_undo()
        source = self._markup_clipboard
        pasted = replace(
            source,
            x0=source.x0 + 16.0,
            y0=source.y0 - 16.0,
            x1=source.x1 + 16.0,
            y1=source.y1 - 16.0,
        )
        self.markup_items.append((self.current_markup_page_index(), pasted))
        self.refresh_markup_list()
        self.markup_list.setCurrentRow(len(self.markup_items) - 1)
        self.update_markup_preview_display()
        self.set_status("已貼上標註。")

    def save_markup_pdf(self) -> None:
        if self.markup_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        if not self.markup_items:
            self.set_status("請先加入至少一個標註。")
            return
        target, _ = QFileDialog.getSaveFileName(self, "另存註解 PDF", "marked-up.pdf", "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)
        markups = list(self.markup_items)
        applied = {"value": 0}

        def job() -> None:
            applied["value"] = apply_markup_annotations(
                self.markup_pdf_path,
                target_path,
                markups,
                self.markup_password_input.text(),
            )

        self.run_pdf_job(
            job,
            "",
            on_success=lambda: (
                self.open_pdf_as_new_tab(target_path),
                self.set_status(f"已套用 {applied['value']} 個標註並另存：{target_path.name}"),
            ),
        )

    # --- page cropping -------------------------------------------------------
    def build_crop_tab(self) -> QWidget:
        tab = PdfDropPanel()
        tab.filesDropped.connect(self.drop_crop_pdf)
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(10)
        top = QHBoxLayout()
        self.add_button(top, "載入 PDF", self.load_crop_pdf)
        top.addWidget(QLabel("頁碼"))
        self.crop_page_input = QLineEdit("1")
        self.crop_page_input.setFixedWidth(56)
        self.crop_page_validator = QIntValidator(1, 1, self)
        self.crop_page_input.setValidator(self.crop_page_validator)
        self.crop_page_input.editingFinished.connect(self.on_advanced_page_input_edited)
        top.addWidget(self.crop_page_input)
        self.add_button(top, "上一頁", lambda: self.change_crop_page(-1))
        self.add_button(top, "下一頁", lambda: self.change_crop_page(1))
        self.add_button(top, "更新預覽", self.render_crop_preview)
        top.addStretch(1)
        left.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.crop_preview_label = MarkupPreviewLabel()
        self.crop_preview_label.band_color = QColor(214, 69, 65)
        self.crop_preview_label.rectDrawn.connect(self.set_crop_rect_from_drag)
        scroll.setWidget(self.crop_preview_label)
        left.addWidget(scroll, 1)
        layout.addLayout(left, 1)

        side = QFrame()
        side.setObjectName("panel")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

        intro = QLabel("在左側預覽上拖曳框選「要保留」的區域，或直接輸入裁切框數值（PDF 點，原點在左下角）。")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        side_layout.addWidget(intro)

        side_layout.addWidget(QLabel("裁切框 左 / 下 / 右 / 上"))
        rect_row = QHBoxLayout()
        self.crop_left_input = QLineEdit()
        self.crop_bottom_input = QLineEdit()
        self.crop_right_input = QLineEdit()
        self.crop_top_input = QLineEdit()
        for widget in (self.crop_left_input, self.crop_bottom_input, self.crop_right_input, self.crop_top_input):
            widget.setPlaceholderText("0")
            widget.textChanged.connect(self.on_crop_inputs_changed)
            rect_row.addWidget(widget)
        side_layout.addLayout(rect_row)

        side_layout.addWidget(QLabel("套用範圍"))
        self.crop_scope_combo = QComboBox()
        self.crop_scope_combo.addItem("目前頁", "current")
        self.crop_scope_combo.addItem("全部頁", "all")
        self.crop_scope_combo.addItem("自訂頁碼", "spec")
        self.crop_scope_combo.currentIndexChanged.connect(self.on_crop_scope_changed)
        side_layout.addWidget(self.crop_scope_combo)

        self.crop_pages_input = QLineEdit()
        self.crop_pages_input.setPlaceholderText("例如 1-3,5")
        self.crop_pages_input.setEnabled(False)
        side_layout.addWidget(self.crop_pages_input)

        self.add_button(side_layout, "重設為整頁", self.reset_crop_rect)

        side_layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.crop_password_input = QLineEdit()
        self.crop_password_input.setEchoMode(QLineEdit.Password)
        side_layout.addWidget(self.crop_password_input)

        save_button = self.add_button(side_layout, "裁切並另存 PDF", self.save_crop_pdf, "primary")
        save_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        side_layout.addStretch(1)
        layout.addWidget(wrap_side_panel(side, 320))
        return tab

    def load_crop_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "載入 PDF", "", "PDF files (*.pdf)")
        if path:
            self.load_advanced_pdf_from_path(Path(path), self.crop_password_input.text())

    def drop_crop_pdf(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() in PDF_SUFFIXES]
        if not pdf_paths:
            self.set_status("請拖放 PDF 檔案到裁切分頁。")
            return
        self.load_advanced_pdf_from_path(pdf_paths[0], self.crop_password_input.text())

    def set_crop_pdf(self, path: Path) -> None:
        try:
            reader = open_reader(path, self.crop_password_input.text())
        except Exception as exc:
            self.show_error(exc)
            return
        self.crop_pdf_path = path
        self.crop_page_count = len(reader.pages)
        self.crop_rect = None
        self.crop_page_validator.setRange(1, max(self.crop_page_count, 1))
        self.crop_page_input.setText("1")
        self.render_crop_preview()
        self.reset_crop_rect()
        self.set_status(f"已載入 {path.name}，共 {self.crop_page_count} 頁。")

    def change_crop_page(self, delta: int) -> None:
        if self.crop_pdf_path is None:
            return
        current = int(self.crop_page_input.text() or "1")
        target = min(max(current + delta, 1), max(self.crop_page_count, 1))
        if target != current:
            self.set_advanced_page(target - 1)

    def render_crop_preview(self) -> None:
        if self.crop_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        if not PDF_RENDER_AVAILABLE or pdfium is None:
            self.set_status("PDF 預覽元件未啟用。")
            return
        try:
            page_number = min(max(int(self.crop_page_input.text() or "1"), 1), self.crop_page_count)
            self.crop_page_input.setText(str(page_number))
            document = pdfium.PdfDocument(str(self.crop_pdf_path), password=self.crop_password_input.text() or None)
            page = document.get_page(page_number - 1)
            page_width, page_height = page.get_size()
            scale = self.advanced_preview_scale(page_width, page_height)
            image = page.render(scale=scale).to_pil().convert("RGB")
            page.close()
            document.close()
            self.crop_page_size = (float(page_width), float(page_height))
            self.crop_preview_image = image
            self.update_crop_preview_display()
        except Exception as exc:
            self.show_error(exc)

    def update_crop_preview_display(self) -> None:
        if self.crop_preview_image is None:
            self.crop_preview_label.clear()
            return
        page_width, page_height = self.crop_page_size
        canvas = self.crop_preview_image.convert("RGBA")
        image_width, image_height = canvas.size
        if self.crop_rect is not None and page_width > 0 and page_height > 0:
            left, bottom, right, top = self.crop_rect
            scale_x = image_width / page_width
            scale_y = image_height / page_height
            ix0 = left * scale_x
            ix1 = right * scale_x
            iy0 = image_height - top * scale_y
            iy1 = image_height - bottom * scale_y
            overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 120))
            clear = ImageDraw.Draw(overlay)
            clear.rectangle((ix0, iy0, ix1, iy1), fill=(0, 0, 0, 0))
            canvas = Image.alpha_composite(canvas, overlay)
            outline = ImageDraw.Draw(canvas)
            outline.rectangle((ix0, iy0, ix1, iy1), outline=(214, 69, 65, 255), width=2)
        merged = canvas.convert("RGB")
        pixmap = QPixmap.fromImage(ImageQt(merged))
        self.crop_preview_label.set_preview_pixmap(pixmap)

    def crop_image_point_to_pdf(self, point: QPoint) -> tuple[float, float]:
        page_width, page_height = self.crop_page_size
        image = self.crop_preview_image
        if image is None or page_width <= 0 or page_height <= 0:
            return (0.0, 0.0)
        image_width, image_height = image.size
        ix = min(max(point.x(), 0), image_width)
        iy = min(max(point.y(), 0), image_height)
        pdf_x = ix / image_width * page_width
        pdf_y = page_height - (iy / image_height * page_height)
        return (pdf_x, pdf_y)

    def set_crop_rect_from_drag(self, start: QPoint, end: QPoint) -> None:
        if self.crop_preview_image is None:
            self.set_status("請先載入 PDF 並更新預覽。")
            return
        x0, y0 = self.crop_image_point_to_pdf(start)
        x1, y1 = self.crop_image_point_to_pdf(end)
        left, right = min(x0, x1), max(x0, x1)
        bottom, top = min(y0, y1), max(y0, y1)
        self.set_crop_rect((left, bottom, right, top))
        self.set_status(f"裁切框：左 {left:.0f} 下 {bottom:.0f} 右 {right:.0f} 上 {top:.0f}")

    def set_crop_rect(self, rect: tuple[float, float, float, float], update_inputs: bool = True) -> None:
        self.crop_rect = rect
        if update_inputs:
            left, bottom, right, top = rect
            for widget, value in (
                (self.crop_left_input, left),
                (self.crop_bottom_input, bottom),
                (self.crop_right_input, right),
                (self.crop_top_input, top),
            ):
                widget.blockSignals(True)
                widget.setText(f"{value:.1f}")
                widget.blockSignals(False)
        self.update_crop_preview_display()

    def on_crop_inputs_changed(self) -> None:
        rect = self.crop_rect_from_inputs()
        if rect is not None:
            self.crop_rect = rect
            self.update_crop_preview_display()

    def crop_rect_from_inputs(self) -> tuple[float, float, float, float] | None:
        try:
            left = float(self.crop_left_input.text())
            bottom = float(self.crop_bottom_input.text())
            right = float(self.crop_right_input.text())
            top = float(self.crop_top_input.text())
        except ValueError:
            return None
        return (left, bottom, right, top)

    def reset_crop_rect(self) -> None:
        page_width, page_height = self.crop_page_size
        if page_width <= 0 or page_height <= 0:
            return
        self.set_crop_rect((0.0, 0.0, page_width, page_height))

    def on_crop_scope_changed(self) -> None:
        self.crop_pages_input.setEnabled(self.crop_scope_combo.currentData() == "spec")

    def save_crop_pdf(self) -> None:
        if self.crop_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        rect = self.crop_rect_from_inputs()
        if rect is None:
            self.set_status("裁切框數值無效，請重新框選或輸入數字。")
            return
        scope = self.crop_scope_combo.currentData()
        if scope == "current":
            pages_spec = str(self.current_crop_page_index() + 1)
        elif scope == "spec":
            pages_spec = self.crop_pages_input.text().strip()
            if not pages_spec:
                self.set_status("請輸入要裁切的頁碼範圍。")
                return
        else:
            pages_spec = ""
        target, _ = QFileDialog.getSaveFileName(self, "另存裁切 PDF", "cropped.pdf", "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)
        cropped = {"value": 0}

        def job() -> None:
            cropped["value"] = crop_pdf_pages(
                self.crop_pdf_path,
                target_path,
                rect,
                pages_spec,
                self.crop_password_input.text(),
            )

        self.run_pdf_job(
            job,
            "",
            on_success=lambda: (
                self.open_pdf_as_new_tab(target_path),
                self.set_status(f"已裁切 {cropped['value']} 頁並另存：{target_path.name}"),
            ),
        )

    def current_crop_page_index(self) -> int:
        return int(self.crop_page_input.text() or "1") - 1

    def build_erase_tab(self) -> QWidget:
        tab = PdfDropPanel()
        self._erase_tab = tab
        tab.filesDropped.connect(self.drop_erase_pdf)
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(10)
        top = QHBoxLayout()
        self.add_button(top, "載入 PDF", self.load_erase_pdf)
        top.addWidget(QLabel("頁碼"))
        self.erase_page_input = QLineEdit("1")
        self.erase_page_input.setFixedWidth(56)
        self.erase_page_validator = QIntValidator(1, 1, self)
        self.erase_page_input.setValidator(self.erase_page_validator)
        self.erase_page_input.editingFinished.connect(self.on_advanced_page_input_edited)
        top.addWidget(self.erase_page_input)
        self.add_button(top, "上一頁", lambda: self.change_erase_page(-1))
        self.add_button(top, "下一頁", lambda: self.change_erase_page(1))
        self.add_button(top, "更新預覽", self.render_erase_preview)
        top.addStretch(1)
        left.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.erase_preview_label = ErasePreviewLabel()
        self.erase_preview_label.setCursor(Qt.BlankCursor)
        self.erase_preview_label.strokePoint.connect(self.add_erase_stroke_point)
        self.erase_preview_label.strokeFinished.connect(self.finish_erase_stroke)
        self.erase_preview_label.rectDrawn.connect(self.add_erase_rect)
        self.erase_preview_label.pointClicked.connect(self.add_erase_text_at_point)
        self.erase_preview_label.boxResized.connect(self.resize_erase_text_box_from_handle)
        self.erase_preview_label.boxMoved.connect(self.move_erase_text_box)
        self.erase_preview_label.boxInteractionFinished.connect(self.finish_erase_text_box_interaction)
        self.erase_preview_label.inlineEdited.connect(self.on_erase_inline_text_edited)
        self.erase_preview_label.copyRequested.connect(self.copy_erase_text_box)
        self.erase_preview_label.pasteRequested.connect(self.paste_erase_text_box)
        self.erase_preview_label.undoRequested.connect(self.undo_erase_mark)
        self.erase_preview_label.deleteRequested.connect(self.delete_current_erase_item)
        scroll.setWidget(self.erase_preview_label)
        left.addWidget(scroll, 1)
        layout.addLayout(left, 1)

        side = QFrame()
        side.setObjectName("panel")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

        side_layout.addWidget(QLabel("工具"))
        tool_row = QHBoxLayout()
        self.erase_brush_button = QPushButton("橡皮刷")
        self.erase_brush_button.setCheckable(True)
        self.erase_brush_button.setChecked(True)
        self.erase_rect_button = QPushButton("長方形")
        self.erase_rect_button.setCheckable(True)
        self.erase_text_button = QPushButton("文字方塊")
        self.erase_text_button.setCheckable(True)
        self.erase_brush_button.clicked.connect(lambda: self.set_erase_tool("brush"))
        self.erase_rect_button.clicked.connect(lambda: self.set_erase_tool("rect"))
        self.erase_text_button.clicked.connect(lambda: self.set_erase_tool("text"))
        tool_row.addWidget(self.erase_brush_button, 1)
        tool_row.addWidget(self.erase_rect_button, 1)
        tool_row.addWidget(self.erase_text_button, 1)
        side_layout.addLayout(tool_row)

        side_layout.addWidget(QLabel("顏色"))
        self.erase_color_combo = QComboBox()
        self.erase_color_combo.addItem("白色", "white")
        self.erase_color_combo.addItem("黑色", "black")
        self.erase_color_combo.currentIndexChanged.connect(self.update_erase_preview_display)
        side_layout.addWidget(self.erase_color_combo)

        side_layout.addWidget(QLabel("橡皮刷大小"))
        size_row = QHBoxLayout()
        self.erase_size_slider = QSlider(Qt.Horizontal)
        self.erase_size_slider.setRange(8, 80)
        self.erase_size_slider.setValue(28)
        self.erase_size_slider.valueChanged.connect(self.on_erase_size_changed)
        size_row.addWidget(self.erase_size_slider, 1)
        self.erase_size_label = QLabel("直徑 28 pt")
        self.erase_size_label.setFixedWidth(78)
        size_row.addWidget(self.erase_size_label)
        side_layout.addLayout(size_row)

        self.erase_remove_content_checkbox = QCheckBox("徹底刪除底層文字／圖（塗銷）")
        self.erase_remove_content_checkbox.setChecked(True)
        side_layout.addWidget(self.erase_remove_content_checkbox)

        side_layout.addWidget(QLabel("文字方塊內容（點預覽即出現方塊，可直接打字）"))
        self.erase_text_input = QTextEdit()
        self.erase_text_input.setPlaceholderText("點預覽放置方塊後，在框內或這裡輸入文字")
        self.erase_text_input.setFixedHeight(72)
        self.erase_text_input.textChanged.connect(self.on_erase_sidebar_text_changed)
        side_layout.addWidget(self.erase_text_input)
        text_size_row = QHBoxLayout()
        text_size_row.addWidget(QLabel("文字大小"))
        self.erase_text_size_combo = QComboBox()
        configure_font_size_combo(self.erase_text_size_combo, "18", self.on_erase_text_style_changed)
        text_size_row.addWidget(self.erase_text_size_combo, 1)
        self.erase_text_bold_checkbox = QCheckBox("粗體")
        self.erase_text_bold_checkbox.toggled.connect(self.on_erase_text_style_changed)
        text_size_row.addWidget(self.erase_text_bold_checkbox)
        side_layout.addLayout(text_size_row)
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("字型"))
        self.erase_text_font_combo = QComboBox()
        self.erase_text_font_combo.addItem("中文（微軟雅黑／正黑體）", "cjk")
        self.erase_text_font_combo.addItem("Helvetica", "helvetica")
        self.erase_text_font_combo.currentIndexChanged.connect(self.on_erase_text_style_changed)
        font_row.addWidget(self.erase_text_font_combo, 1)
        side_layout.addLayout(font_row)
        text_color_row = QHBoxLayout()
        text_color_row.addWidget(QLabel("文字顏色"))
        self.erase_text_color_combo = QComboBox()
        self.erase_text_color_combo.addItem("黑色", "black")
        self.erase_text_color_combo.addItem("紅色", "red")
        self.erase_text_color_combo.addItem("藍色", "blue")
        self.erase_text_color_combo.addItem("白色", "white")
        self.erase_text_color_combo.addItem("自訂...", "custom")
        self.erase_text_color_combo.currentIndexChanged.connect(self.on_erase_text_color_changed)
        text_color_row.addWidget(self.erase_text_color_combo, 1)
        self.erase_text_color_button = QPushButton("選色")
        self.erase_text_color_button.setFixedWidth(56)
        self.erase_text_color_button.clicked.connect(self.choose_erase_text_color)
        text_color_row.addWidget(self.erase_text_color_button)
        side_layout.addLayout(text_color_row)

        side_layout.addWidget(QLabel("本頁標記"))
        self.erase_mark_list = QListWidget()
        self.erase_mark_list.setMinimumHeight(90)
        self.erase_mark_list.setMaximumHeight(160)
        side_layout.addWidget(self.erase_mark_list)

        undo_row = QHBoxLayout()
        self.add_button(undo_row, "復原上一筆", self.undo_erase_mark)
        self.add_button(undo_row, "清除本頁", self.clear_erase_marks_on_page)
        side_layout.addLayout(undo_row)

        side_layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.erase_password_input = QLineEdit()
        self.erase_password_input.setEchoMode(QLineEdit.Password)
        side_layout.addWidget(self.erase_password_input)

        save_button = self.add_button(side_layout, "套用並另存 PDF", self.save_erase_pdf, "primary")
        save_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        changed_button = self.add_button(side_layout, "另存有修改的頁", self.save_changed_pages_pdf)
        changed_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        guide = QLabel(
            "選「文字方塊」後點預覽，方塊會立刻出現。可直接在框內打字、拖角縮放、改字型顏色。"
            "點選方塊後 Ctrl+C 複製、Ctrl+V 貼到其他位置，Ctrl+Z 或「復原上一筆」可還原。"
        )
        guide.setObjectName("muted")
        guide.setWordWrap(True)
        side_layout.addWidget(guide)
        side_layout.addStretch(1)
        layout.addWidget(wrap_side_panel(side, 320))
        return tab

    def load_erase_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "載入 PDF", "", "PDF files (*.pdf)")
        if path:
            self.load_advanced_pdf_from_path(Path(path), self.erase_password_input.text())

    def drop_erase_pdf(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() in PDF_SUFFIXES]
        if not pdf_paths:
            self.set_status("請拖放 PDF 檔案到橡皮擦分頁。")
            return
        self.load_advanced_pdf_from_path(pdf_paths[0], self.erase_password_input.text())

    def set_erase_pdf(self, path: Path) -> None:
        try:
            reader = open_reader(path, self.erase_password_input.text())
        except Exception as exc:
            self.show_error(exc)
            return
        self.erase_pdf_path = path
        self.erase_page_count = len(reader.pages)
        self.erase_marks = []
        self._erase_live_points = []
        self._erase_text_selected = None
        self._erase_undo_stack = []
        self._erase_text_clipboard = None
        self.erase_page_validator.setRange(1, max(self.erase_page_count, 1))
        self.erase_page_input.setText("1")
        self.refresh_erase_list()
        self.render_erase_preview()
        self.set_status(f"已載入 {path.name}，共 {self.erase_page_count} 頁。")

    def change_erase_page(self, delta: int) -> None:
        if self.erase_pdf_path is None:
            return
        current = int(self.erase_page_input.text() or "1")
        target = min(max(current + delta, 1), max(self.erase_page_count, 1))
        if target != current:
            self.set_advanced_page(target - 1)

    def current_erase_page_index(self) -> int:
        return int(self.erase_page_input.text() or "1") - 1

    def erase_brush_radius(self) -> float:
        return float(self.erase_size_slider.value()) / 2.0

    def erase_color_rgb(self) -> tuple[float, float, float]:
        if self.erase_color_combo.currentData() == "black":
            return (0.0, 0.0, 0.0)
        return (1.0, 1.0, 1.0)

    def set_erase_tool(self, tool: str) -> None:
        self.erase_brush_button.setChecked(tool == "brush")
        self.erase_rect_button.setChecked(tool == "rect")
        self.erase_text_button.setChecked(tool == "text")
        self.erase_preview_label.tool = tool
        self.erase_size_slider.setEnabled(tool == "brush")
        if tool == "brush":
            self.erase_preview_label.setCursor(Qt.BlankCursor)
            self.set_status("橡皮刷：預覽上的圈圈就是實際大小，按住拖動。擦完可改選「文字方塊」蓋上新字。")
        elif tool == "rect":
            self.erase_preview_label.setCursor(Qt.CrossCursor)
            self.set_status("長方形：拖出範圍後會立刻遮擋。擦完可改選「文字方塊」。")
        else:
            self.erase_preview_label.setCursor(Qt.IBeamCursor)
            self.set_status("文字方塊：點預覽即出現方塊，可在框內打字、拖角縮放。Ctrl+C／V 複製貼上，Ctrl+Z 還原。")
        if tool != "text":
            self.clear_erase_text_selection()
        else:
            self.update_erase_preview_display()
        self.sync_erase_brush_cursor()

    def on_erase_size_changed(self, value: int) -> None:
        self.erase_size_label.setText(f"直徑 {value} pt")
        self.sync_erase_brush_cursor()

    def sync_erase_brush_cursor(self) -> None:
        image = self.erase_preview_image
        page_width, _page_height = self.erase_page_size
        if image is not None and page_width > 0:
            scale_x = image.width / page_width
            radius_px = self.erase_brush_radius() * scale_x
        else:
            radius_px = self.erase_brush_radius()
        self.erase_preview_label.brush_radius_px = max(radius_px, 4.0)
        red, green, blue = self.erase_color_rgb()
        self.erase_preview_label.cover_color = QColor(int(red * 255), int(green * 255), int(blue * 255))
        self.erase_preview_label.update()

    def render_erase_preview(self) -> None:
        if self.erase_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        if not PDF_RENDER_AVAILABLE or pdfium is None:
            self.set_status("PDF 預覽元件未啟用。")
            return
        try:
            page_number = min(max(int(self.erase_page_input.text() or "1"), 1), self.erase_page_count)
            self.erase_page_input.setText(str(page_number))
            document = pdfium.PdfDocument(
                str(self.erase_pdf_path),
                password=self.erase_password_input.text() or None,
            )
            page = document.get_page(page_number - 1)
            page_width, page_height = page.get_size()
            scale = self.advanced_preview_scale(page_width, page_height)
            image = page.render(scale=scale).to_pil().convert("RGB")
            page.close()
            document.close()
            self.erase_page_size = (float(page_width), float(page_height))
            self.erase_preview_image = image
            self.update_erase_preview_display()
            self.refresh_erase_list()
        except Exception as exc:
            self.show_error(exc)

    def erase_image_point_to_pdf(self, point: QPoint) -> tuple[float, float]:
        page_width, page_height = self.erase_page_size
        image = self.erase_preview_image
        if image is None or page_width <= 0 or page_height <= 0:
            return (0.0, 0.0)
        ix = min(max(point.x(), 0), image.width)
        iy = min(max(point.y(), 0), image.height)
        return (ix / image.width * page_width, page_height - (iy / image.height * page_height))

    def add_erase_stroke_point(self, point: QPoint) -> None:
        if self.erase_preview_image is None:
            self.set_status("請先載入 PDF。")
            return
        pdf_point = self.erase_image_point_to_pdf(point)
        radius = self.erase_brush_radius()
        if self._erase_live_points:
            last_x, last_y = self._erase_live_points[-1]
            gap = ((pdf_point[0] - last_x) ** 2 + (pdf_point[1] - last_y) ** 2) ** 0.5
            if gap < radius * 0.4:
                return
        self._erase_live_points.append(pdf_point)
        self.update_erase_preview_display()

    def finish_erase_stroke(self) -> None:
        if not self._erase_live_points:
            return
        self.erase_marks.append(
            EraseMark(
                page_index=self.current_erase_page_index(),
                kind="stroke",
                color_rgb=self.erase_color_rgb(),
                points=tuple(self._erase_live_points),
                radius=self.erase_brush_radius(),
            )
        )
        self._erase_undo_stack.append(("mark", self.current_erase_page_index()))
        self._erase_live_points = []
        self.refresh_erase_list()
        self.update_erase_preview_display()
        self.set_status(f"已加入橡皮刷，共 {len(self.erase_marks)} 筆標記。")

    def add_erase_rect(self, start: QPoint, end: QPoint) -> None:
        if self.erase_preview_image is None:
            self.set_status("請先載入 PDF。")
            return
        x0, y0 = self.erase_image_point_to_pdf(start)
        x1, y1 = self.erase_image_point_to_pdf(end)
        if abs(x1 - x0) < 4 or abs(y1 - y0) < 4:
            if self.erase_preview_label.tool == "text":
                self.add_erase_text_at_point(end)
            return
        if self.erase_preview_label.tool == "text":
            self._begin_new_erase_text_box()
            self.add_erase_text_box(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            return
        self.erase_marks.append(
            EraseMark(
                page_index=self.current_erase_page_index(),
                kind="rect",
                color_rgb=self.erase_color_rgb(),
                points=((x0, y0), (x1, y1)),
                radius=self.erase_brush_radius(),
            )
        )
        self._erase_undo_stack.append(("mark", self.current_erase_page_index()))
        self.refresh_erase_list()
        self.update_erase_preview_display()
        self.set_status(f"已加入長方形遮擋，共 {len(self.erase_marks)} 筆標記。")

    def erase_text_color_rgb(self) -> tuple[float, float, float]:
        preset = self.erase_text_color_combo.currentData() if hasattr(self, "erase_text_color_combo") else None
        if preset == "white":
            return (1.0, 1.0, 1.0)
        if preset in ANNOTATION_COLOR_PRESETS:
            return ANNOTATION_COLOR_PRESETS[preset]
        return self.erase_text_color_rgb_value

    def on_erase_text_color_changed(self) -> None:
        preset = self.erase_text_color_combo.currentData()
        if preset == "custom":
            self.choose_erase_text_color()
            return
        if preset == "white":
            self.erase_text_color_rgb_value = (1.0, 1.0, 1.0)
        elif preset in ANNOTATION_COLOR_PRESETS:
            self.erase_text_color_rgb_value = ANNOTATION_COLOR_PRESETS[preset]
        self.on_erase_text_style_changed()

    def choose_erase_text_color(self) -> None:
        current = QColor.fromRgbF(*self.erase_text_color_rgb_value)
        chosen = QColorDialog.getColor(current, self, "選擇文字顏色")
        if not chosen.isValid():
            return
        self.erase_text_color_rgb_value = (chosen.redF(), chosen.greenF(), chosen.blueF())
        custom_index = self.erase_text_color_combo.findData("custom")
        if custom_index >= 0:
            self.erase_text_color_combo.setCurrentIndex(custom_index)
        self.on_erase_text_style_changed()

    def erase_item_image_rect(self, item: dict) -> QRect:
        page_width, page_height = self.erase_page_size
        image = self.erase_preview_image
        if image is None or page_width <= 0 or page_height <= 0:
            return QRect()
        left = item["pdf_x"] / page_width * image.width
        top = (page_height - (item["pdf_y"] + item["rect_height"])) / page_height * image.height
        width = item["rect_width"] / page_width * image.width
        height = item["rect_height"] / page_height * image.height
        return QRect(int(round(left)), int(round(top)), max(int(round(width)), 1), max(int(round(height)), 1))

    def selected_erase_text_item(self) -> dict | None:
        index = self._erase_text_selected
        if index is None or index < 0 or index >= len(self.annotation_items):
            return None
        return self.annotation_items[index]

    def clear_erase_text_selection(self) -> None:
        self._erase_text_selected = None
        self._erase_resize_snapshot = None
        if hasattr(self, "erase_preview_label"):
            self.erase_preview_label.handles_enabled = False
            self.erase_preview_label.box_rect = QRect()
            self.erase_preview_label.hide_inline_editor()

    def _erase_text_hit_index(self, point: QPoint) -> int | None:
        page_index = self.current_erase_page_index()
        for index in range(len(self.annotation_items) - 1, -1, -1):
            item = self.annotation_items[index]
            if item.get("page_index") != page_index:
                continue
            if self.erase_item_image_rect(item).adjusted(-6, -6, 6, 6).contains(point):
                return index
        return None

    def select_erase_text_item(self, index: int, *, edit: bool = True) -> None:
        if index < 0 or index >= len(self.annotation_items):
            self.clear_erase_text_selection()
            return
        self._erase_text_selected = index
        item = self.annotation_items[index]
        self._erase_syncing_text = True
        try:
            self.erase_text_input.setPlainText(str(item.get("text") or ""))
            self.erase_text_size_combo.setCurrentText(str(int(item.get("font_size") or 18)))
            font_key = str(item.get("font_key") or "cjk")
            font_row = self.erase_text_font_combo.findData(font_key)
            if font_row >= 0:
                self.erase_text_font_combo.setCurrentIndex(font_row)
            self.erase_text_bold_checkbox.setChecked(bool(item.get("bold")))
        finally:
            self._erase_syncing_text = False
        self.update_erase_preview_display()
        if edit:
            self.erase_preview_label.pending_box_delete = False
            self.erase_preview_label.inline_edit.setFocus()
        else:
            arm_box_delete(self.erase_preview_label)

    def _erase_tab_active(self) -> bool:
        return (
            hasattr(self, "_erase_tab")
            and hasattr(self, "_advanced_tab")
            and self.main_tabs.currentWidget() is self._advanced_tab
            and self.advanced_tabs.currentWidget() is self._erase_tab
        )

    def _erase_text_tool_active(self) -> bool:
        return self._erase_tab_active() and getattr(self.erase_preview_label, "tool", "") == "text"

    def _begin_new_erase_text_box(self) -> None:
        if self._erase_text_selected is None:
            return
        self._erase_syncing_text = True
        try:
            self.erase_text_input.clear()
        finally:
            self._erase_syncing_text = False

    def add_erase_text_at_point(self, point: QPoint) -> None:
        if self.erase_preview_label.tool != "text":
            return
        self._erase_last_click = QPoint(point)
        hit = self._erase_text_hit_index(point)
        if hit is not None:
            box = self.erase_item_image_rect(self.annotation_items[hit])
            self.select_erase_text_item(hit, edit=not rect_chrome_contains(box, point))
            return
        self._begin_new_erase_text_box()
        font_size = combo_font_size(self.erase_text_size_combo, 18)
        width, height = self.measure_annotation_text_box("文字", font_size, False, "cjk", 180.0)
        pdf_x, pdf_y_top = self.erase_image_point_to_pdf(point)
        self.add_erase_text_box(pdf_x, pdf_y_top - height, width, height)
        self._erase_last_click = None

    def add_erase_text_box(self, pdf_x: float, pdf_y: float, width: float, height: float) -> None:
        text = self.erase_text_input.toPlainText()
        font_size = combo_font_size(self.erase_text_size_combo, 18)
        font_key = self.erase_text_font_combo.currentData() or "cjk"
        bold = self.erase_text_bold_checkbox.isChecked()
        if text.strip():
            fitted_width, fitted_height = self.measure_annotation_text_box(
                text, font_size, bold, font_key, max(width, 80.0)
            )
            width = max(width, fitted_width)
            height = max(height, fitted_height)
        else:
            width = max(width, 160.0)
            height = max(height, font_size * 1.8, 32.0)
        self._erase_text_seq += 1
        item = {
            "text": text,
            "cover": False,
            "font_key": font_key,
            "font_size": font_size,
            "bold": bold,
            "color_rgb": self.erase_text_color_rgb(),
            "fill_rgb": (1.0, 1.0, 1.0),
            "fill_none": False,
            "pdf_x": pdf_x,
            "pdf_y": pdf_y,
            "rect_width": width,
            "rect_height": height,
            "shape": "rect",
            "pointer_x": pdf_x + width / 2.0,
            "pointer_y": pdf_y - 16.0,
            "page_index": self.current_erase_page_index(),
            "_uid": self._erase_text_seq,
        }
        self.annotation_items.append(item)
        self._erase_undo_stack.append(("text", item["page_index"], item["_uid"]))
        self.refresh_annotation_item_list()
        self.select_erase_text_item(len(self.annotation_items) - 1)
        self.refresh_erase_list()
        self.set_status("已放置文字方塊。可直接打字、拖角縮放，或 Ctrl+C／V 複製到其他位置。")

    def on_erase_inline_text_edited(self, text: str) -> None:
        item = self.selected_erase_text_item()
        if item is None or self._erase_syncing_text:
            return
        item["text"] = text
        self._erase_syncing_text = True
        try:
            if self.erase_text_input.toPlainText() != text:
                self.erase_text_input.setPlainText(text)
        finally:
            self._erase_syncing_text = False
        self.refresh_erase_list()

    def on_erase_sidebar_text_changed(self) -> None:
        if self._erase_syncing_text:
            return
        item = self.selected_erase_text_item()
        if item is None:
            return
        text = self.erase_text_input.toPlainText()
        item["text"] = text
        editor = self.erase_preview_label.inline_edit
        if editor.toPlainText() != text:
            editor.blockSignals(True)
            editor.setPlainText(text)
            editor.blockSignals(False)
        self.refresh_erase_list()

    def on_erase_text_style_changed(self, *_args) -> None:
        if self._erase_syncing_text:
            return
        item = self.selected_erase_text_item()
        if item is None:
            return
        item["font_size"] = combo_font_size(self.erase_text_size_combo, 18)
        item["font_key"] = self.erase_text_font_combo.currentData() or "cjk"
        item["bold"] = self.erase_text_bold_checkbox.isChecked()
        item["color_rgb"] = self.erase_text_color_rgb()
        self.update_erase_preview_display()

    def _erase_image_delta_to_pdf(self, start: QPoint, current: QPoint) -> tuple[float, float]:
        page_width, page_height = self.erase_page_size
        image = self.erase_preview_image
        if image is None or page_width <= 0 or page_height <= 0:
            return (0.0, 0.0)
        dx = (current.x() - start.x()) / image.width * page_width
        dy = -((current.y() - start.y()) / image.height * page_height)
        return dx, dy

    def resize_erase_text_box_from_handle(self, handle: str, start: QPoint, current: QPoint) -> None:
        item = self.selected_erase_text_item()
        if item is None:
            return
        if self._erase_resize_snapshot is None:
            self._erase_resize_snapshot = (
                item["pdf_x"],
                item["pdf_y"],
                item["rect_width"],
                item["rect_height"],
            )
            self._erase_undo_stack.append(("text_edit", item.get("page_index", 0), item.get("_uid"), dict(item)))
        pdf_x, pdf_y, width, height = self._erase_resize_snapshot
        dx, dy = self._erase_image_delta_to_pdf(start, current)
        if "e" in handle:
            width += dx
        if "w" in handle:
            pdf_x += dx
            width -= dx
        if "n" in handle:
            height += dy
        if "s" in handle:
            pdf_y += dy
            height -= dy
        item["pdf_x"] = pdf_x
        item["pdf_y"] = pdf_y
        item["rect_width"] = max(width, 80.0)
        item["rect_height"] = max(height, 28.0)
        self.update_erase_preview_display()

    def move_erase_text_box(self, start: QPoint, current: QPoint) -> None:
        item = self.selected_erase_text_item()
        if item is None:
            return
        if self._erase_resize_snapshot is None:
            self._erase_resize_snapshot = (
                item["pdf_x"],
                item["pdf_y"],
                item["rect_width"],
                item["rect_height"],
            )
            self._erase_undo_stack.append(("text_edit", item.get("page_index", 0), item.get("_uid"), dict(item)))
        pdf_x, pdf_y, width, height = self._erase_resize_snapshot
        dx, dy = self._erase_image_delta_to_pdf(start, current)
        item["pdf_x"] = pdf_x + dx
        item["pdf_y"] = pdf_y + dy
        item["rect_width"] = width
        item["rect_height"] = height
        self.update_erase_preview_display()

    def finish_erase_text_box_interaction(self) -> None:
        self._erase_resize_snapshot = None
        self.update_erase_preview_display()
        self.set_status("已調整文字方塊。")

    def copy_erase_text_box(self) -> None:
        item = self.selected_erase_text_item()
        if item is None:
            return
        self._erase_text_clipboard = dict(item)
        QApplication.clipboard().setText(str(item.get("text") or ""))
        self.set_status("已複製文字方塊。到其他位置按 Ctrl+V 貼上。")

    def paste_erase_text_box(self) -> None:
        if self.erase_preview_label.tool != "text" or self._erase_text_clipboard is None:
            return
        source = dict(self._erase_text_clipboard)
        if self._erase_last_click is not None:
            pdf_x, pdf_y_top = self.erase_image_point_to_pdf(self._erase_last_click)
            pdf_y = pdf_y_top - float(source.get("rect_height") or 32)
        else:
            pdf_x = float(source.get("pdf_x") or 72) + 16
            pdf_y = float(source.get("pdf_y") or 200) - 16
        self.erase_text_input.blockSignals(True)
        self.erase_text_input.setPlainText(str(source.get("text") or ""))
        self.erase_text_input.blockSignals(False)
        if source.get("font_size"):
            self.erase_text_size_combo.setCurrentText(str(int(source["font_size"])))
        self.add_erase_text_box(pdf_x, pdf_y, float(source.get("rect_width") or 180), float(source.get("rect_height") or 32))
        pasted = self.selected_erase_text_item()
        if pasted is not None:
            pasted["text"] = source.get("text") or ""
            pasted["font_key"] = source.get("font_key") or pasted["font_key"]
            pasted["font_size"] = source.get("font_size") or pasted["font_size"]
            pasted["bold"] = bool(source.get("bold"))
            pasted["color_rgb"] = source.get("color_rgb") or pasted["color_rgb"]
            pasted["fill_rgb"] = source.get("fill_rgb") or pasted.get("fill_rgb")
        self.select_erase_text_item(self._erase_text_selected or 0)
        self._erase_last_click = None
        self.set_status("已貼上文字方塊。")

    def undo_erase_mark(self) -> None:
        page_index = self.current_erase_page_index()
        for stack_index in range(len(self._erase_undo_stack) - 1, -1, -1):
            action = self._erase_undo_stack[stack_index]
            if action[1] != page_index:
                continue
            self._erase_undo_stack.pop(stack_index)
            kind = action[0]
            if kind == "mark":
                for index in range(len(self.erase_marks) - 1, -1, -1):
                    if self.erase_marks[index].page_index == page_index:
                        self.erase_marks.pop(index)
                        break
                self.set_status("已復原上一筆標記。")
            elif kind == "text":
                uid = action[2]
                self.annotation_items = [item for item in self.annotation_items if item.get("_uid") != uid]
                self.clear_erase_text_selection()
                self.set_status("已復原文字方塊。")
            elif kind == "text_edit":
                uid = action[2]
                before = action[3]
                restored_index = None
                for index, item in enumerate(self.annotation_items):
                    if item.get("_uid") == uid:
                        item.clear()
                        item.update(before)
                        restored_index = index
                        break
                if restored_index is not None:
                    self._erase_text_selected = restored_index
                self.set_status("已還原文字方塊調整。")
            elif kind == "text_restore":
                item = dict(action[2])
                index = min(int(action[3]), len(self.annotation_items))
                self.annotation_items.insert(index, item)
                self._erase_text_selected = index
                self.set_status("已還原文字方塊。")
            self.refresh_erase_list()
            self.refresh_annotation_item_list()
            self.update_erase_preview_display()
            return
        self.set_status("本頁沒有可復原的標記。")

    def clear_erase_marks_on_page(self) -> None:
        page_index = self.current_erase_page_index()
        before_marks = len(self.erase_marks)
        self.erase_marks = [mark for mark in self.erase_marks if mark.page_index != page_index]
        before_text = len(self.annotation_items)
        self.annotation_items = [item for item in self.annotation_items if item.get("page_index") != page_index]
        self._erase_live_points = []
        self.clear_erase_text_selection()
        self.refresh_erase_list()
        self.refresh_annotation_item_list()
        self.update_erase_preview_display()
        removed = (before_marks - len(self.erase_marks)) + (before_text - len(self.annotation_items))
        self.set_status(f"已清除本頁 {removed} 筆標記。")

    def delete_current_erase_item(self) -> None:
        if self._erase_text_selected is not None and 0 <= self._erase_text_selected < len(self.annotation_items):
            item = self.annotation_items[self._erase_text_selected]
            self._erase_undo_stack.append(("text_restore", item.get("page_index", 0), dict(item), self._erase_text_selected))
            self.annotation_items.pop(self._erase_text_selected)
            self.clear_erase_text_selection()
            self.refresh_erase_list()
            self.refresh_annotation_item_list()
            self.update_erase_preview_display()
            self._clear_box_delete_arm()
            self.set_status("已刪除文字方塊。")
            return
        page_index = self.current_erase_page_index()
        for index in range(len(self.erase_marks) - 1, -1, -1):
            if self.erase_marks[index].page_index == page_index:
                self._erase_undo_stack.append(("mark", page_index))
                self.erase_marks.pop(index)
                self.refresh_erase_list()
                self.update_erase_preview_display()
                self.set_status("已刪除標記。")
                return
        self.set_status("目前沒有可刪除的橡皮擦標記或文字方塊。")

    def refresh_erase_list(self) -> None:
        self.erase_mark_list.clear()
        page_index = self.current_erase_page_index()
        for mark in self.erase_marks:
            if mark.page_index != page_index:
                continue
            color_name = "黑" if mark.color_rgb[0] < 0.5 else "白"
            if mark.kind == "rect":
                label = f"長方形（{color_name}）"
            else:
                label = f"橡皮刷 {len(mark.points)} 點／{int(mark.radius * 2)} pt（{color_name}）"
            self.erase_mark_list.addItem(label)
        for item in self.annotation_items:
            if item.get("page_index") != page_index:
                continue
            preview = str(item.get("text") or "").replace("\n", " ")
            if len(preview) > 16:
                preview = f"{preview[:16]}…"
            self.erase_mark_list.addItem(f"文字方塊：{preview}")

    def update_erase_preview_display(self) -> None:
        if self.erase_preview_image is None:
            self.erase_preview_label.clear()
            self.erase_preview_label.hide_inline_editor()
            return
        page_width, page_height = self.erase_page_size
        canvas = self.erase_preview_image.copy()
        if page_width <= 0 or page_height <= 0:
            self.erase_preview_label.set_preview_pixmap(QPixmap.fromImage(ImageQt(canvas)))
            self.erase_preview_label.hide_inline_editor()
            return
        draw = ImageDraw.Draw(canvas)
        scale_x = canvas.width / page_width
        scale_y = canvas.height / page_height

        def paint_mark(mark: EraseMark) -> None:
            fill = tuple(int(channel * 255) for channel in mark.color_rgb)
            if mark.kind == "rect" and len(mark.points) >= 2:
                (x0, y0), (x1, y1) = mark.points[0], mark.points[1]
                left = min(x0, x1) * scale_x
                right = max(x0, x1) * scale_x
                top = canvas.height - max(y0, y1) * scale_y
                bottom = canvas.height - min(y0, y1) * scale_y
                draw.rectangle((left, top, right, bottom), fill=fill)
                return
            radius = max(mark.radius * scale_x, 2.0)
            for pdf_x, pdf_y in mark.points:
                cx = pdf_x * scale_x
                cy = canvas.height - pdf_y * scale_y
                draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=fill)

        page_index = self.current_erase_page_index()
        for mark in self.erase_marks:
            if mark.page_index == page_index:
                paint_mark(mark)
        if self._erase_live_points:
            paint_mark(
                EraseMark(
                    page_index=page_index,
                    kind="stroke",
                    color_rgb=self.erase_color_rgb(),
                    points=tuple(self._erase_live_points),
                    radius=self.erase_brush_radius(),
                )
            )
        page_index = self.current_erase_page_index()
        selected = self.selected_erase_text_item()
        for index, item in enumerate(self.annotation_items):
            if item.get("page_index") != page_index:
                continue
            draw_item = dict(item)
            if selected is item and self.erase_preview_label.tool == "text":
                draw_item["text"] = ""
            canvas = self.draw_annotation_overlay_on_image(canvas.convert("RGB"), draw_item, self.erase_page_size)
        self.erase_preview_label.set_preview_pixmap(QPixmap.fromImage(ImageQt(canvas.convert("RGB"))))
        if selected is not None and self.erase_preview_label.tool == "text":
            box = self.erase_item_image_rect(selected)
            self.erase_preview_label.box_rect = box
            self.erase_preview_label.handles_enabled = True
            interacting = self.erase_preview_label._mode in ("resize", "move") or self._erase_resize_snapshot is not None
            if interacting:
                self.erase_preview_label.hide_inline_editor()
            else:
                self.erase_preview_label.show_inline_editor(
                    box,
                    str(selected.get("text") or ""),
                    int(selected.get("font_size") or 18),
                    bold=bool(selected.get("bold")),
                    color_rgb=tuple(selected.get("color_rgb") or (0.0, 0.0, 0.0)),
                )
        else:
            self.erase_preview_label.handles_enabled = False
            self.erase_preview_label.box_rect = QRect()
            self.erase_preview_label.hide_inline_editor()
        self.sync_erase_brush_cursor()

    def paint_erase_marks_on_image(
        self,
        image: Image.Image,
        page_size: tuple[float, float],
        page_index: int,
    ) -> Image.Image:
        page_width, page_height = page_size
        if page_width <= 0 or page_height <= 0 or not self.erase_marks:
            return image
        canvas = image.copy()
        draw = ImageDraw.Draw(canvas)
        scale_x = canvas.width / page_width
        scale_y = canvas.height / page_height
        for mark in self.erase_marks:
            if mark.page_index != page_index:
                continue
            fill = tuple(int(channel * 255) for channel in mark.color_rgb)
            if mark.kind == "rect" and len(mark.points) >= 2:
                (x0, y0), (x1, y1) = mark.points[0], mark.points[1]
                left = min(x0, x1) * scale_x
                right = max(x0, x1) * scale_x
                top = canvas.height - max(y0, y1) * scale_y
                bottom = canvas.height - min(y0, y1) * scale_y
                draw.rectangle((left, top, right, bottom), fill=fill)
                continue
            radius = max(mark.radius * scale_x, 2.0)
            for pdf_x, pdf_y in mark.points:
                cx = pdf_x * scale_x
                cy = canvas.height - pdf_y * scale_y
                draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=fill)
        return canvas.convert("RGB")

    def save_erase_pdf(self) -> None:
        if self.erase_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        overlays = [item for item in self.annotation_items if str(item.get("text") or "").strip()]
        if not self.erase_marks and not overlays:
            self.set_status("請先用橡皮刷遮擋，或加入文字方塊。")
            return
        target, _ = QFileDialog.getSaveFileName(self, "另存橡皮擦 PDF", "erased.pdf", "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)
        marks = list(self.erase_marks)
        remove_content = self.erase_remove_content_checkbox.isChecked()
        applied = {"value": 0}

        def job() -> None:
            applied["value"] = apply_erase_then_text_overlays(
                self.erase_pdf_path,
                target_path,
                marks,
                overlays,
                self.erase_password_input.text(),
                remove_content,
            )

        def after_save() -> None:
            self.erase_marks = []
            self.annotation_items = []
            self.clear_erase_text_selection()
            self.refresh_erase_list()
            self.refresh_annotation_item_list()
            self.update_erase_preview_display()
            self.open_pdf_as_new_tab(target_path)
            extra = f"，並加入 {len(overlays)} 個文字方塊" if overlays else ""
            self.set_status(f"已套用橡皮擦／遮擋{extra}並另存：{target_path.name}")

        self.run_pdf_job(job, "", on_success=after_save)

    def build_text_edit_tab(self) -> QWidget:
        tab = PdfDropPanel()
        tab.filesDropped.connect(self.drop_text_edit_pdf)
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        left = QVBoxLayout()
        top = QHBoxLayout()
        self.add_button(top, "載入 PDF", self.load_text_edit_pdf)
        top.addWidget(QLabel("頁碼"))
        self.text_edit_page_input = QLineEdit("1")
        self.text_edit_page_input.setFixedWidth(56)
        self.text_edit_page_validator = QIntValidator(1, 1, self)
        self.text_edit_page_input.setValidator(self.text_edit_page_validator)
        self.text_edit_page_input.editingFinished.connect(self.on_advanced_page_input_edited)
        top.addWidget(self.text_edit_page_input)
        self.add_button(top, "上一頁", lambda: self.change_text_edit_page(-1))
        self.add_button(top, "下一頁", lambda: self.change_text_edit_page(1))
        self.add_button(top, "偵測文字", self.refresh_text_edit_page)
        top.addStretch(1)
        left.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.text_edit_preview_label = TextEditPreviewLabel()
        self.text_edit_preview_label.positionClicked.connect(self.select_text_edit_block_at_point)
        self.text_edit_preview_label.inlineEdited.connect(self.on_text_edit_inline_edited)
        scroll.setWidget(self.text_edit_preview_label)
        left.addWidget(scroll, 1)
        layout.addLayout(left, 1)

        side = QFrame()
        side.setObjectName("panel")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

        side_layout.addWidget(QLabel("搜尋文字"))
        search_row = QHBoxLayout()
        self.text_edit_search_input = QLineEdit()
        self.text_edit_search_input.setPlaceholderText("輸入要尋找的文字")
        self.text_edit_search_input.returnPressed.connect(self.find_next_text_edit_block)
        self.text_edit_search_input.textChanged.connect(lambda _text: self.update_text_edit_search_feedback())
        search_row.addWidget(self.text_edit_search_input, 1)
        self.add_button(search_row, "上一個", self.find_previous_text_edit_block)
        self.add_button(search_row, "下一個", self.find_next_text_edit_block)
        self.add_button(search_row, "清除", self.clear_text_edit_search)
        side_layout.addLayout(search_row)
        search_options_row = QHBoxLayout()
        self.text_edit_case_sensitive_checkbox = QCheckBox("區分大小寫")
        self.text_edit_case_sensitive_checkbox.toggled.connect(
            lambda _checked: self.update_text_edit_search_feedback()
        )
        search_options_row.addWidget(self.text_edit_case_sensitive_checkbox)
        self.text_edit_whole_word_checkbox = QCheckBox("全字匹配")
        self.text_edit_whole_word_checkbox.toggled.connect(
            lambda _checked: self.update_text_edit_search_feedback()
        )
        search_options_row.addWidget(self.text_edit_whole_word_checkbox)
        search_options_row.addStretch(1)
        side_layout.addLayout(search_options_row)

        self.text_edit_search_feedback = QLabel("輸入搜尋文字後會顯示目前頁符合數。")
        self.text_edit_search_feedback.setObjectName("muted")
        self.text_edit_search_feedback.setWordWrap(True)
        side_layout.addWidget(self.text_edit_search_feedback)
        count_all_button = self.add_button(side_layout, "計算整份文件符合數", self.count_all_text_search_matches)
        count_all_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        side_layout.addWidget(QLabel("偵測到的文字片段"))
        self.text_edit_block_list = QListWidget()
        self.text_edit_block_list.setMinimumHeight(100)
        self.text_edit_block_list.setMaximumHeight(180)
        self.text_edit_block_list.currentRowChanged.connect(self.on_text_edit_block_selected)
        side_layout.addWidget(self.text_edit_block_list)

        self.text_edit_block_info = QLabel("選取文字片段後可替換。")
        self.text_edit_block_info.setObjectName("muted")
        self.text_edit_block_info.setWordWrap(True)
        side_layout.addWidget(self.text_edit_block_info)

        side_layout.addWidget(QLabel("替換成"))
        self.text_edit_replacement_input = QTextEdit()
        self.text_edit_replacement_input.setFixedHeight(80)
        self.text_edit_replacement_input.textChanged.connect(
            lambda: self.update_text_edit_preview(self.current_text_edit_block())
        )
        self.text_edit_replacement_input.textChanged.connect(self.update_text_edit_replacement_hint)
        side_layout.addWidget(self.text_edit_replacement_input)

        side_layout.addWidget(QLabel("替換方式"))
        self.text_edit_mode_combo = QComboBox()
        self.text_edit_mode_combo.addItem("無痕替換（保留原字型，推薦）", "seamless")
        self.text_edit_mode_combo.addItem("覆蓋替換（白底覆蓋）", "overlay")
        self.text_edit_mode_combo.addItem("直接改內容流（實驗：英文/數字同長度）", "content_stream")
        self.text_edit_mode_combo.currentIndexChanged.connect(
            lambda _index: self.update_text_edit_replacement_hint()
        )
        side_layout.addWidget(self.text_edit_mode_combo)

        self.text_edit_replacement_hint = QLabel("選取文字片段後會顯示替換限制。")
        self.text_edit_replacement_hint.setObjectName("muted")
        self.text_edit_replacement_hint.setWordWrap(True)
        side_layout.addWidget(self.text_edit_replacement_hint)

        side_layout.addWidget(QLabel("遮蔽方式"))
        self.text_edit_redaction_mode_combo = QComboBox()
        self.text_edit_redaction_mode_combo.addItem("視覺遮蔽（黑框覆蓋）", "visual")
        self.text_edit_redaction_mode_combo.addItem("安全遮蔽（實驗：移除簡單文字）", "secure")
        side_layout.addWidget(self.text_edit_redaction_mode_combo)

        side_layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.text_edit_password_input = QLineEdit()
        self.text_edit_password_input.setEchoMode(QLineEdit.Password)
        side_layout.addWidget(self.text_edit_password_input)

        save_button = self.add_button(side_layout, "替換並另存 PDF", self.save_text_edit_pdf, "primary")
        save_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        redact_button = self.add_button(side_layout, "遮蔽選取文字並另存", self.redact_text_edit_pdf)
        redact_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        redact_all_button = self.add_button(side_layout, "遮蔽全部搜尋結果並另存", self.redact_all_text_search_matches)
        redact_all_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        guide = QLabel(
            "點預覽上的文字即可直接改，像 Adobe Acrobat；左邊會即時顯示替換效果。"
            "預設「無痕替換」會先移除原文字再寫回。中文請不要用「直接改內容流」。"
            "掃描件請先 OCR，或改用橡皮擦。"
        )
        guide.setObjectName("muted")
        guide.setWordWrap(True)
        side_layout.addWidget(guide)
        layout.addWidget(wrap_side_panel(side, 360))
        return tab

    def build_bookmark_tab(self) -> QWidget:
        tab = PdfDropPanel()
        tab.filesDropped.connect(self.drop_bookmark_pdf)
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        left = QVBoxLayout()
        top = QHBoxLayout()
        self.add_button(top, "載入 PDF", self.load_bookmark_pdf)
        self.add_button(top, "重新讀取原始書籤", self.reload_bookmarks)
        top.addStretch(1)
        left.addLayout(top)

        left.addWidget(QLabel("書籤 / 目錄結構"))
        self.bookmark_list = QListWidget()
        self.bookmark_list.currentRowChanged.connect(self.on_bookmark_selected)
        left.addWidget(self.bookmark_list, 1)

        self.bookmark_status_label = QLabel("載入 PDF 後可檢視、編輯並重建書籤。")
        self.bookmark_status_label.setObjectName("muted")
        self.bookmark_status_label.setWordWrap(True)
        left.addWidget(self.bookmark_status_label)
        layout.addLayout(left, 1)

        side = QFrame()
        side.setObjectName("panel")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

        side_layout.addWidget(QLabel("書籤標題"))
        self.bookmark_title_input = QLineEdit()
        self.bookmark_title_input.setPlaceholderText("例如：第一章 簡介")
        side_layout.addWidget(self.bookmark_title_input)

        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("目標頁碼"))
        self.bookmark_page_input = QLineEdit("1")
        self.bookmark_page_input.setFixedWidth(64)
        self.bookmark_page_validator = QIntValidator(1, 1, self)
        self.bookmark_page_input.setValidator(self.bookmark_page_validator)
        page_row.addWidget(self.bookmark_page_input)
        page_row.addStretch(1)
        side_layout.addLayout(page_row)

        side_layout.addWidget(QLabel("階層"))
        self.bookmark_level_combo = QComboBox()
        self.bookmark_level_combo.addItem("主層", 0)
        self.bookmark_level_combo.addItem("子層", 1)
        self.bookmark_level_combo.addItem("次子層", 2)
        side_layout.addWidget(self.bookmark_level_combo)

        self.add_button(side_layout, "新增書籤", self.add_bookmark_item)
        self.add_button(side_layout, "更新選取書籤", self.update_selected_bookmark)
        self.add_button(side_layout, "刪除選取書籤", self.delete_selected_bookmark, "danger")

        move_row = QHBoxLayout()
        self.add_button(move_row, "上移", lambda: self.move_bookmark_item(-1))
        self.add_button(move_row, "下移", lambda: self.move_bookmark_item(1))
        self.add_button(move_row, "升階", lambda: self.indent_bookmark_item(-1))
        self.add_button(move_row, "降階", lambda: self.indent_bookmark_item(1))
        side_layout.addLayout(move_row)

        self.add_button(side_layout, "清空全部書籤", self.clear_bookmarks, "danger")

        side_layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.bookmark_password_input = QLineEdit()
        self.bookmark_password_input.setEchoMode(QLineEdit.Password)
        side_layout.addWidget(self.bookmark_password_input)

        save_button = self.add_button(side_layout, "套用書籤並另存 PDF", self.save_bookmark_pdf, "primary")
        save_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        guide = QLabel(
            "可讀取現有 PDF 書籤、新增/編輯/排序，並用階層建立巢狀目錄。套用後會以新書籤重建並另存新檔。"
        )
        guide.setObjectName("muted")
        guide.setWordWrap(True)
        side_layout.addWidget(guide)
        side_layout.addStretch(1)
        layout.addWidget(wrap_side_panel(side, 320))
        return tab

    def load_bookmark_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "載入 PDF", "", "PDF files (*.pdf)")
        if path:
            self.load_advanced_pdf_from_path(Path(path), self.bookmark_password_input.text())

    def drop_bookmark_pdf(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() in PDF_SUFFIXES]
        if not pdf_paths:
            self.set_status("請拖放 PDF 檔案到書籤分頁。")
            return
        self.load_advanced_pdf_from_path(pdf_paths[0], self.bookmark_password_input.text())

    def set_bookmark_pdf(self, path: Path) -> None:
        try:
            reader = open_reader(path, self.bookmark_password_input.text())
            self.bookmark_page_count = len(reader.pages)
            self.bookmark_items = extract_outline(path, self.bookmark_password_input.text())
        except Exception as exc:
            self.show_error(exc)
            return
        self.bookmark_pdf_path = path
        self.bookmark_page_validator.setRange(1, max(self.bookmark_page_count, 1))
        self.refresh_bookmark_list()
        self.set_status(f"已載入 {path.name}，共 {len(self.bookmark_items)} 個書籤。")

    def reload_bookmarks(self) -> None:
        if self.bookmark_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        try:
            self.bookmark_items = extract_outline(
                self.bookmark_pdf_path, self.bookmark_password_input.text()
            )
        except Exception as exc:
            self.show_error(exc)
            return
        self.refresh_bookmark_list()
        self.set_status(f"已重新讀取原始書籤，共 {len(self.bookmark_items)} 個。")

    def refresh_bookmark_list(self) -> None:
        self.bookmark_list.blockSignals(True)
        self.bookmark_list.clear()
        for item in self.bookmark_items:
            prefix = "　" * item.level
            label = f"{prefix}{item.title}  (p.{item.page_index + 1})"
            list_item = QListWidgetItem(label)
            self.bookmark_list.addItem(list_item)
        self.bookmark_list.blockSignals(False)
        if not self.bookmark_items:
            self.bookmark_status_label.setText("目前沒有書籤。可新增書籤或載入含書籤的 PDF。")
        else:
            self.bookmark_status_label.setText(f"共 {len(self.bookmark_items)} 個書籤。")

    def on_bookmark_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.bookmark_items):
            return
        item = self.bookmark_items[row]
        self.bookmark_title_input.setText(item.title)
        self.bookmark_page_input.setText(str(item.page_index + 1))
        self.bookmark_level_combo.setCurrentIndex(min(item.level, self.bookmark_level_combo.count() - 1))

    def bookmark_inputs(self) -> BookmarkItem | None:
        title = self.bookmark_title_input.text().strip()
        if not title:
            self.set_status("請先輸入書籤標題。")
            return None
        page_index = int(self.bookmark_page_input.text() or "1") - 1
        if self.bookmark_page_count:
            page_index = max(0, min(page_index, self.bookmark_page_count - 1))
        level = self.bookmark_level_combo.currentData() or 0
        return BookmarkItem(title, page_index, int(level))

    def add_bookmark_item(self) -> None:
        new_item = self.bookmark_inputs()
        if new_item is None:
            return
        row = self.bookmark_list.currentRow()
        insert_at = row + 1 if 0 <= row < len(self.bookmark_items) else len(self.bookmark_items)
        self.bookmark_items.insert(insert_at, new_item)
        self.refresh_bookmark_list()
        self.bookmark_list.setCurrentRow(insert_at)
        self.set_status(f"已新增書籤：{new_item.title}")

    def update_selected_bookmark(self) -> None:
        row = self.bookmark_list.currentRow()
        if not (0 <= row < len(self.bookmark_items)):
            self.set_status("請先選取要更新的書籤。")
            return
        new_item = self.bookmark_inputs()
        if new_item is None:
            return
        self.bookmark_items[row] = new_item
        self.refresh_bookmark_list()
        self.bookmark_list.setCurrentRow(row)
        self.set_status(f"已更新書籤：{new_item.title}")

    def delete_selected_bookmark(self) -> None:
        row = self.bookmark_list.currentRow()
        if not (0 <= row < len(self.bookmark_items)):
            self.set_status("請先選取要刪除的書籤。")
            return
        removed = self.bookmark_items.pop(row)
        self.refresh_bookmark_list()
        self.bookmark_list.setCurrentRow(min(row, len(self.bookmark_items) - 1))
        self.set_status(f"已刪除書籤：{removed.title}")

    def move_bookmark_item(self, direction: int) -> None:
        row = self.bookmark_list.currentRow()
        target = row + direction
        if not (0 <= row < len(self.bookmark_items)) or not (0 <= target < len(self.bookmark_items)):
            return
        self.bookmark_items[row], self.bookmark_items[target] = (
            self.bookmark_items[target],
            self.bookmark_items[row],
        )
        self.refresh_bookmark_list()
        self.bookmark_list.setCurrentRow(target)

    def indent_bookmark_item(self, delta: int) -> None:
        row = self.bookmark_list.currentRow()
        if not (0 <= row < len(self.bookmark_items)):
            return
        item = self.bookmark_items[row]
        new_level = max(0, item.level + delta)
        self.bookmark_items[row] = BookmarkItem(item.title, item.page_index, new_level)
        self.refresh_bookmark_list()
        self.bookmark_list.setCurrentRow(row)

    def clear_bookmarks(self) -> None:
        if not self.bookmark_items:
            return
        self.bookmark_items = []
        self.refresh_bookmark_list()
        self.set_status("已清空全部書籤。")

    def save_bookmark_pdf(self) -> None:
        if self.bookmark_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        target, _ = QFileDialog.getSaveFileName(self, "另存書籤 PDF", "bookmarked.pdf", "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)
        items = list(self.bookmark_items)
        self.run_pdf_job(
            lambda: apply_outline(
                self.bookmark_pdf_path,
                target_path,
                items,
                self.bookmark_password_input.text(),
            ),
            f"已套用 {len(items)} 個書籤並另存：{target_path.name}",
            on_success=lambda: self.open_pdf_as_new_tab(target_path),
        )

    def load_text_edit_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "載入 PDF", "", "PDF files (*.pdf)")
        if path:
            self.load_advanced_pdf_from_path(Path(path), self.text_edit_password_input.text())

    def drop_text_edit_pdf(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() in PDF_SUFFIXES]
        if not pdf_paths:
            self.set_status("請拖放 PDF 檔案到文字編輯分頁。")
            return
        self.load_advanced_pdf_from_path(pdf_paths[0], self.text_edit_password_input.text())

    def set_text_edit_pdf(self, path: Path) -> None:
        try:
            reader = open_reader(path, self.text_edit_password_input.text())
        except Exception as exc:
            self.show_error(exc)
            return
        self.text_edit_pdf_path = path
        self.text_edit_page_count = len(reader.pages)
        self.text_edit_page_validator.setRange(1, max(self.text_edit_page_count, 1))
        self.text_edit_page_input.setText("1")
        self.refresh_text_edit_page()
        self.set_status(f"已載入文字編輯 PDF：{path.name}")

    def change_text_edit_page(self, delta: int) -> None:
        if self.text_edit_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        current = min(max(int(self.text_edit_page_input.text() or "1"), 1), self.text_edit_page_count)
        next_page = min(max(current + delta, 1), self.text_edit_page_count)
        if next_page == current:
            boundary = "第一頁" if delta < 0 else "最後一頁"
            self.set_status(f"已在{boundary}。")
            return
        self.set_advanced_page(next_page - 1)

    def refresh_text_edit_page(self) -> None:
        if self.text_edit_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        page_number = min(max(int(self.text_edit_page_input.text() or "1"), 1), self.text_edit_page_count)
        self.text_edit_page_input.setText(str(page_number))
        try:
            self.text_edit_blocks = extract_page_text_blocks(
                self.text_edit_pdf_path,
                page_number - 1,
                self.text_edit_password_input.text(),
            )
            self.render_text_edit_preview()
            self.refresh_text_edit_blocks()
        except Exception as exc:
            self.show_error(exc)

    def refresh_text_edit_blocks(self) -> None:
        self.text_edit_block_list.clear()
        for block in self.text_edit_blocks:
            label = block.text.replace("\n", " ")
            if len(label) > 80:
                label = f"{label[:77]}..."
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, block)
            self.text_edit_block_list.addItem(item)
        if not self.text_edit_blocks:
            self.text_edit_block_info.setText(
                "此頁沒有偵測到可編輯文字層。掃描件或投影片轉成的圖片 PDF 請先 OCR，"
                "或改用「橡皮擦 / 遮擋」蓋掉畫面。"
            )
        self.update_text_edit_search_feedback()

    def find_next_text_edit_block(self) -> None:
        self.find_text_edit_block(direction=1)

    def find_previous_text_edit_block(self) -> None:
        self.find_text_edit_block(direction=-1)

    def clear_text_edit_search(self) -> None:
        if not self.text_edit_search_input.text():
            self.set_status("搜尋文字已清空。")
            return
        self.text_edit_search_input.clear()
        self.update_text_edit_preview(self.current_text_edit_block())
        self.set_status("已清除搜尋文字與預覽高亮。")

    def update_text_edit_search_feedback(self) -> None:
        query = self.text_edit_search_input.text().strip()
        if not query:
            self.text_edit_search_feedback.setText("輸入搜尋文字後會顯示目前頁符合數。")
        else:
            match_count = sum(1 for block in self.text_edit_blocks if self.text_edit_block_matches_query(block, query))
            self.text_edit_search_feedback.setText(f"目前頁符合：{match_count} 個文字片段。")
        self.update_text_edit_preview(self.current_text_edit_block())

    def count_all_text_search_matches(self) -> None:
        if self.text_edit_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        query = self.text_edit_search_input.text().strip()
        if not query:
            self.set_status("請先輸入要計算的搜尋文字。")
            return

        try:
            total = 0
            for page_index in range(self.text_edit_page_count):
                if page_index == int(self.text_edit_page_input.text() or "1") - 1:
                    blocks = self.text_edit_blocks
                else:
                    blocks = extract_page_text_blocks(
                        self.text_edit_pdf_path,
                        page_index,
                        self.text_edit_password_input.text(),
                    )
                total += sum(1 for block in blocks if self.text_edit_block_matches_query(block, query))
        except Exception as exc:
            self.show_error(exc)
            return

        self.text_edit_search_feedback.setText(f"整份文件符合：{total} 個文字片段。")
        self.set_status(f"整份文件共有 {total} 個搜尋符合。")

    def find_text_edit_block(self, direction: int = 1) -> None:
        query = self.text_edit_search_input.text().strip()
        if not query:
            self.set_status("請輸入要搜尋的文字。")
            return
        if self.text_edit_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return

        current_page = min(max(int(self.text_edit_page_input.text() or "1"), 1), self.text_edit_page_count)
        current_row = self.text_edit_block_list.currentRow()
        page_blocks = self.text_edit_blocks
        try:
            for offset in range(self.text_edit_page_count):
                page_number = ((current_page - 1 + offset * direction) % self.text_edit_page_count) + 1
                if offset == 0:
                    blocks = page_blocks
                    if direction > 0:
                        indexes = list(range(current_row + 1, len(blocks))) + list(range(0, max(current_row + 1, 0)))
                    else:
                        start = current_row - 1 if current_row >= 0 else len(blocks) - 1
                        indexes = list(range(start, -1, -1)) + list(range(len(blocks) - 1, start, -1))
                else:
                    blocks = extract_page_text_blocks(
                        self.text_edit_pdf_path,
                        page_number - 1,
                        self.text_edit_password_input.text(),
                    )
                    indexes = list(range(len(blocks))) if direction > 0 else list(range(len(blocks) - 1, -1, -1))
                matches = [index for index in indexes if self.text_edit_block_matches_query(blocks[index], query)]
                if matches:
                    if page_number != current_page:
                        self.text_edit_page_input.setText(str(page_number))
                        self.text_edit_blocks = blocks
                        self.render_text_edit_preview()
                        self.refresh_text_edit_blocks()
                    self.text_edit_block_list.setCurrentRow(matches[0])
                    total = sum(1 for block in blocks if self.text_edit_block_matches_query(block, query))
                    self.set_status(f"第 {page_number} 頁找到第 {matches[0] + 1} 個文字片段，共 {total} 個符合。")
                    return
        except Exception as exc:
            self.show_error(exc)
            return
        self.set_status(f"找不到文字：{self.text_edit_search_input.text().strip()}")

    def text_edit_block_matches_query(self, block: TextBlock, query: str) -> bool:
        return text_matches_query(
            block.text,
            query,
            self.text_edit_case_sensitive_checkbox.isChecked(),
            self.text_edit_whole_word_checkbox.isChecked(),
        )

    def render_text_edit_preview(self) -> None:
        if self.text_edit_pdf_path is None:
            return
        page_index = int(self.text_edit_page_input.text() or "1") - 1
        if PDF_RENDER_AVAILABLE and pdfium is not None:
            document = pdfium.PdfDocument(str(self.text_edit_pdf_path), password=self.text_edit_password_input.text() or None)
            try:
                page = document.get_page(page_index)
                try:
                    page_width, page_height = page.get_size()
                    scale = self.advanced_preview_scale(page_width, page_height)
                    self.text_edit_preview_image = page.render(scale=scale).to_pil().convert("RGB")
                finally:
                    page.close()
            finally:
                document.close()
        else:
            item = PageItem(self.text_edit_pdf_path, page_index, self.text_edit_pdf_path.name)
            self.text_edit_preview_image = self.placeholder_thumbnail(item)
        self.update_text_edit_preview()

    def on_text_edit_block_selected(self, row: int) -> None:
        if row < 0:
            return
        block = self.text_edit_block_list.item(row).data(Qt.UserRole)
        if not isinstance(block, TextBlock):
            return
        self.text_edit_replacement_input.setPlainText(block.text)
        if text_contains_cjk(block.text) and (self.text_edit_mode_combo.currentData() or "") == "content_stream":
            self.text_edit_mode_combo.setCurrentIndex(self.text_edit_mode_combo.findData("seamless"))
        self.text_edit_block_info.setText(
            f"位置 X {block.x:.1f}, Y {block.y:.1f}；字體 {block.font_size:.1f}pt；"
            f"字型 {block.font_name or '未知'}"
            + (f"；頁面字型 {block.page_font_name}" if block.page_font_name else "")
        )
        self.update_text_edit_replacement_hint()
        self.update_text_edit_preview(block)

    def current_text_edit_block(self) -> TextBlock | None:
        item = self.text_edit_block_list.currentItem()
        if item is None:
            return None
        block = item.data(Qt.UserRole)
        return block if isinstance(block, TextBlock) else None

    def update_text_edit_replacement_hint(self) -> None:
        block = self.current_text_edit_block()
        if block is None:
            self.text_edit_replacement_hint.setText("選取文字片段後會顯示替換限制。")
            return
        original = block.text.strip()
        replacement = self.text_edit_replacement_input.toPlainText().strip()
        original_length = len(original)
        replacement_length = len(replacement)
        mode = self.text_edit_mode_combo.currentData() or "seamless"
        if mode == "seamless":
            if not PYMUPDF_AVAILABLE:
                self.text_edit_replacement_hint.setText("無痕替換需要 PyMuPDF；請改用覆蓋替換。")
                return
            self.text_edit_replacement_hint.setText(
                f"無痕替換：原文 {original_length} 字 → 新文字 {replacement_length} 字；"
                f"會以 {block.font_name or '偵測字型'} / {block.font_size:.1f}pt 寫回。"
            )
            return
        if mode != "content_stream":
            self.text_edit_replacement_hint.setText(
                f"覆蓋替換：原文 {original_length} 字，新文字 {replacement_length} 字，可不同長度。"
            )
            return
        is_ascii = all(32 <= ord(char) <= 126 for char in original + replacement)
        if not replacement:
            message = "直接改內容流：請輸入替換文字；目前只支援半形英文/數字且新舊同長度。"
        elif not is_ascii:
            message = "直接改內容流：目前只支援半形英文、數字和符號；中文請用覆蓋替換。"
        elif original_length != replacement_length:
            message = f"直接改內容流：長度不同（原文 {original_length} 字，新文字 {replacement_length} 字），請改同長度或使用覆蓋替換。"
        else:
            message = f"直接改內容流：長度相同（{original_length} 字），可嘗試保留原樣式直接修改。"
        self.text_edit_replacement_hint.setText(message)

    def update_text_edit_preview(self, selected_block: TextBlock | None = None) -> None:
        if self.text_edit_preview_image is None:
            self.text_edit_preview_label.clear()
            return
        image = self.text_edit_preview_image.copy()
        reader = open_reader(self.text_edit_pdf_path, self.text_edit_password_input.text())
        page = reader.pages[int(self.text_edit_page_input.text() or "1") - 1]
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        draw = ImageDraw.Draw(image)
        scale_x = image.width / page_width
        scale_y = image.height / page_height

        query = self.text_edit_search_input.text().strip()
        if query:
            for block in self.text_edit_blocks:
                if self.text_edit_block_matches_query(block, query):
                    left, top, right, bottom = self.text_block_to_image_rect(block)
                    draw.rectangle((left, top, right, bottom), outline="#f97316", width=2)

        if selected_block is not None:
            replacement = self.text_edit_replacement_input.toPlainText().strip()
            left, top, right, bottom = self.text_replacement_preview_rect(
                selected_block,
                replacement,
                scale_x,
                scale_y,
                image.height,
            )
            if replacement:
                draw.rectangle((left, top, right, bottom), fill="#ffffff", outline="#e2e8f0", width=1)
                preview_font_size = max(selected_block.font_size * scale_y * 0.85, 8)
                font = self.text_edit_preview_font(selected_block, preview_font_size, replacement)
                text_color = rgb_to_hex(selected_block.color_rgb)
                draw.text((left + 3, top + 1), replacement, fill=text_color, font=font)
            draw.rectangle((left, top, right, bottom), outline="#0f766e", width=3)
            pixmap = QPixmap.fromImage(ImageQt(image))
            self.text_edit_preview_label.set_preview_pixmap(pixmap)
            self.show_text_edit_inline_editor(selected_block, replacement, left, top, right, bottom, scale_y)
            return
        self.text_edit_preview_label.hide_inline_editor()
        pixmap = QPixmap.fromImage(ImageQt(image))
        self.text_edit_preview_label.set_preview_pixmap(pixmap)

    def show_text_edit_inline_editor(
        self,
        block: TextBlock,
        replacement: str,
        left: float,
        top: float,
        right: float,
        bottom: float,
        scale_y: float,
    ) -> None:
        editor = self.text_edit_preview_label.inline_edit
        width = max(int(right - left), 48)
        height = max(int(bottom - top), 20)
        editor.setGeometry(int(left), int(top), width, height)
        family = "Microsoft JhengHei"
        if not QFont(family).exactMatch():
            family = "Microsoft YaHei"
        font = QFont(family, max(int(block.font_size * scale_y * 0.55), 9))
        font.setBold(bool(block.font_flags & 16) or "bold" in (block.font_name or "").lower())
        editor.setFont(font)
        color = rgb_to_hex(block.color_rgb)
        editor.setStyleSheet(
            f"QLineEdit {{ background: #ffffff; color: {color}; border: 2px solid #0f766e; padding: 0 4px; }}"
        )
        if editor.text() != replacement:
            editor.blockSignals(True)
            editor.setText(replacement)
            editor.blockSignals(False)
        editor.show()
        editor.raise_()

    def on_text_edit_inline_edited(self, text: str) -> None:
        self.text_edit_replacement_input.blockSignals(True)
        self.text_edit_replacement_input.setPlainText(text)
        self.text_edit_replacement_input.blockSignals(False)
        self.update_text_edit_replacement_hint()
        editor = self.text_edit_preview_label.inline_edit
        extra = max(editor.fontMetrics().horizontalAdvance(text) + 18, 48)
        editor.resize(max(extra, editor.width()), editor.height())

    def text_edit_preview_font(
        self,
        block: TextBlock,
        font_size_pt: float,
        text: str = "",
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        size = max(int(font_size_pt), 8)
        bold = bool(block.font_flags & 16) or "bold" in (block.font_name or "").lower()
        need_cjk = text_contains_cjk(text or block.text)
        font_file = block.font_file or ""
        font_name = Path(font_file).name.lower()
        cjk_file = any(
            token in font_name for token in ("msyh", "msjh", "mingliu", "simsun", "simhei", "noto", "cjk")
        )
        if font_file and (not need_cjk or cjk_file):
            try:
                return ImageFont.truetype(font_file, size=size, index=0)
            except Exception:
                pass
        font_key = "cjk" if need_cjk else font_key_for_pdf_font(block.font_name)
        return self.annotation_preview_font(font_size_pt, bold, font_key, text or block.text)

    def text_replacement_preview_rect(
        self,
        block: TextBlock,
        replacement: str,
        scale_x: float,
        scale_y: float,
        image_height: int,
    ) -> tuple[float, float, float, float]:
        if block.bbox != (0.0, 0.0, 0.0, 0.0):
            x0, y0, x1, y1 = block.bbox
            left = x0 * scale_x
            top = y0 * scale_y
            right = x1 * scale_x
            bottom = y1 * scale_y
            if replacement and len(replacement) > len(block.text.strip()):
                extra = (len(replacement) - len(block.text.strip())) * block.font_size * 0.55 * scale_x
                right += extra
            return (left, top, right, bottom)
        if replacement:
            cover_width = max(block.width + block.font_size * 0.8, len(replacement) * block.font_size * 0.65)
            cover_height = max(block.height, block.font_size * 1.8)
            left = block.x * scale_x
            top = image_height - (block.y + cover_height) * scale_y
            right = (block.x + cover_width) * scale_x
            bottom = image_height - (block.y - 4) * scale_y
            return (left, top, right, bottom)
        left = block.x * scale_x
        bottom = image_height - block.y * scale_y
        top = bottom - block.height * scale_y
        right = left + block.width * scale_x
        return (left, top, right, bottom)

    def current_text_edit_page_size(self) -> tuple[float, float]:
        if self.text_edit_pdf_path is None:
            return (0.0, 0.0)
        reader = open_reader(self.text_edit_pdf_path, self.text_edit_password_input.text())
        page = reader.pages[int(self.text_edit_page_input.text() or "1") - 1]
        return (float(page.mediabox.width), float(page.mediabox.height))

    def text_block_to_image_rect(self, block: TextBlock) -> tuple[float, float, float, float]:
        if self.text_edit_preview_image is None:
            return (0.0, 0.0, 0.0, 0.0)
        page_width, page_height = self.current_text_edit_page_size()
        if page_width <= 0 or page_height <= 0:
            return (0.0, 0.0, 0.0, 0.0)
        scale_x = self.text_edit_preview_image.width / page_width
        scale_y = self.text_edit_preview_image.height / page_height
        if block.bbox != (0.0, 0.0, 0.0, 0.0):
            x0, y0, x1, y1 = block.bbox
            return (x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y)
        left = block.x * scale_x
        bottom = self.text_edit_preview_image.height - block.y * scale_y
        top = bottom - block.height * scale_y
        right = left + block.width * scale_x
        return (left, top, right, bottom)

    def select_text_edit_block_at_point(self, point: QPoint) -> None:
        if self.text_edit_preview_image is None:
            return
        best_index = -1
        best_distance = float("inf")
        for index, block in enumerate(self.text_edit_blocks):
            left, top, right, bottom = self.text_block_to_image_rect(block)
            margin = 6
            if left - margin <= point.x() <= right + margin and top - margin <= point.y() <= bottom + margin:
                center_x = (left + right) / 2
                center_y = (top + bottom) / 2
                distance = abs(point.x() - center_x) + abs(point.y() - center_y)
                if distance < best_distance:
                    best_distance = distance
                    best_index = index
        if best_index >= 0:
            self.text_edit_block_list.setCurrentRow(best_index)
            self.set_status("已從預覽選取文字片段。")
        else:
            self.set_status("此位置附近沒有偵測到文字片段。")

    def save_text_edit_pdf(self) -> None:
        if self.text_edit_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        item = self.text_edit_block_list.currentItem()
        if item is None:
            self.set_status("請先選取要替換的文字片段。")
            return
        block = item.data(Qt.UserRole)
        replacement = self.text_edit_replacement_input.toPlainText().strip()
        target, _ = QFileDialog.getSaveFileName(self, "另存文字編輯 PDF", "edited-text.pdf", "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)
        mode = self.text_edit_mode_combo.currentData() or "seamless"
        if mode == "content_stream" and (
            text_contains_cjk(getattr(block, "text", "")) or text_contains_cjk(replacement)
        ):
            mode = "seamless"
            self.text_edit_mode_combo.setCurrentIndex(self.text_edit_mode_combo.findData("seamless"))
        replacement_job = replace_text_block_seamless
        if mode == "overlay":
            replacement_job = replace_text_block_overlay
        elif mode == "content_stream":
            replacement_job = replace_text_block_content_stream
        page_number = int(self.text_edit_page_input.text() or "1")

        self.run_pdf_job(
            lambda: replacement_job(
                self.text_edit_pdf_path,
                target_path,
                page_number - 1,
                block,
                replacement,
                self.text_edit_password_input.text(),
            ),
            f"已替換文字並更新預覽：{target_path.name}",
            on_success=lambda: self.show_text_edit_result(target_path, page_number),
        )

    def show_text_edit_result(self, target_path: Path, page_number: int) -> None:
        self.open_pdf_as_new_tab(target_path)
        if not target_path.exists():
            return
        self.load_advanced_pdf_from_path(target_path)
        self.text_edit_page_input.setText(str(page_number))
        self.refresh_text_edit_page()
        text_edit_index = self.advanced_tabs.indexOf(self._text_edit_tab)
        if text_edit_index >= 0:
            self.advanced_tabs.setCurrentIndex(text_edit_index)
        self.main_tabs.setCurrentWidget(self._advanced_tab)

    def redact_text_edit_pdf(self) -> None:
        if self.text_edit_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        item = self.text_edit_block_list.currentItem()
        if item is None:
            self.set_status("請先選取要遮蔽的文字片段。")
            return
        block = item.data(Qt.UserRole)
        if not isinstance(block, TextBlock):
            self.set_status("請先選取有效的文字片段。")
            return
        target, _ = QFileDialog.getSaveFileName(self, "另存遮蔽 PDF", "redacted-text.pdf", "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)
        redaction_job = redact_text_block_overlay
        if (self.text_edit_redaction_mode_combo.currentData() or "visual") == "secure":
            redaction_job = redact_text_block_secure
        self.run_pdf_job(
            lambda: redaction_job(
                self.text_edit_pdf_path,
                target_path,
                int(self.text_edit_page_input.text() or "1") - 1,
                block,
                self.text_edit_password_input.text(),
            ),
            f"已遮蔽文字並另存：{target_path.name}",
            on_success=lambda: self.open_pdf_as_new_tab(target_path),
        )

    def redact_all_text_search_matches(self) -> None:
        if self.text_edit_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        query = self.text_edit_search_input.text().strip()
        if not query:
            self.set_status("請先輸入要批量遮蔽的搜尋文字。")
            return
        target, _ = QFileDialog.getSaveFileName(self, "另存批量遮蔽 PDF", "redacted-search-results.pdf", "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)
        redacted_count = {"value": 0}

        def job() -> None:
            redacted_count["value"] = redact_matching_text_blocks_overlay(
                self.text_edit_pdf_path,
                target_path,
                query,
                self.text_edit_password_input.text(),
                self.text_edit_case_sensitive_checkbox.isChecked(),
                self.text_edit_whole_word_checkbox.isChecked(),
            )

        self.run_pdf_job(
            job,
            "",
            on_success=lambda: (
                self.open_pdf_as_new_tab(target_path),
                self.set_status(f"已遮蔽 {redacted_count['value']} 個搜尋結果並另存：{target_path.name}"),
            ),
        )

    def output_settings(self) -> QSettings:
        return QSettings(SETTINGS_ORG, SETTINGS_APP)

    def load_output_preferences(self) -> None:
        settings = self.output_settings()
        self.open_pdf_after_save_checkbox.setChecked(
            settings.value("open_pdf_after_save", True, type=bool)
        )
        self.open_folder_after_export_checkbox.setChecked(
            settings.value("open_folder_after_export", True, type=bool)
        )
        self.tool_open_pdf_tab_checkbox.setChecked(settings.value("tool_open_pdf_tab", True, type=bool))
        self.tool_open_output_folder_checkbox.setChecked(
            settings.value("tool_open_output_folder", True, type=bool)
        )
        self.office_open_pdf_checkbox.setChecked(
            settings.value("office_open_pdf", True, type=bool)
        )
        self.office_open_pdf_tab_checkbox.setChecked(
            settings.value("office_open_pdf_tab", True, type=bool)
        )
        self.office_open_output_folder_checkbox.setChecked(
            settings.value("office_open_output_folder", True, type=bool)
        )
        self.pdf_office_open_file_checkbox.setChecked(
            settings.value("pdf_office_open_file", True, type=bool)
        )
        self.pdf_office_open_output_folder_checkbox.setChecked(
            settings.value("pdf_office_open_output_folder", True, type=bool)
        )

    def save_output_preferences(self) -> None:
        settings = self.output_settings()
        settings.setValue("open_pdf_after_save", self.open_pdf_after_save_checkbox.isChecked())
        settings.setValue("open_folder_after_export", self.open_folder_after_export_checkbox.isChecked())
        settings.setValue("tool_open_pdf_tab", self.tool_open_pdf_tab_checkbox.isChecked())
        settings.setValue("tool_open_output_folder", self.tool_open_output_folder_checkbox.isChecked())
        settings.setValue("office_open_pdf", self.office_open_pdf_checkbox.isChecked())
        settings.setValue("office_open_pdf_tab", self.office_open_pdf_tab_checkbox.isChecked())
        settings.setValue("office_open_output_folder", self.office_open_output_folder_checkbox.isChecked())
        settings.setValue("pdf_office_open_file", self.pdf_office_open_file_checkbox.isChecked())
        settings.setValue("pdf_office_open_output_folder", self.pdf_office_open_output_folder_checkbox.isChecked())

    def refresh_tool_file_list(self) -> None:
        self.tool_file_list.clear()
        for path in self.tool_file_items:
            self.tool_file_list.addItem(str(path))

    def add_tool_files_from_paths(self, paths: list[Path], allowed_suffixes: set[str]) -> None:
        added = 0
        skipped = 0
        for path in paths:
            if path.is_file() and path.suffix.lower() in allowed_suffixes:
                self.tool_file_items.append(path)
                added += 1
            else:
                skipped += 1
        self.refresh_tool_file_list()
        if skipped:
            self.set_status(f"已加入 {added} 個檔案，略過 {skipped} 個不支援項目。")
        elif added:
            self.set_status(f"已加入 {added} 個檔案。")

    def add_tool_pdf_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "加入 PDF", "", "PDF files (*.pdf)")
        self.add_tool_files_from_paths([Path(path) for path in files], PDF_SUFFIXES)

    def add_tool_image_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "加入圖片",
            "",
            "Image files (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp)",
        )
        self.add_tool_files_from_paths([Path(path) for path in files], IMAGE_SUFFIXES)

    def remove_tool_files(self) -> None:
        for index in sorted((self.tool_file_list.row(item) for item in self.tool_file_list.selectedItems()), reverse=True):
            self.tool_file_items.pop(index)
        self.refresh_tool_file_list()

    def move_tool_file(self, direction: int) -> None:
        selected = sorted(self.tool_file_list.row(item) for item in self.tool_file_list.selectedItems())
        if len(selected) != 1:
            self.set_status("請選取一個檔案來上移或下移。")
            return
        source = selected[0]
        target = source + direction
        if target < 0 or target >= len(self.tool_file_items):
            return
        item = self.tool_file_items.pop(source)
        self.tool_file_items.insert(target, item)
        self.refresh_tool_file_list()
        self.tool_file_list.item(target).setSelected(True)

    def clear_tool_files(self) -> None:
        self.tool_file_items.clear()
        self.refresh_tool_file_list()

    def drop_tool_files(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() in PDF_SUFFIXES]
        image_paths = [Path(path) for path in paths if Path(path).suffix.lower() in IMAGE_SUFFIXES]
        office_paths = [Path(path) for path in paths if Path(path).suffix.lower() in OFFICE_SUFFIXES]
        if pdf_paths:
            self.add_tool_files_from_paths(pdf_paths, PDF_SUFFIXES)
        if image_paths:
            self.add_tool_files_from_paths(image_paths, IMAGE_SUFFIXES)
        if office_paths and not pdf_paths and not image_paths:
            self.set_status("Word / Excel / PowerPoint 請到「Office 轉 PDF」分頁轉換。")
            return
        if not pdf_paths and not image_paths:
            self.set_status("請拖放 PDF 或圖片檔案到工具清單。")

    def refresh_office_file_list(self) -> None:
        self.office_file_list.clear()
        for path in self.office_file_items:
            self.office_file_list.addItem(str(path))

    def add_office_files_from_paths(self, paths: list[Path]) -> None:
        added = 0
        skipped = 0
        for path in paths:
            if path.is_file() and path.suffix.lower() in OFFICE_SUFFIXES:
                self.office_file_items.append(path)
                added += 1
            else:
                skipped += 1
        self.refresh_office_file_list()
        if skipped:
            self.set_status(f"已加入 {added} 個 Office 檔，略過 {skipped} 個不支援項目。")
        elif added:
            self.set_status(f"已加入 {added} 個 Office 檔。")

    def add_office_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "加入 Word / Excel / PPT", "", OFFICE_DIALOG_FILTER)
        self.add_office_files_from_paths([Path(path) for path in files])

    def drop_office_files(self, paths: list[str]) -> None:
        office_paths = [Path(path) for path in paths if Path(path).suffix.lower() in OFFICE_SUFFIXES]
        if not office_paths:
            self.set_status("請拖放 Word、Excel 或 PowerPoint 檔案。")
            return
        self.add_office_files_from_paths(office_paths)

    def remove_office_files(self) -> None:
        for index in sorted((self.office_file_list.row(item) for item in self.office_file_list.selectedItems()), reverse=True):
            self.office_file_items.pop(index)
        self.refresh_office_file_list()

    def move_office_file(self, direction: int) -> None:
        selected = sorted(self.office_file_list.row(item) for item in self.office_file_list.selectedItems())
        if len(selected) != 1:
            self.set_status("請選取一個檔案來上移或下移。")
            return
        source = selected[0]
        target = source + direction
        if target < 0 or target >= len(self.office_file_items):
            return
        item = self.office_file_items.pop(source)
        self.office_file_items.insert(target, item)
        self.refresh_office_file_list()
        self.office_file_list.item(target).setSelected(True)

    def clear_office_files(self) -> None:
        self.office_file_items.clear()
        self.refresh_office_file_list()

    def _office_progress_dialog(self, title: str) -> QProgressDialog:
        dialog = QProgressDialog(title, None, 0, 0, self)
        dialog.setWindowTitle("Office 轉 PDF")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setCancelButton(None)
        dialog.setMinimumWidth(420)
        dialog.show()
        bar = dialog.findChild(QProgressBar)
        if bar is not None:
            configure_count_progress_bar(bar)
        return dialog

    def _update_office_progress(self, dialog: QProgressDialog, state: dict) -> None:
        text = str(state.get("text") or "正在轉換…")
        current = int(state.get("current") or 0)
        total = int(state.get("total") or 0)
        self.office_progress_label.setText(text)
        dialog.setLabelText(text)
        if total <= 0:
            self.office_progress.setRange(0, 0)
            self.office_progress.setTextVisible(False)
            dialog.setRange(0, 0)
        else:
            self.office_progress.setTextVisible(True)
            self.office_progress.setFormat("%v / %m")
            self.office_progress.setRange(0, total)
            self.office_progress.setValue(min(current, total))
            dialog.setRange(0, total)
            dialog.setValue(min(current, total))
        QApplication.processEvents()

    def _finish_office_progress(self, dialog: QProgressDialog, text: str) -> None:
        self.office_progress.setRange(0, 100)
        self.office_progress.setValue(100)
        self.office_progress.setTextVisible(True)
        self.office_progress.setFormat("完成")
        self.office_progress_label.setText(text)
        dialog.setRange(0, 100)
        dialog.setValue(100)
        dialog.setLabelText(text)
        dialog.hide()
        dialog.deleteLater()

    def _open_converted_pdfs(self, paths: list[Path]) -> None:
        if self.office_open_pdf_checkbox.isChecked():
            for path in paths:
                open_output_file(path)
        if self.office_open_pdf_tab_checkbox.isChecked():
            for path in paths:
                self.open_pdf_as_new_tab(path)

    def run_office_convert(self) -> None:
        if not self.office_file_items:
            self.set_status("請先加入 Word、Excel 或 PowerPoint 檔案。")
            return
        mode = self.office_output_mode.currentData() or "merge"
        separate = mode == "separate" and len(self.office_file_items) > 1
        if separate:
            folder = QFileDialog.getExistingDirectory(
                self, "選擇輸出資料夾", str(self.office_file_items[0].parent)
            )
            if not folder:
                return
            folder_path = Path(folder)
            outputs: list[Path] = []
            dialog = self._office_progress_dialog("正在轉換 Office 檔…")
            state = {"current": 0, "total": 0, "text": "正在轉換…"}

            def progress(current: int, total: int, text: str) -> None:
                state["current"] = current
                state["total"] = total
                state["text"] = text

            def pump() -> None:
                self._update_office_progress(dialog, state)

            def job() -> None:
                done = 0
                file_count = len(self.office_file_items)
                for index, source in enumerate(self.office_file_items, start=1):
                    target = folder_path / suggested_pdf_name_for_source(source)
                    prefix = f"({index}/{file_count}) {source.name}："

                    def nested(current: int, total: int, text: str, prefix=prefix) -> None:
                        progress(current, total, prefix + text)

                    office_files_to_pdf([source], target, progress=nested, pump=pump)
                    outputs.append(target)
                    done += 1
                self._last_tool_status_message = f"已轉換 {done} 個 Office 檔 → {folder_path}"

            def on_success() -> None:
                self._finish_office_progress(dialog, self._last_tool_status_message)
                self.set_status(self._last_tool_status_message)
                self._open_converted_pdfs(outputs)
                if self.office_open_output_folder_checkbox.isChecked():
                    reveal_output(folder_path)

            try:
                self.run_pdf_job(
                    job,
                    "",
                    on_success=on_success,
                    audit_operation="office_to_pdf",
                    audit_source=self.office_file_items[0],
                    audit_target=folder_path,
                    audit_detail=f"{len(self.office_file_items)} files",
                )
            finally:
                if dialog.isVisible():
                    self._finish_office_progress(dialog, self.office_progress_label.text())
            return

        source = self.office_file_items[0]
        suggested = str(suggested_pdf_path_for_source(source))
        target, _ = QFileDialog.getSaveFileName(self, "另存 PDF", suggested, "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)
        dialog = self._office_progress_dialog(f"正在轉換 {source.name}…")
        state = {"current": 0, "total": 0, "text": f"正在轉換 {source.name}…"}

        def progress(current: int, total: int, text: str) -> None:
            state["current"] = current
            state["total"] = total
            state["text"] = text

        def pump() -> None:
            self._update_office_progress(dialog, state)

        def job() -> None:
            converted = office_files_to_pdf(
                self.office_file_items, target_path, progress=progress, pump=pump
            )
            if converted == 1:
                self._last_tool_status_message = f"已把 {self.office_file_items[0].name} 轉成 PDF。"
            else:
                self._last_tool_status_message = f"已把 {converted} 個 Office 檔合併成 PDF。"

        def on_success() -> None:
            self._finish_office_progress(dialog, self._last_tool_status_message)
            self.set_status(self._last_tool_status_message)
            self._open_converted_pdfs([target_path])

        try:
            self.run_pdf_job(
                job,
                "",
                on_success=on_success,
                audit_operation="office_to_pdf",
                audit_source=self.office_file_items[0],
                audit_target=target_path,
            )
        finally:
            if dialog.isVisible():
                self._finish_office_progress(dialog, self.office_progress_label.text())

    def refresh_pdf_office_file_list(self) -> None:
        self.pdf_office_file_list.clear()
        for path in self.pdf_office_file_items:
            self.pdf_office_file_list.addItem(str(path))

    def add_pdf_office_files_from_paths(self, paths: list[Path]) -> None:
        added = 0
        skipped = 0
        for path in paths:
            if path.is_file() and path.suffix.lower() in PDF_SUFFIXES:
                self.pdf_office_file_items.append(path)
                added += 1
            else:
                skipped += 1
        self.refresh_pdf_office_file_list()
        if skipped:
            self.set_status(f"已加入 {added} 個 PDF，略過 {skipped} 個不支援項目。")
        elif added:
            self.set_status(f"已加入 {added} 個 PDF。")

    def add_pdf_office_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "加入 PDF", "", "PDF files (*.pdf)")
        self.add_pdf_office_files_from_paths([Path(path) for path in files])

    def drop_pdf_office_files(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() in PDF_SUFFIXES]
        if not pdf_paths:
            self.set_status("請拖放 PDF 檔案到「PDF 轉 Office」分頁。")
            return
        self.add_pdf_office_files_from_paths(pdf_paths)

    def remove_pdf_office_files(self) -> None:
        for index in sorted(
            (self.pdf_office_file_list.row(item) for item in self.pdf_office_file_list.selectedItems()),
            reverse=True,
        ):
            self.pdf_office_file_items.pop(index)
        self.refresh_pdf_office_file_list()

    def move_pdf_office_file(self, direction: int) -> None:
        selected = sorted(self.pdf_office_file_list.row(item) for item in self.pdf_office_file_list.selectedItems())
        if len(selected) != 1:
            self.set_status("請選取一個檔案來上移或下移。")
            return
        source = selected[0]
        target = source + direction
        if target < 0 or target >= len(self.pdf_office_file_items):
            return
        item = self.pdf_office_file_items.pop(source)
        self.pdf_office_file_items.insert(target, item)
        self.refresh_pdf_office_file_list()
        self.pdf_office_file_list.item(target).setSelected(True)

    def clear_pdf_office_files(self) -> None:
        self.pdf_office_file_items.clear()
        self.refresh_pdf_office_file_list()

    def _run_callable_in_background(self, fn, on_progress=None):
        events: queue.Queue = queue.Queue()
        box = {"value": None}

        def work() -> None:
            def progress_emit(current: int, total: int, text: str) -> None:
                events.put(("progress", current, total, text))

            try:
                box["value"] = fn(progress_emit)
            except Exception as exc:
                events.put(("error", exc, None, None))
                return
            events.put(("done", None, None, None))

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        error = None
        while True:
            QApplication.processEvents()
            try:
                kind, current, total, text = events.get(timeout=0.05)
            except queue.Empty:
                if not thread.is_alive() and events.empty():
                    error = RuntimeError("背景轉換已結束，但沒有回傳結果。")
                    break
                continue
            if kind == "progress":
                if on_progress is not None:
                    on_progress(current, total, text)
            elif kind == "done":
                break
            elif kind == "error":
                error = current
                break
        thread.join(timeout=2)
        if error is not None:
            raise error
        return box["value"]

    def _pdf_office_progress_dialog(self, title: str) -> QProgressDialog:
        dialog = QProgressDialog(title, None, 0, 0, self)
        dialog.setWindowTitle("PDF 轉 Office")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setCancelButton(None)
        dialog.setMinimumWidth(420)
        dialog.show()
        bar = dialog.findChild(QProgressBar)
        if bar is not None:
            configure_count_progress_bar(bar)
        return dialog

    def _update_pdf_office_progress(self, dialog: QProgressDialog, current: int, total: int, text: str) -> None:
        self.pdf_office_progress_label.setText(text)
        dialog.setLabelText(text)
        if total <= 0:
            self.pdf_office_progress.setRange(0, 0)
            self.pdf_office_progress.setTextVisible(False)
            dialog.setRange(0, 0)
        else:
            self.pdf_office_progress.setTextVisible(True)
            self.pdf_office_progress.setFormat("%v / %m")
            self.pdf_office_progress.setRange(0, total)
            self.pdf_office_progress.setValue(min(current, total))
            dialog.setRange(0, total)
            dialog.setValue(min(current, total))
        QApplication.processEvents()

    def _finish_pdf_office_progress(self, dialog: QProgressDialog, text: str) -> None:
        self.pdf_office_progress.setRange(0, 100)
        self.pdf_office_progress.setValue(100)
        self.pdf_office_progress.setTextVisible(True)
        self.pdf_office_progress.setFormat("完成")
        self.pdf_office_progress_label.setText(text)
        dialog.setRange(0, 100)
        dialog.setValue(100)
        dialog.setLabelText(text)
        dialog.hide()
        dialog.deleteLater()

    def _pdf_office_options(self) -> tuple[str, str, str, str, str, int]:
        fmt = self.pdf_office_format_combo.currentData() or "word"
        extension = ".docx" if fmt == "word" else ".xlsx"
        password = self.pdf_office_password_input.text()
        pages = self.pdf_office_pages_input.text()
        language = self.pdf_office_ocr_combo.currentData() or "auto"
        try:
            dpi = int(self.pdf_office_dpi_combo.currentText() or "200")
        except ValueError:
            dpi = 200
        return fmt, extension, password, pages, language, dpi

    def _ocr_language_status(self) -> str:
        resolved = last_ocr_language()
        if not resolved:
            return ""
        return f"（{ocr_language_short_label(resolved)}）"

    def _pdf_office_method_label(self, fmt: str, method: str) -> str:
        ocr_label = "OCR" + self._ocr_language_status() if method == "ocr" else "OCR"
        if fmt == "word":
            return {
                "word": "Microsoft Word",
                "libreoffice": "LibreOffice",
                "pdf2docx": "版面重建",
                "text": "版面重建（文字層）",
                "ocr": ocr_label,
            }.get(method, method)
        return {
            "tables": "偵測表格",
            "columns": "對齊欄位",
            "text": "文字層",
            "ocr": ocr_label,
        }.get(method, method)

    def _convert_pdf_to_office_file(
        self,
        source: Path,
        target: Path,
        fmt: str,
        password: str,
        pages: str,
        language: str,
        dpi: int,
        progress=None,
    ) -> tuple[int, str]:
        if fmt == "word":
            return pdf_to_docx(
                source,
                target,
                password,
                pages_spec=pages,
                language=language,
                dpi=dpi,
                progress=progress,
            )
        return pdf_to_xlsx(
            source,
            target,
            password,
            pages_spec=pages,
            language=language,
            dpi=dpi,
            progress=progress,
        )

    def _suggested_pdf_office_path(self, source: Path, extension: str) -> Path:
        stem = source.stem.strip(" .") or "output"
        return source.with_name(f"{stem}{extension}")

    def _open_converted_office_files(self, paths: list[Path], folder: Path | None = None) -> None:
        if self.pdf_office_open_file_checkbox.isChecked():
            for path in paths:
                open_output_file(path)
        if folder is not None and self.pdf_office_open_output_folder_checkbox.isChecked():
            reveal_output(folder)

    def run_pdf_to_office(self) -> None:
        if not self.pdf_office_file_items:
            self.set_status("請先加入 PDF 檔案。")
            return
        fmt, extension, password, pages, language, dpi = self._pdf_office_options()
        kind_label = "Word" if fmt == "word" else "Excel"
        dialog_filter = "Word files (*.docx)" if fmt == "word" else "Excel files (*.xlsx)"
        separate = len(self.pdf_office_file_items) > 1
        if separate:
            folder = QFileDialog.getExistingDirectory(
                self, "選擇輸出資料夾", str(self.pdf_office_file_items[0].parent)
            )
            if not folder:
                return
            folder_path = Path(folder)
            outputs: list[Path] = []
            dialog = self._pdf_office_progress_dialog("正在轉換 PDF…")
            self._update_pdf_office_progress(dialog, 0, len(self.pdf_office_file_items), "正在轉換…")

            def job() -> None:
                file_count = len(self.pdf_office_file_items)
                items = list(self.pdf_office_file_items)

                def work(progress_emit):
                    local_outputs: list[Path] = []
                    last_method = ""
                    for index, item in enumerate(items, start=1):
                        target = folder_path / self._suggested_pdf_office_path(item, extension).name
                        progress_emit(index - 1, file_count, f"({index}/{file_count}) {item.name}")
                        _page_count, last_method = self._convert_pdf_to_office_file(
                            item,
                            target,
                            fmt,
                            password,
                            pages,
                            language,
                            dpi,
                            progress=progress_emit,
                        )
                        local_outputs.append(target)
                    return local_outputs, last_method

                local_outputs, last_method = self._run_callable_in_background(
                    work,
                    lambda current, total, text: self._update_pdf_office_progress(
                        dialog, current, total, text
                    ),
                )
                outputs.extend(local_outputs)
                method_label = self._pdf_office_method_label(fmt, last_method)
                self._last_tool_status_message = (
                    f"已轉換 {len(outputs)} 個 PDF → {kind_label}（{method_label}）→ {folder_path}"
                )

            def on_success() -> None:
                self._finish_pdf_office_progress(dialog, self._last_tool_status_message)
                self.set_status(self._last_tool_status_message)
                self._open_converted_office_files(outputs, folder_path)

            try:
                self.run_pdf_job(
                    job,
                    "",
                    on_success=on_success,
                    audit_operation=f"pdf_to_{fmt}",
                    audit_source=self.pdf_office_file_items[0],
                    audit_target=folder_path,
                    audit_detail=f"{len(self.pdf_office_file_items)} files",
                )
            finally:
                if dialog.isVisible():
                    self._finish_pdf_office_progress(dialog, self.pdf_office_progress_label.text())
            return

        source = self.pdf_office_file_items[0]
        suggested = str(self._suggested_pdf_office_path(source, extension))
        target, _ = QFileDialog.getSaveFileName(self, f"另存 {kind_label}", suggested, dialog_filter)
        if not target:
            return
        target_path = Path(target)
        if target_path.suffix.lower() != extension:
            target_path = target_path.with_suffix(extension)
        dialog = self._pdf_office_progress_dialog(f"正在轉換 {source.name}…")
        self._update_pdf_office_progress(dialog, 0, 0, f"正在轉換 {source.name}…")

        def job() -> None:
            def work(progress_emit):
                return self._convert_pdf_to_office_file(
                    source,
                    target_path,
                    fmt,
                    password,
                    pages,
                    language,
                    dpi,
                    progress=progress_emit,
                )

            page_count, method = self._run_callable_in_background(
                work,
                lambda current, total, text: self._update_pdf_office_progress(
                    dialog, current, total, text
                ),
            )
            method_label = self._pdf_office_method_label(fmt, method)
            self._last_tool_status_message = f"已把 {page_count} 頁轉成 {kind_label}（{method_label}）。"

        def on_success() -> None:
            self._finish_pdf_office_progress(dialog, self._last_tool_status_message)
            self.set_status(self._last_tool_status_message)
            self._open_converted_office_files([target_path])

        try:
            self.run_pdf_job(
                job,
                "",
                on_success=on_success,
                audit_operation=f"pdf_to_{fmt}",
                audit_source=source,
                audit_target=target_path,
            )
        finally:
            if dialog.isVisible():
                self._finish_pdf_office_progress(dialog, self.pdf_office_progress_label.text())

    def drop_advanced_pdf(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() in PDF_SUFFIXES]
        if not pdf_paths:
            self.set_status("請拖放 PDF 檔案到進階分頁。")
            return
        self.load_advanced_pdf_from_path(pdf_paths[0], self.advanced_password_text())

    def advanced_password_text(self) -> str:
        for field in (
            getattr(self, "annotation_password_input", None),
            getattr(self, "markup_password_input", None),
            getattr(self, "crop_password_input", None),
            getattr(self, "erase_password_input", None),
            getattr(self, "text_edit_password_input", None),
            getattr(self, "bookmark_password_input", None),
        ):
            if field is not None and field.text():
                return field.text()
        return ""

    def load_advanced_pdf_from_path(self, path: Path, password: str = "") -> None:
        if self._broadcasting_advanced_pdf:
            return
        self._broadcasting_advanced_pdf = True
        try:
            if password:
                for field in (
                    self.annotation_password_input,
                    self.markup_password_input,
                    self.crop_password_input,
                    self.erase_password_input,
                    self.text_edit_password_input,
                    self.bookmark_password_input,
                ):
                    field.setText(password)
            self.set_annotation_pdf(path)
            self.set_markup_pdf(path)
            self.set_crop_pdf(path)
            self.set_erase_pdf(path)
            self.set_text_edit_pdf(path)
            self.set_bookmark_pdf(path)
            self.rebuild_advanced_thumbnails()
            self.set_status(f"已載入進階共用 PDF：{path.name}（標註／註解／裁切／橡皮擦／文字編輯／書籤）")
        finally:
            self._broadcasting_advanced_pdf = False

    def _advanced_page_count(self) -> int:
        return (
            self.annotation_page_count
            or self.markup_page_count
            or self.crop_page_count
            or self.erase_page_count
            or self.text_edit_page_count
            or self.bookmark_page_count
            or 0
        )

    def _advanced_pdf_path(self) -> Path | None:
        return (
            self.annotation_pdf_path
            or self.markup_pdf_path
            or self.crop_pdf_path
            or self.erase_pdf_path
            or self.text_edit_pdf_path
            or self.bookmark_pdf_path
        )

    def _advanced_page_inputs(self) -> list[QLineEdit]:
        return [
            self.annotation_page_input,
            self.markup_page_input,
            self.crop_page_input,
            self.erase_page_input,
            self.text_edit_page_input,
        ]

    def on_advanced_page_input_edited(self) -> None:
        if self._syncing_advanced_page:
            return
        sender = self.sender()
        raw = sender.text() if sender is not None else self.annotation_page_input.text()
        try:
            page_number = int(raw or "1")
        except (TypeError, ValueError):
            page_number = 1
        self.set_advanced_page(page_number - 1)

    def change_annotation_page(self, delta: int) -> None:
        if self.annotation_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        current = int(self.annotation_page_input.text() or "1")
        target = min(max(current + delta, 1), max(self.annotation_page_count, 1))
        if target == current:
            boundary = "第一頁" if delta < 0 else "最後一頁"
            self.set_status(f"已在{boundary}。")
            return
        self.set_advanced_page(target - 1)

    def set_advanced_page(self, page_index: int, *, from_thumbs: bool = False) -> None:
        page_count = self._advanced_page_count()
        if page_count <= 0:
            return
        page_index = min(max(int(page_index), 0), page_count - 1)
        page_number = page_index + 1
        current_page = int(self.annotation_page_input.text() or "1")
        if page_number != current_page:
            self._maybe_queue_annotation_on_page_leave()
            self._reset_live_annotation_placement()
            self._clear_annotation_draft_text()
        if self._syncing_advanced_page:
            return
        self._syncing_advanced_page = True
        try:
            for field in self._advanced_page_inputs():
                field.setText(str(page_number))
            if not from_thumbs and hasattr(self, "advanced_page_list"):
                self.advanced_page_list.blockSignals(True)
                self.advanced_page_list.setCurrentRow(page_index)
                self.advanced_page_list.blockSignals(False)
            self._erase_live_points = []
            self.clear_erase_text_selection()
            if self.annotation_pdf_path is not None:
                self.render_annotation_preview()
            if self.markup_pdf_path is not None:
                self.render_markup_preview()
            if self.crop_pdf_path is not None:
                self.render_crop_preview()
            if self.erase_pdf_path is not None:
                self.render_erase_preview()
            if self.text_edit_pdf_path is not None:
                self.refresh_text_edit_page()
        finally:
            self._syncing_advanced_page = False

    def _on_advanced_thumb_selected(self, row: int) -> None:
        if row < 0 or self._syncing_advanced_page:
            return
        self.set_advanced_page(row, from_thumbs=True)

    def _on_advanced_subtab_changed(self, _index: int) -> None:
        if self.annotation_preview_image is not None:
            self.update_annotation_preview_display()
        if self.erase_preview_image is not None:
            self.update_erase_preview_display()

    def advanced_preview_scale(self, page_width: float, page_height: float) -> float:
        zoom = max(ADVANCED_PREVIEW_ZOOM_MIN, min(self.advanced_preview_zoom, ADVANCED_PREVIEW_ZOOM_MAX))
        fitted = min(
            ANNOT_PREVIEW_MAX_WIDTH / max(page_width, 1.0),
            ANNOT_PREVIEW_MAX_HEIGHT / max(page_height, 1.0),
            1.35,
        )
        return max(0.35, min(fitted * zoom, 4.0))

    def change_advanced_preview_zoom(self, delta: float) -> None:
        self.advanced_preview_zoom = max(
            ADVANCED_PREVIEW_ZOOM_MIN,
            min(self.advanced_preview_zoom + delta, ADVANCED_PREVIEW_ZOOM_MAX),
        )
        if hasattr(self, "advanced_zoom_label"):
            self.advanced_zoom_label.setText(f"{int(round(self.advanced_preview_zoom * 100))}%")
        if self.annotation_pdf_path is not None:
            self.render_annotation_preview()
        if self.markup_pdf_path is not None:
            self.render_markup_preview()
        if self.crop_pdf_path is not None:
            self.render_crop_preview()
        if self.erase_pdf_path is not None:
            self.render_erase_preview()
        if self.text_edit_pdf_path is not None:
            self.render_text_edit_preview()

    def _advanced_thumb_target_size(self) -> tuple[int, int]:
        panel_width = ADVANCED_THUMB_PANEL_WIDTH
        if hasattr(self, "advanced_thumb_panel"):
            panel_width = max(self.advanced_thumb_panel.width(), ADVANCED_THUMB_PANEL_MIN_WIDTH)
        icon_width = max(panel_width - 40, 96)
        icon_height = int(icon_width * 1.28)
        return icon_width, icon_height

    def _apply_advanced_thumb_metrics(self) -> None:
        if not hasattr(self, "advanced_page_list"):
            return
        icon_width, icon_height = self._advanced_thumb_target_size()
        self.advanced_page_list.setIconSize(QSize(icon_width, icon_height))
        hint_width = max(icon_width + 12, 120)
        for row in range(self.advanced_page_list.count()):
            item = self.advanced_page_list.item(row)
            if item is not None:
                item.setSizeHint(QSize(hint_width, icon_height + 22))

    def _on_advanced_splitter_moved(self, *_args) -> None:
        self._apply_advanced_thumb_metrics()
        self._advanced_thumb_resize_timer.start(180)

    def _refresh_advanced_thumbs_for_width(self) -> None:
        self.rebuild_advanced_thumbnails(keep_page=True)

    def rebuild_advanced_thumbnails(self, keep_page: bool = False) -> None:
        if not hasattr(self, "advanced_page_list"):
            return
        current = self.advanced_page_list.currentRow() if keep_page else 0
        self._advanced_thumb_timer.stop()
        self._advanced_thumb_generation += 1
        self._advanced_thumb_pending = []
        self.advanced_page_list.clear()
        path = self._advanced_pdf_path()
        count = self._advanced_page_count()
        if path is None or count <= 0:
            return
        icon_width, icon_height = self._advanced_thumb_target_size()
        self.advanced_page_list.setIconSize(QSize(icon_width, icon_height))
        for index in range(count):
            item = QListWidgetItem(self.placeholder_icon, f"第 {index + 1} 頁")
            item.setSizeHint(QSize(icon_width + 12, icon_height + 22))
            self.advanced_page_list.addItem(item)
        row = min(max(current, 0), count - 1)
        self.advanced_page_list.blockSignals(True)
        self.advanced_page_list.setCurrentRow(row)
        self.advanced_page_list.blockSignals(False)
        self._advanced_thumb_pending = list(range(count))
        self._advanced_thumb_timer.start(ADVANCED_THUMB_DELAY_MS)

    def _render_next_advanced_thumb_batch(self) -> None:
        if not self._advanced_thumb_pending:
            return
        generation = self._advanced_thumb_generation
        path = self._advanced_pdf_path()
        if path is None or not PDF_RENDER_AVAILABLE or pdfium is None:
            return
        batch = self._advanced_thumb_pending[:ADVANCED_THUMB_BATCH_SIZE]
        self._advanced_thumb_pending = self._advanced_thumb_pending[ADVANCED_THUMB_BATCH_SIZE:]
        password = self.advanced_password_text()
        icon_width, icon_height = self._advanced_thumb_target_size()
        max_size = (icon_width, icon_height)
        try:
            document = pdfium.PdfDocument(str(path), password=password or None)
        except Exception:
            return
        try:
            for index in batch:
                if generation != self._advanced_thumb_generation:
                    return
                item = self.advanced_page_list.item(index)
                if item is None:
                    continue
                try:
                    page = document.get_page(index)
                    width, height = page.get_size()
                    scale = min(
                        max_size[0] / max(width, 1),
                        max_size[1] / max(height, 1),
                        0.45,
                    )
                    image = page.render(scale=scale).to_pil().convert("RGB")
                    page.close()
                    image.thumbnail(max_size, Image.Resampling.BILINEAR)
                    item.setIcon(QIcon(QPixmap.fromImage(ImageQt(image))))
                except Exception:
                    continue
        finally:
            document.close()
        if self._advanced_thumb_pending and generation == self._advanced_thumb_generation:
            self._advanced_thumb_timer.start(ADVANCED_THUMB_DELAY_MS)

    def load_annotation_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "載入 PDF", "", "PDF files (*.pdf)")
        if path:
            self.load_advanced_pdf_from_path(Path(path), self.annotation_password_input.text())

    def drop_annotation_pdf(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() in PDF_SUFFIXES]
        if not pdf_paths:
            self.set_status("請拖放 PDF 檔案到標註分頁。")
            return
        self.load_advanced_pdf_from_path(pdf_paths[0], self.annotation_password_input.text())

    def set_annotation_pdf(self, path: Path) -> None:
        try:
            reader = open_reader(path, self.annotation_password_input.text())
        except Exception as exc:
            self.show_error(exc)
            return
        self.annotation_pdf_path = path
        self.annotation_page_count = len(reader.pages)
        self.annotation_items = []
        self._annotation_placed = False
        self._annotation_manual_size = False
        self._annotation_resize_snapshot = None
        self._annotation_undo_stack = []
        self._annotation_clipboard = None
        self.refresh_annotation_item_list()
        self.annotation_page_validator.setRange(1, max(self.annotation_page_count, 1))
        self.annotation_page_input.setText("1")
        self.render_annotation_preview()
        if (
            self.annotation_shape() == "comment"
            and self.annotation_preview_image is not None
            and not self._annotation_placed
        ):
            image_width, image_height = self.annotation_preview_image.size
            self.set_annotation_position_from_click(QPoint(max(image_width // 3, 48), max(image_height // 2, 48)))
        if not self._broadcasting_advanced_pdf:
            self.rebuild_advanced_thumbnails()
        self.set_status(f"已載入 {path.name}，共 {self.annotation_page_count} 頁。")

    def render_annotation_preview(self) -> None:
        if self.annotation_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        if not PDF_RENDER_AVAILABLE or pdfium is None:
            self.set_status("PDF 預覽元件未啟用，仍可手動輸入 X/Y。")
            return
        try:
            page_number = min(max(int(self.annotation_page_input.text() or "1"), 1), self.annotation_page_count)
            self.annotation_page_input.setText(str(page_number))
            document = pdfium.PdfDocument(str(self.annotation_pdf_path), password=self.annotation_password_input.text() or None)
            page = document.get_page(page_number - 1)
            page_width, page_height = page.get_size()
            scale = self.advanced_preview_scale(page_width, page_height)
            image = page.render(scale=scale).to_pil().convert("RGB")
            page.close()
            document.close()
            self.annotation_page_size = (float(page_width), float(page_height))
            self.annotation_preview_image = image
            self.update_annotation_preview_display()
        except Exception as exc:
            self.show_error(exc)

    def update_annotation_preview_display(self) -> None:
        if self.annotation_preview_image is None:
            self.annotation_preview_label.clear()
            self.annotation_preview_label.box_rect = QRect()
            self.annotation_preview_label.pointer_rect = QRect()
            self.annotation_preview_label.handles_enabled = False
            self.annotation_preview_label.pointer_enabled = False
            self.annotation_preview_label.elbow_enabled = False
            return
        page_index = int(self.annotation_page_input.text() or "1") - 1
        preview_image = self.annotation_preview_image.copy()
        preview_image = self.paint_erase_marks_on_image(preview_image, self.annotation_page_size, page_index)
        for item in self.annotation_items:
            if item.get("page_index") == page_index:
                preview_image = self.draw_annotation_overlay_on_image(preview_image, item)
        style = self.annotation_style_values()
        live_overlay = bool(self._annotation_placed)
        if live_overlay:
            preview_image = self.draw_annotation_overlay_on_image(preview_image, style)
        pixmap = QPixmap.fromImage(ImageQt(preview_image))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        page_width, page_height = self.annotation_page_size
        image_width, image_height = preview_image.size
        if live_overlay and page_width > 0 and page_height > 0:
            if style["shape"] in CALLOUT_KINDS:
                mark_x, mark_y = style["pointer_x"], style["pointer_y"]
            else:
                mark_x, mark_y = style["pdf_x"], style["pdf_y"]
            x = mark_x / page_width * image_width
            y = (page_height - mark_y) / page_height * image_height
            pointer_center = QPoint(int(x), int(y))
            pen = QPen(Qt.GlobalColor.darkCyan, 2)
            painter.setPen(pen)
            painter.setBrush(QColor("#7fdbff"))
            painter.drawEllipse(pointer_center, 7, 7)
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(int(x) - 14, int(y), int(x) + 14, int(y))
            painter.drawLine(int(x), int(y) - 14, int(x), int(y) + 14)
            box_rect = self.annotation_image_box_rect(style)
            handle_pen = QPen(QColor("#128576"), 1)
            painter.setPen(handle_pen)
            painter.setBrush(QColor("#ffffff"))
            for handle in annotation_handle_rects(box_rect).values():
                painter.drawRect(handle)
            self.annotation_preview_label.box_rect = box_rect
            self.annotation_preview_label.pointer_rect = QRect(int(x) - 16, int(y) - 16, 32, 32)
            self.annotation_preview_label.handles_enabled = True
            self.annotation_preview_label.pointer_enabled = style["shape"] in CALLOUT_KINDS
            if style["shape"] == "comment":
                path = comment_polyline(
                    style["pdf_x"],
                    style["pdf_y"],
                    style["pdf_x"] + style["rect_width"],
                    style["pdf_y"] + style["rect_height"],
                    style["pointer_x"],
                    style["pointer_y"],
                )
                def _to_image(pdf_x: float, pdf_y: float) -> QPoint:
                    return QPoint(
                        int(round(pdf_x / page_width * image_width)),
                        int(round((page_height - pdf_y) / page_height * image_height)),
                    )

                elbow_a = _to_image(*path[1])
                elbow_b = _to_image(*path[2])
                self.annotation_preview_label.elbow_p1 = elbow_a
                self.annotation_preview_label.elbow_p2 = elbow_b
                self.annotation_preview_label.elbow_enabled = True
                mid = QPoint((elbow_a.x() + elbow_b.x()) // 2, (elbow_a.y() + elbow_b.y()) // 2)
                painter.setPen(QPen(QColor("#128576"), 1))
                painter.setBrush(QColor("#ffffff"))
                painter.drawRect(mid.x() - 5, mid.y() - 5, 10, 10)
                painter.drawRect(elbow_b.x() - 4, elbow_b.y() - 4, 8, 8)
            else:
                self.annotation_preview_label.elbow_enabled = False
        else:
            self.annotation_preview_label.box_rect = QRect()
            self.annotation_preview_label.pointer_rect = QRect()
            self.annotation_preview_label.handles_enabled = False
            self.annotation_preview_label.pointer_enabled = False
            self.annotation_preview_label.elbow_enabled = False
        painter.end()
        self.annotation_preview_label.set_preview_pixmap(pixmap)

    def _lock_annotation_box_at_current(self) -> None:
        if self.annotation_shape() not in CALLOUT_KINDS:
            return
        if self.annotation_box_locked and self.annotation_box_pdf is not None:
            return
        style = self.annotation_style_values()
        self.annotation_box_pdf = (style["pdf_x"], style["pdf_y"])
        self.annotation_box_locked = True

    def _reset_live_annotation_placement(self) -> None:
        self._annotation_placed = False
        self.annotation_box_locked = False
        self.annotation_box_pdf = None
        self._annotation_manual_size = False
        self._annotation_resize_snapshot = None

    def _clear_annotation_draft_text(self) -> None:
        if hasattr(self, "annotation_text_input"):
            self.annotation_text_input.blockSignals(True)
            self.annotation_text_input.clear()
            self.annotation_text_input.blockSignals(False)
        if hasattr(self, "markup_note_input"):
            self.markup_note_input.clear()
        if hasattr(self, "erase_text_input"):
            self._erase_syncing_text = True
            try:
                self.erase_text_input.clear()
            finally:
                self._erase_syncing_text = False

    def _annotation_tab_active(self) -> bool:
        return (
            hasattr(self, "_annotation_tab")
            and hasattr(self, "_advanced_tab")
            and self.main_tabs.currentWidget() is self._advanced_tab
            and self.advanced_tabs.currentWidget() is self._annotation_tab
        )

    def _markup_tab_active(self) -> bool:
        return (
            hasattr(self, "_markup_tab")
            and hasattr(self, "_advanced_tab")
            and self.main_tabs.currentWidget() is self._advanced_tab
            and self.advanced_tabs.currentWidget() is self._markup_tab
        )

    def _workspace_tab_active(self) -> bool:
        return hasattr(self, "_workspace_tab") and self.main_tabs.currentWidget() is self._workspace_tab

    def _box_undo_tab_active(self) -> bool:
        return (
            self._annotation_tab_active()
            or self._markup_tab_active()
            or self._erase_tab_active()
            or self._workspace_tab_active()
        )

    def _box_delete_armed(self) -> bool:
        for name in ("annotation_preview_label", "erase_preview_label", "markup_preview_label"):
            preview = getattr(self, name, None)
            if preview is not None and getattr(preview, "pending_box_delete", False):
                return True
        workspace = getattr(self, "document_workspace", None)
        if workspace is not None and getattr(getattr(workspace, "preview_widget", None), "pending_box_delete", False):
            return True
        return False

    def _clear_box_delete_arm(self) -> None:
        for name in ("annotation_preview_label", "erase_preview_label", "markup_preview_label"):
            preview = getattr(self, name, None)
            if preview is not None:
                preview.pending_box_delete = False
        workspace = getattr(self, "document_workspace", None)
        if workspace is not None and hasattr(workspace, "preview_widget"):
            workspace.preview_widget.pending_box_delete = False

    def _focused_text_editor(self):
        widget = QApplication.focusWidget()
        if isinstance(widget, (QLineEdit, QTextEdit)):
            return widget
        return None

    def _delete_in_focused_editor(self) -> bool:
        editor = self._focused_text_editor()
        if editor is None:
            return False
        if isinstance(editor, QTextEdit):
            cursor = editor.textCursor()
            if cursor.hasSelection():
                cursor.removeSelectedText()
            else:
                cursor.deleteChar()
            editor.setTextCursor(cursor)
            return True
        if isinstance(editor, QLineEdit):
            if editor.hasSelectedText():
                start = editor.selectionStart()
                selected = editor.selectedText()
                text = editor.text()
                editor.setText(text[:start] + text[start + len(selected) :])
                editor.setCursorPosition(start)
            else:
                pos = editor.cursorPosition()
                text = editor.text()
                if pos < len(text):
                    editor.setText(text[:pos] + text[pos + 1 :])
                    editor.setCursorPosition(pos)
            return True
        return False

    def _copy_text_selection_or_run(self, copy_box) -> None:
        editor = self._focused_text_editor()
        if isinstance(editor, QTextEdit) and editor.textCursor().hasSelection():
            editor.copy()
            return
        if isinstance(editor, QLineEdit) and editor.hasSelectedText():
            editor.copy()
            return
        copy_box()

    def _paste_into_editor_or_run(self, paste_box) -> None:
        editor = self._focused_text_editor()
        if editor is not None:
            editor.paste()
            return
        paste_box()

    def _annotation_undo_snapshot(self) -> dict:
        return {
            "items": [dict(item) for item in self.annotation_items],
            "placed": self._annotation_placed,
            "text": self.annotation_text_input.toPlainText() if hasattr(self, "annotation_text_input") else "",
            "x": self.annotation_x_input.text() if hasattr(self, "annotation_x_input") else "72",
            "y": self.annotation_y_input.text() if hasattr(self, "annotation_y_input") else "720",
            "width": self.annotation_width_input.text() if hasattr(self, "annotation_width_input") else "220",
            "height": self.annotation_height_input.text() if hasattr(self, "annotation_height_input") else "32",
            "box_pdf": self.annotation_box_pdf,
            "box_locked": self.annotation_box_locked,
            "manual_size": self._annotation_manual_size,
            "shape": self.annotation_shape() if hasattr(self, "annotation_shape_list") else "box",
            "cover": self.annotation_cover_checkbox.isChecked() if hasattr(self, "annotation_cover_checkbox") else True,
            "font_key": self.annotation_font_combo.currentData() if hasattr(self, "annotation_font_combo") else "cjk",
            "font_size": self.annotation_font_size_combo.currentText() if hasattr(self, "annotation_font_size_combo") else "12",
            "bold": self.annotation_bold_checkbox.isChecked() if hasattr(self, "annotation_bold_checkbox") else False,
            "color_rgb": self.annotation_color_rgb,
            "fill_rgb": self.annotation_fill_rgb,
            "fill_none": self.annotation_fill_none,
        }

    def _push_annotation_undo(self) -> None:
        if not hasattr(self, "annotation_text_input"):
            return
        self._annotation_undo_stack.append(self._annotation_undo_snapshot())
        if len(self._annotation_undo_stack) > 40:
            self._annotation_undo_stack.pop(0)

    def _restore_annotation_undo(self, snap: dict) -> None:
        self._restoring_annotation = True
        try:
            self.annotation_items = [dict(item) for item in snap.get("items", [])]
            self._annotation_placed = bool(snap.get("placed"))
            self.annotation_box_pdf = snap.get("box_pdf")
            self.annotation_box_locked = bool(snap.get("box_locked"))
            self._annotation_manual_size = bool(snap.get("manual_size"))
            self.set_annotation_shape(str(snap.get("shape") or "box"))
            self.annotation_text_input.blockSignals(True)
            self.annotation_text_input.setPlainText(str(snap.get("text") or ""))
            self.annotation_text_input.blockSignals(False)
            self.annotation_x_input.setText(str(snap.get("x") or "72"))
            self.annotation_y_input.setText(str(snap.get("y") or "720"))
            self.annotation_width_input.setText(str(snap.get("width") or "220"))
            self.annotation_height_input.setText(str(snap.get("height") or "32"))
            self.annotation_cover_checkbox.setChecked(bool(snap.get("cover", True)))
            font_row = self.annotation_font_combo.findData(snap.get("font_key") or "cjk")
            if font_row >= 0:
                self.annotation_font_combo.setCurrentIndex(font_row)
            if snap.get("font_size"):
                self.annotation_font_size_combo.setCurrentText(str(snap["font_size"]))
            self.annotation_bold_checkbox.setChecked(bool(snap.get("bold")))
            if snap.get("color_rgb"):
                self.annotation_color_rgb = tuple(snap["color_rgb"])
            self.annotation_fill_rgb = snap.get("fill_rgb")
            self.annotation_fill_none = bool(snap.get("fill_none"))
            self.refresh_annotation_item_list()
            self.update_annotation_preview_display()
        finally:
            self._restoring_annotation = False

    def undo_annotation_action(self) -> None:
        if not self._annotation_undo_stack:
            self.set_status("沒有可復原的標註動作。")
            return
        snap = self._annotation_undo_stack.pop()
        self._restore_annotation_undo(snap)
        self.set_status("已復原標註。")

    def _current_annotation_copy_item(self) -> dict | None:
        if self._annotation_placed:
            item = dict(self.annotation_style_values())
            item["page_index"] = int(self.annotation_page_input.text() or "1") - 1
            return item
        row = self.annotation_item_list.currentRow() if hasattr(self, "annotation_item_list") else -1
        if 0 <= row < len(self.annotation_items):
            return dict(self.annotation_items[row])
        if self.annotation_items:
            return dict(self.annotation_items[-1])
        return None

    def copy_annotation_box(self) -> None:
        item = self._current_annotation_copy_item()
        if item is None:
            self.set_status("請先放置標註後再複製。")
            return
        self._annotation_clipboard = dict(item)
        QApplication.clipboard().setText(str(item.get("text") or ""))
        self.set_status("已複製標註。到其他位置按 Ctrl+V 貼上。")

    def _apply_annotation_item(self, item: dict, *, offset: bool = False) -> None:
        dx, dy = (16.0, -16.0) if offset else (0.0, 0.0)
        self._restoring_annotation = True
        try:
            self.set_annotation_shape(str(item.get("shape") or "box"))
            self.annotation_text_input.blockSignals(True)
            self.annotation_text_input.setPlainText(str(item.get("text") or ""))
            self.annotation_text_input.blockSignals(False)
            self.annotation_cover_checkbox.setChecked(bool(item.get("cover")))
            font_row = self.annotation_font_combo.findData(item.get("font_key") or "cjk")
            if font_row >= 0:
                self.annotation_font_combo.setCurrentIndex(font_row)
            if item.get("font_size"):
                self.annotation_font_size_combo.setCurrentText(str(int(item["font_size"])))
            self.annotation_bold_checkbox.setChecked(bool(item.get("bold")))
            if item.get("color_rgb"):
                self.annotation_color_rgb = tuple(item["color_rgb"])
            if item.get("fill_none"):
                self.annotation_fill_none = True
            else:
                self.annotation_fill_none = False
                if item.get("fill_rgb") is not None:
                    self.annotation_fill_rgb = tuple(item["fill_rgb"])
            width = float(item.get("rect_width") or 220)
            height = float(item.get("rect_height") or 32)
            pdf_x = float(item.get("pdf_x") or 72) + dx
            pdf_y = float(item.get("pdf_y") or 200) + dy
            pointer_x = float(item.get("pointer_x") or pdf_x) + dx
            pointer_y = float(item.get("pointer_y") or pdf_y) + dy
            self.annotation_width_input.setText(f"{width:.1f}")
            self.annotation_height_input.setText(f"{height:.1f}")
            shape = str(item.get("shape") or "box")
            if shape in CALLOUT_KINDS:
                self.annotation_x_input.setText(f"{pointer_x:.1f}")
                self.annotation_y_input.setText(f"{pointer_y:.1f}")
                self.annotation_box_pdf = (pdf_x, pdf_y)
                self.annotation_box_locked = True
            else:
                self.annotation_x_input.setText(f"{pdf_x:.1f}")
                self.annotation_y_input.setText(f"{pdf_y:.1f}")
                self.annotation_box_pdf = None
                self.annotation_box_locked = False
            self._annotation_placed = True
            self._annotation_manual_size = True
            self.update_annotation_preview_display()
        finally:
            self._restoring_annotation = False

    def paste_annotation_box(self) -> None:
        if self._annotation_clipboard is None:
            self.set_status("請先點選標註後按 Ctrl+C。")
            return
        self._push_annotation_undo()
        current = None
        if self._annotation_placed:
            current = self.collect_current_annotation_item()
            if current is None and str(self.annotation_text_input.toPlainText() or "").strip() == "":
                style = dict(self.annotation_style_values())
                style["page_index"] = int(self.annotation_page_input.text() or "1") - 1
                current = style
        if current is not None and str(current.get("text") or "").strip():
            self.annotation_items.append(current)
            self.refresh_annotation_item_list()
        self._apply_annotation_item(self._annotation_clipboard, offset=True)
        self.set_status("已貼上標註。可再調整位置或文字。")

    def _annotation_queued_item_at_point(self, point: QPoint) -> int | None:
        try:
            page = int(self.annotation_page_input.text() or "1") - 1
        except ValueError:
            page = 0
        for index in range(len(self.annotation_items) - 1, -1, -1):
            item = self.annotation_items[index]
            if int(item.get("page_index", 0)) != page:
                continue
            rect = self.annotation_image_box_rect(item)
            if rect_chrome_contains(rect, point) or rect.adjusted(-2, -2, 2, 2).contains(point):
                return index
        return None

    def set_annotation_position_from_click(self, point: QPoint) -> None:
        page_width, page_height = self.annotation_page_size
        if self.annotation_preview_image is None or page_width <= 0 or page_height <= 0:
            return
        hit = self._annotation_queued_item_at_point(point)
        if hit is not None:
            self.annotation_item_list.setCurrentRow(hit)
            arm_box_delete(self.annotation_preview_label)
            self.set_status("已選取標註，按 Delete 刪除。")
            return
        self._push_annotation_undo()
        image_width, image_height = self.annotation_preview_image.size
        image_x = min(max(point.x(), 0), image_width)
        image_y = min(max(point.y(), 0), image_height)
        pdf_x = image_x / image_width * page_width
        pdf_y = page_height - (image_y / image_height * page_height)
        already_placed = self._annotation_placed and self.annotation_shape() in CALLOUT_KINDS
        box_was_locked = self.annotation_box_locked and self.annotation_box_pdf is not None
        self.annotation_x_input.setText(f"{pdf_x:.1f}")
        self.annotation_y_input.setText(f"{pdf_y:.1f}")
        self._annotation_placed = True
        if already_placed and box_was_locked:
            self.update_annotation_preview_display()
            self.set_status(f"已移動插入點（箭咀）：X {pdf_x:.1f}, Y {pdf_y:.1f}")
            return
        if self.annotation_shape() in CALLOUT_KINDS:
            self.annotation_box_locked = False
            self.annotation_box_pdf = None
            self._annotation_manual_size = False
            self.fit_annotation_box_to_text()
            self._lock_annotation_box_at_current()
            self.update_annotation_preview_display()
            self.set_status(f"已設定插入點（箭咀）：X {pdf_x:.1f}, Y {pdf_y:.1f}。可拖橫線左右伸長，或拖十字準星改插入點。")
            return
        self.annotation_box_locked = False
        self.annotation_box_pdf = None
        self._annotation_manual_size = False
        self.fit_annotation_box_to_text()
        self.set_status(f"已設定文字位置：X {pdf_x:.1f}, Y {pdf_y:.1f}")

    def move_annotation_pointer(self, point: QPoint) -> None:
        if self.annotation_preview_image is None:
            return
        self._lock_annotation_box_at_current()
        pdf_x, pdf_y = self._annotation_image_to_pdf(point)
        self.annotation_x_input.blockSignals(True)
        self.annotation_y_input.blockSignals(True)
        self.annotation_x_input.setText(f"{pdf_x:.1f}")
        self.annotation_y_input.setText(f"{pdf_y:.1f}")
        self.annotation_x_input.blockSignals(False)
        self.annotation_y_input.blockSignals(False)
        self._annotation_placed = True
        self.update_annotation_preview_display()

    def finish_annotation_pointer_interaction(self) -> None:
        self.set_status("已移動箭咀插入點。可再拖十字準星對準不同文字。")

    def move_annotation_elbow(self, point: QPoint) -> None:
        if self.annotation_preview_image is None:
            return
        self._lock_annotation_box_at_current()
        pdf_x, _pdf_y = self._annotation_image_to_pdf(point)
        self.annotation_x_input.blockSignals(True)
        self.annotation_x_input.setText(f"{pdf_x:.1f}")
        self.annotation_x_input.blockSignals(False)
        self._annotation_placed = True
        self.update_annotation_preview_display()

    def finish_annotation_elbow_interaction(self) -> None:
        self.set_status("已左右伸長附註箭咀。可再拖橫線對準不同文字。")

    def set_annotation_from_drag(self, start: QPoint, end: QPoint) -> None:
        if self.annotation_shape() not in CALLOUT_KINDS:
            self.set_annotation_position_from_click(end)
            return
        if self._annotation_placed and self.annotation_box_locked:
            self.move_annotation_pointer(end)
            return
        page_width, page_height = self.annotation_page_size
        if self.annotation_preview_image is None or page_width <= 0 or page_height <= 0:
            return
        pointer = self._annotation_image_to_pdf(start)
        box = self._annotation_image_to_pdf(end)
        self.annotation_x_input.setText(f"{pointer[0]:.1f}")
        self.annotation_y_input.setText(f"{pointer[1]:.1f}")
        self.annotation_box_pdf = box
        self.annotation_box_locked = True
        self._annotation_placed = True
        self._annotation_manual_size = False
        self.fit_annotation_box_to_text()
        self.set_status(f"已設定指引線：箭咀 ({pointer[0]:.1f}, {pointer[1]:.1f})")

    def _annotation_image_to_pdf(self, point: QPoint) -> tuple[float, float]:
        page_width, page_height = self.annotation_page_size
        image_width, image_height = self.annotation_preview_image.size
        image_x = min(max(point.x(), 0), image_width)
        image_y = min(max(point.y(), 0), image_height)
        pdf_x = image_x / image_width * page_width
        pdf_y = page_height - (image_y / image_height * page_height)
        return (pdf_x, pdf_y)

    def save_annotation_pdf(self) -> None:
        if self.annotation_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        items = list(self.annotation_items)
        current = self.collect_current_annotation_item()
        if current is not None and (self._annotation_placed or not items):
            items.append(current)
        items = [item for item in items if str(item.get("text") or "").strip()]
        if not items:
            self.set_status("請先放置或加入標註。可在多頁加入後一次另存。")
            return
        target, _ = QFileDialog.getSaveFileName(self, "另存標註 PDF", "annotated.pdf", "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)
        marks = list(self.erase_marks)
        remove_content = self.erase_remove_content_checkbox.isChecked()

        def job() -> None:
            if marks:
                apply_erase_then_text_overlays(
                    self.annotation_pdf_path,
                    target_path,
                    marks,
                    items,
                    self.annotation_password_input.text(),
                    remove_content,
                )
            else:
                add_text_overlay_annotations(
                    source=self.annotation_pdf_path,
                    target=target_path,
                    overlays=items,
                    password=self.annotation_password_input.text(),
                )

        def after_save() -> None:
            self.annotation_items = []
            self.erase_marks = []
            self._reset_live_annotation_placement()
            self.refresh_annotation_item_list()
            self.refresh_erase_list()
            self.open_pdf_as_new_tab(target_path)

        self.run_pdf_job(
            job,
            f"已套用 {len(items)} 筆文字標註：{target_path.name}",
            on_success=after_save,
        )

    def pending_annotation_overlays(self) -> list[dict]:
        items = list(self.annotation_items)
        current = self.collect_current_annotation_item()
        if current is not None and (self._annotation_placed or not items):
            items.append(current)
        return [item for item in items if str(item.get("text") or "").strip()]

    def changed_advanced_page_indexes(self) -> list[int]:
        pages: set[int] = set()
        for item in self.pending_annotation_overlays():
            pages.add(int(item.get("page_index", 0)))
        for mark in self.erase_marks:
            pages.add(int(mark.page_index))
        for page_index, _markup in self.markup_items:
            pages.add(int(page_index))
        return sorted(pages)

    def save_changed_pages_pdf(self) -> None:
        source = self._advanced_pdf_path()
        if source is None:
            self.set_status("請先載入 PDF。")
            return
        overlays = self.pending_annotation_overlays()
        marks = list(self.erase_marks)
        markups = list(self.markup_items)
        page_indexes = self.changed_advanced_page_indexes()
        if not page_indexes:
            self.set_status("目前沒有已加入註解或修改的頁。請先放置標註、螢光或橡皮擦。")
            return
        suggested = safe_output_name(f"{source.stem}-modified-pages.pdf")
        target, _ = QFileDialog.getSaveFileName(self, "另存有修改的頁", suggested, "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)
        password = self.advanced_password_text()
        remove_content = True
        if hasattr(self, "erase_remove_content_checkbox"):
            remove_content = self.erase_remove_content_checkbox.isChecked()
        page_count = {"value": 0}

        def job() -> None:
            page_count["value"] = apply_edits_and_extract_pages(
                source,
                target_path,
                page_indexes,
                overlays=overlays,
                erase_marks=marks,
                markups=markups,
                password=password,
                remove_content=remove_content,
            )

        def after_save() -> None:
            self.open_pdf_as_new_tab(target_path)
            numbers = "、".join(str(index + 1) for index in page_indexes)
            self.set_status(f"已擷取 {page_count['value']} 頁有修改的內容（第 {numbers} 頁）：{target_path.name}")

        self.run_pdf_job(job, "", on_success=after_save)

    def collect_current_annotation_item(self) -> dict | None:
        text = self.annotation_text_input.toPlainText().strip()
        if not text:
            return None
        style = self.annotation_style_values()
        style["text"] = text
        style["page_index"] = int(self.annotation_page_input.text() or "1") - 1
        return style

    def queue_current_annotation(self, *_args, silent: bool = False) -> bool:
        item = self.collect_current_annotation_item()
        if item is None:
            if not silent:
                self.set_status("請輸入標註文字後再加入。")
            return False
        self._push_annotation_undo()
        self.annotation_items.append(item)
        self._reset_live_annotation_placement()
        self._clear_annotation_draft_text()
        self.refresh_annotation_item_list()
        self.update_annotation_preview_display()
        if not silent:
            self.set_status(
                f"已加入第 {item['page_index'] + 1} 頁標註，共 {len(self.annotation_items)} 筆。可到其他頁繼續，最後再另存。"
            )
        return True

    def _maybe_queue_annotation_on_page_leave(self) -> None:
        if self._annotation_placed and self.annotation_text_input.toPlainText().strip():
            self.queue_current_annotation(silent=True)

    def refresh_annotation_item_list(self) -> None:
        if not hasattr(self, "annotation_item_list"):
            return
        self.annotation_item_list.clear()
        for item in self.annotation_items:
            preview = str(item.get("text") or "").replace("\n", " ")
            if len(preview) > 16:
                preview = f"{preview[:16]}…"
            self.annotation_item_list.addItem(f"第 {int(item.get('page_index', 0)) + 1} 頁 · {preview}")

    def delete_selected_annotation_item(self) -> None:
        self.delete_current_annotation_box()

    def delete_current_annotation_box(self) -> None:
        if self._annotation_placed:
            self._push_annotation_undo()
            self._reset_live_annotation_placement()
            if hasattr(self, "annotation_text_input"):
                self.annotation_text_input.blockSignals(True)
                self.annotation_text_input.clear()
                self.annotation_text_input.blockSignals(False)
            self.update_annotation_preview_display()
            self._clear_box_delete_arm()
            self.set_status("已刪除標註方塊。")
            return
        row = self.annotation_item_list.currentRow() if hasattr(self, "annotation_item_list") else -1
        if not (0 <= row < len(self.annotation_items)):
            try:
                page = int(self.annotation_page_input.text() or "1") - 1
            except ValueError:
                page = 0
            row = next(
                (
                    index
                    for index in range(len(self.annotation_items) - 1, -1, -1)
                    if int(self.annotation_items[index].get("page_index", 0)) == page
                ),
                -1,
            )
        if not (0 <= row < len(self.annotation_items)):
            self.set_status("目前沒有可刪除的標註方塊。")
            return
        self._push_annotation_undo()
        self.annotation_items.pop(row)
        self.refresh_annotation_item_list()
        self.update_annotation_preview_display()
        self._clear_box_delete_arm()
        self.set_status("已刪除標註。")

    def clear_annotation_items(self) -> None:
        if not self.annotation_items:
            return
        self._push_annotation_undo()
        self.annotation_items = []
        self.refresh_annotation_item_list()
        self.update_annotation_preview_display()
        self.set_status("已清空標註。")

    def _batch_sources(self) -> list[Path]:
        return [path for path in self.tool_file_items if path.suffix.lower() == ".pdf"]

    def _should_batch_tool(self, operation: str) -> bool:
        if operation in {"merge", "images_to_pdf"}:
            return False
        if not getattr(self, "tool_batch_checkbox", None) or not self.tool_batch_checkbox.isChecked():
            return False
        if operation not in BATCHABLE_OPERATIONS:
            return False
        return len(self._batch_sources()) > 1

    def _batch_output_path(self, source: Path, folder: Path, operation: str) -> Path:
        extension = tool_output_extension(operation)
        return folder / safe_output_name(f"{source.stem}_{operation}{extension}")

    def watermark_options(self) -> dict:
        try:
            x_percent = float(self.tool_watermark_x_input.text().strip() or "50")
        except ValueError:
            x_percent = 50.0
        try:
            y_percent = float(self.tool_watermark_y_input.text().strip() or "50")
        except ValueError:
            y_percent = 50.0
        color_key = self.tool_watermark_color_combo.currentData() or "gray"
        color_rgb, _label = WATERMARK_COLORS.get(color_key, WATERMARK_COLORS["gray"])
        rotation = self.tool_watermark_rotation_combo.currentData()
        opacity = self.tool_watermark_opacity_combo.currentData()
        return {
            "position": self.tool_watermark_position_combo.currentData() or "center",
            "rotation": int(45 if rotation is None else rotation),
            "font_size": combo_font_size(self.tool_watermark_size_combo, 48),
            "opacity": float(0.25 if opacity is None else opacity),
            "color_rgb": color_rgb,
            "x_percent": min(max(x_percent, 0.0), 100.0),
            "y_percent": min(max(y_percent, 0.0), 100.0),
        }

    def run_tool_operation(self) -> None:
        if not self.tool_file_items:
            self.set_status("請先加入檔案。")
            return
        operation = self.tool_operation.currentData()
        password = self.tool_password_input.text()
        source = self.tool_file_items[0]
        self._tool_aux_path = None
        batch_mode = self._should_batch_tool(operation)
        if batch_mode and operation not in BATCHABLE_OPERATIONS:
            self.set_status("這個工具不支援批次處理，請取消勾選或改用單檔。")
            return
        if operation in {"insert_pages", "replace_pages", "compare_text", "compare_visual"}:
            prompt = "選擇要比對的 PDF" if operation.startswith("compare") else "選擇來源 PDF"
            second, _ = QFileDialog.getOpenFileName(self, prompt, "", "PDF files (*.pdf)")
            if not second:
                return
            self._tool_aux_path = Path(second)
        elif operation == "stamp_image":
            image_path, _ = QFileDialog.getOpenFileName(
                self,
                "選擇印章 / 簽名圖片",
                "",
                "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
            )
            if not image_path:
                return
            self._tool_aux_path = Path(image_path)
        elif operation in {"search_markup", "secure_redact"}:
            if not self.tool_batch_text_input.text().strip():
                self.set_status("請在「文字 / 模板」欄位輸入搜尋關鍵字。")
                return

        if batch_mode:
            folder = QFileDialog.getExistingDirectory(self, "選擇批次輸出資料夾")
            if not folder:
                return
            target_path = Path(folder)

            def on_batch_success() -> None:
                self.set_status(self._last_tool_status_message)
                if self.tool_open_output_folder_checkbox.isChecked():
                    reveal_output(target_path)

            self.run_pdf_job(
                lambda: self._execute_batch_tool_operation(operation, target_path, password),
                "",
                on_success=on_batch_success,
                audit_operation=f"batch_{operation}",
                audit_target=target_path,
                audit_detail=f"{len(self._batch_sources())} files",
            )
            return

        if operation == "pdf_to_images":
            if self.tool_images_zip_checkbox.isChecked():
                target, _ = QFileDialog.getSaveFileName(
                    self,
                    "另存圖片 ZIP",
                    safe_output_name("pdf-images.zip"),
                    "ZIP files (*.zip)",
                )
                if not target:
                    return
                target_path = Path(target)
            else:
                folder = QFileDialog.getExistingDirectory(self, "選擇圖片輸出資料夾")
                if not folder:
                    return
                target_path = Path(folder)
        else:
            extension = tool_output_extension(operation)
            dialog_filter = {
                ".docx": "Word files (*.docx)",
                ".xlsx": "Excel files (*.xlsx)",
                ".txt": "Text files (*.txt)",
                ".zip": "ZIP files (*.zip)",
            }.get(extension, f"Output files (*{extension})")
            target, _ = QFileDialog.getSaveFileName(
                self,
                "另存輸出檔案",
                safe_output_name(f"{operation}{extension}"),
                dialog_filter,
            )
            if not target:
                return
            target_path = Path(target)

        def on_success() -> None:
            self.set_status(self._last_tool_status_message)
            if operation in PDF_OUTPUT_OPERATIONS and self.tool_open_pdf_tab_checkbox.isChecked():
                self.open_pdf_as_new_tab(target_path)
            if operation in FOLDER_REVEAL_OPERATIONS and self.tool_open_output_folder_checkbox.isChecked():
                reveal_output(target_path)

        self.run_pdf_job(
            lambda: self._execute_tool_operation(operation, source, target_path, password),
            "",
            on_success=on_success,
            audit_operation=operation,
            audit_source=source,
            audit_target=target_path,
        )

    def _execute_batch_tool_operation(self, operation: str, folder: Path, password: str) -> None:
        sources = self._batch_sources()
        if not sources:
            raise ValueError("批次處理需要至少一個支援的檔案。")
        folder.mkdir(parents=True, exist_ok=True)
        done = 0
        errors: list[str] = []
        for source in sources:
            target = self._batch_output_path(source, folder, operation)
            try:
                self._execute_tool_operation(operation, source, target, password)
                done += 1
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
        if done == 0:
            detail = "；".join(errors[:3]) if errors else "未知錯誤"
            raise ValueError(f"批次處理失敗。{detail}")
        message = f"批次完成：成功 {done} / {len(sources)} 個檔案 → {folder}"
        if errors:
            message += f"（失敗 {len(errors)}：{errors[0]}）"
        self._last_tool_status_message = message

    def _execute_tool_operation(self, operation: str, source: Path, target_path: Path, password: str) -> None:
        if operation == "merge":
            merge_pdf_files(self.tool_file_items, target_path, password)
            self._last_tool_status_message = f"已合併 {len(self.tool_file_items)} 個 PDF。"
            return
        if operation == "split":
            page_count = split_pdf_to_zip(source, target_path, password)
            self._last_tool_status_message = f"已拆分 {page_count} 頁並打包成 ZIP。"
            return
        if operation == "split_advanced":
            mode = self.tool_split_mode_combo.currentData() or "every"
            value = self.tool_split_value_input.text()
            file_count = split_pdf_advanced(source, target_path, mode, value, password)
            self._last_tool_status_message = f"已依設定拆分成 {file_count} 個檔案並打包成 ZIP。"
            return
        if operation == "images_to_pdf":
            images_to_pdf(self.tool_file_items, target_path)
            self._last_tool_status_message = f"已把 {len(self.tool_file_items)} 張圖片轉成 PDF。"
            return
        if operation == "pdf_to_images":
            page_count = pdf_to_images(
                source,
                target_path,
                password,
                image_format=self.tool_image_format_combo.currentData(),
                dpi=int(self.tool_image_dpi_combo.currentText()),
                pages_spec=self.tool_pages_input.text(),
            )
            if target_path.suffix.lower() == ".zip":
                self._last_tool_status_message = f"已輸出 {page_count} 張圖片並打包成 ZIP。"
            else:
                self._last_tool_status_message = f"已輸出 {page_count} 張圖片到資料夾。"
            return
        if operation == "extract":
            extract_pdf_pages(source, target_path, self.tool_pages_input.text(), password)
        elif operation == "delete":
            delete_pdf_pages(source, target_path, self.tool_pages_input.text(), password)
        elif operation == "rotate":
            rotate_pdf_pages(
                source,
                target_path,
                int(self.tool_angle_input.currentText()),
                self.tool_pages_input.text(),
                password,
            )
        elif operation == "encrypt":
            encrypt_pdf(source, target_path, self.tool_new_password_input.text(), password)
        elif operation == "encrypt_permissions":
            encrypt_pdf_with_permissions(
                source,
                target_path,
                owner_password=self.tool_new_password_input.text(),
                allow_print=self.tool_perm_print_checkbox.isChecked(),
                allow_copy=self.tool_perm_copy_checkbox.isChecked(),
                allow_modify=self.tool_perm_modify_checkbox.isChecked(),
                password=password,
            )
        elif operation == "bates":
            page_count = add_bates_numbering(
                source,
                target_path,
                prefix=self.tool_bates_prefix_input.text(),
                start=int(self.tool_bates_start_input.text() or "1"),
                digits=int(self.tool_bates_digits_combo.currentText()),
                position=self.tool_bates_position_combo.currentData() or "bottom-right",
                password=password,
            )
            self._last_tool_status_message = f"已為 {page_count} 頁加上 Bates 編號。"
            return
        elif operation == "decrypt":
            decrypt_pdf(source, target_path, password)
        elif operation == "compress":
            compress_pdf(source, target_path, password)
        elif operation == "extract_text":
            extract_pdf_text(source, target_path, password)
        elif operation == "ocr_text":
            page_count = ocr_pdf_to_text(
                source,
                target_path,
                password,
                language=self.tool_ocr_language_combo.currentData() or "auto",
                pages_spec=self.tool_pages_input.text(),
                dpi=int(self.tool_image_dpi_combo.currentText()),
            )
            self._last_tool_status_message = f"已 OCR{self._ocr_language_status()} 抽出 {page_count} 頁文字。"
            return
        elif operation == "ocr_searchable_pdf":
            page_count = ocr_pdf_to_searchable_pdf(
                source,
                target_path,
                password,
                language=self.tool_ocr_language_combo.currentData() or "auto",
                pages_spec=self.tool_pages_input.text(),
                dpi=int(self.tool_image_dpi_combo.currentText()),
            )
            self._last_tool_status_message = f"已產生 {page_count} 頁可搜尋 PDF{self._ocr_language_status()}。"
            return
        elif operation == "info":
            write_pdf_info(source, target_path, password)
        elif operation == "add_page_numbers":
            template = self.tool_batch_text_input.text().strip() or "Page {page} of {total}"
            add_page_numbers(source, target_path, template, password)
        elif operation == "watermark":
            options = self.watermark_options()
            page_count = add_watermark(
                source,
                target_path,
                self.tool_batch_text_input.text(),
                password,
                position=options["position"],
                rotation=options["rotation"],
                font_size=options["font_size"],
                opacity=options["opacity"],
                color_rgb=options["color_rgb"],
                pages_spec=self.tool_pages_input.text(),
                x_percent=options["x_percent"],
                y_percent=options["y_percent"],
            )
            self._last_tool_status_message = f"已在 {page_count} 頁加入浮水印。"
            return
        elif operation == "remove_blank_pages":
            removed = remove_blank_pages(
                source,
                target_path,
                threshold=int(self.tool_blank_threshold_combo.currentText()),
                password=password,
            )
            self._last_tool_status_message = f"已移除 {removed} 頁空白頁。"
            return
        elif operation == "clean_metadata":
            clean_metadata(source, target_path, password)
        elif operation == "insert_pages":
            if self._tool_aux_path is None:
                raise ValueError("請選擇要插入的 PDF。")
            at_index = max(int(self.tool_split_value_input.text() or "1") - 1, 0)
            inserted = insert_pdf_pages(
                source,
                self._tool_aux_path,
                target_path,
                at_index=at_index,
                pages_spec=self.tool_pages_input.text(),
                password=password,
            )
            self._last_tool_status_message = f"已插入 {inserted} 頁。"
            return
        elif operation == "replace_pages":
            if self._tool_aux_path is None:
                raise ValueError("請選擇取代來源 PDF。")
            start_index = max(int(self.tool_split_value_input.text() or "1") - 1, 0)
            replaced = replace_pdf_pages(
                source,
                self._tool_aux_path,
                target_path,
                start_index=start_index,
                pages_spec=self.tool_pages_input.text(),
                password=password,
            )
            self._last_tool_status_message = f"已取代 {replaced} 頁。"
            return
        elif operation == "compress_advanced":
            old_size, new_size = compress_pdf_advanced(
                source,
                target_path,
                image_dpi=int(self.tool_image_dpi_combo.currentText()),
                password=password,
            )
            self._last_tool_status_message = f"進階壓縮完成：{old_size} → {new_size} bytes。"
            return
        elif operation == "compare_text":
            if self._tool_aux_path is None:
                raise ValueError("請選擇要比對的 PDF。")
            diff_count = compare_pdf_text(source, self._tool_aux_path, target_path, password)
            self._last_tool_status_message = f"比對完成，{diff_count} 頁文字不同。"
            return
        elif operation == "compare_visual":
            if self._tool_aux_path is None:
                raise ValueError("請選擇要比對的 PDF。")
            diff_count = compare_pdf_visual(source, self._tool_aux_path, target_path, password)
            self._last_tool_status_message = f"視覺比對完成，{diff_count} 頁畫面不同。"
            return
        elif operation == "split_bookmarks":
            section_count = split_pdf_by_bookmarks(source, target_path, password)
            self._last_tool_status_message = f"已依書籤拆分成 {section_count} 個檔案。"
            return
        elif operation == "stamp_image":
            if self._tool_aux_path is None:
                raise ValueError("請選擇印章 / 簽名圖片。")
            page_token = (self.tool_pages_input.text().strip() or "1").split(",")[0].split("-")[0]
            page_index = max(int(page_token) - 1, 0)
            add_image_stamp(
                source,
                target_path,
                self._tool_aux_path,
                page_index,
                72.0,
                120.0,
                180.0,
                60.0,
                password,
            )
            self._last_tool_status_message = "已加入影像印章 / 簽名。"
            return
        elif operation == "text_stamp":
            stamp_text = self.tool_batch_text_input.text().strip() or "DRAFT"
            page_token = (self.tool_pages_input.text().strip() or "1").split(",")[0].split("-")[0]
            page_index = max(int(page_token) - 1, 0)
            add_text_stamp(
                source,
                target_path,
                stamp_text,
                page_index,
                72.0,
                120.0,
                180.0,
                60.0,
                password=password,
            )
            self._last_tool_status_message = f"已加入文字圖章：{stamp_text}。"
            return
        elif operation == "flatten_forms":
            field_count = flatten_form_fields(source, target_path, password)
            self._last_tool_status_message = f"已壓平 {field_count} 個表單欄位。"
            return
        elif operation == "search_markup":
            match_count = apply_text_markups_for_query(
                source,
                target_path,
                self.tool_batch_text_input.text().strip(),
                password=password,
            )
            self._last_tool_status_message = f"已標註 {match_count} 處符合文字。"
            return
        elif operation == "secure_redact":
            redact_count = secure_redact_query(
                source,
                target_path,
                self.tool_batch_text_input.text().strip(),
                password,
            )
            self._last_tool_status_message = f"已安全塗銷 {redact_count} 處符合文字。"
            return
        else:
            raise ValueError(f"未知工具：{operation}")
        self._last_tool_status_message = f"已完成：{self.tool_operation.currentText()}"

    def add_button(self, layout, text: str, callback, kind: str | None = None) -> QPushButton:
        button = QPushButton(text)
        if kind:
            button.setObjectName(kind)
        if not isinstance(layout, QVBoxLayout):
            prevent_button_clip(button)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def create_document_tab(self, title: str) -> PageGrid:
        grid = PageGrid()
        grid.filesDropped.connect(self.add_files_from_paths)
        grid.reorderRequested.connect(lambda rows, target, page_grid=grid: self.reorder_pages(rows, target, page_grid))
        grid.itemSelectionChanged.connect(self.update_stats)
        grid.itemDoubleClicked.connect(lambda list_item, page_grid=grid: self.preview_page_item(page_grid, list_item))
        grid.customContextMenuRequested.connect(
            lambda pos, page_grid=grid: self.show_page_grid_context_menu(page_grid, pos)
        )
        grid.verticalScrollBar().valueChanged.connect(
            lambda _value, page_grid=grid: self._prioritize_visible_thumbnails(page_grid)
        )
        self.workspaces[grid] = {
            "items": [],
            "cache": {},
            "pending": [],
            "pending_rest": [],
            "generation": 0,
            "undo": [],
        }
        self.document_tabs.addTab(grid, document_tab_title(title))
        self.document_tabs.setTabToolTip(self.document_tabs.indexOf(grid), title)
        self.document_tabs.setCurrentWidget(grid)
        self.set_current_workspace(grid)
        return grid

    def set_current_workspace(self, grid: PageGrid | None) -> None:
        self.page_grid = grid
        if grid is None:
            self.page_items = []
            self.thumbnail_cache = {}
            self.update_stats()
            return
        workspace = self.workspaces[grid]
        self.page_items = workspace["items"]
        self.thumbnail_cache = workspace["cache"]
        self.update_stats()

    def current_grid(self) -> PageGrid | None:
        widget = self.document_tabs.currentWidget()
        return widget if isinstance(widget, PageGrid) else None

    def current_workspace(self) -> dict | None:
        grid = self.current_grid()
        if grid is None:
            return None
        return self.workspaces.get(grid)

    def on_document_tab_changed(self, _index: int) -> None:
        self.set_current_workspace(self.current_grid())

    def close_document_tab(self, index: int) -> None:
        widget = self.document_tabs.widget(index)
        pdf_paths: set[str] = set()
        if isinstance(widget, PageGrid):
            workspace = self.workspaces.pop(widget, None)
            if workspace:
                pdf_paths = {str(item.pdf_path) for item in workspace["items"]}
        self.document_tabs.removeTab(index)
        if pdf_paths:
            self.release_unused_pdfium_documents(pdf_paths)
        if self.document_tabs.count() == 0:
            self.create_document_tab("未命名")
        else:
            self.set_current_workspace(self.current_grid())

    def choose_pdf_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "加入 PDF", "", "PDF files (*.pdf)")
        self.add_files_from_paths(files)

    def add_files_from_paths(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).is_file() and Path(path).suffix.lower() == ".pdf"]
        skipped = len(paths) - len(pdf_paths)
        added_pages = 0
        added_files = 0
        if hasattr(self, "main_tabs"):
            self.main_tabs.setCurrentIndex(0)
        for path in pdf_paths:
            try:
                reader = open_reader(path, self.password_input.text())
            except Exception as exc:
                skipped += 1
                self.show_error(exc)
                continue
            added_files += 1

            grid = self.target_grid_for_new_file(path.name)
            added_pages += self.populate_grid_from_reader(path, reader, grid)

        if added_pages:
            self.set_status(f"已加入 {added_files} 個 PDF（{self.document_tabs.count()} 個 Tab），共 {added_pages} 頁。")
        elif skipped:
            self.set_status("沒有加入頁面，請確認檔案是 PDF 或密碼正確。")

    def populate_grid_from_reader(self, path: Path, reader, grid: PageGrid) -> int:
        workspace = self.workspaces[grid]
        workspace["items"].clear()
        workspace["cache"].clear()
        for page_index in range(len(reader.pages)):
            workspace["items"].append(PageItem(path, page_index, f"{path.name} - Page {page_index + 1}"))
        self.rebuild_grid(grid=grid)
        index = self.document_tabs.indexOf(grid)
        self.document_tabs.setTabText(index, document_tab_title(path.name))
        self.document_tabs.setTabToolTip(index, path.name)
        return len(reader.pages)

    def open_pdf_as_new_tab(self, path: Path) -> None:
        reader = open_reader(path, self.password_input.text())
        grid = self.create_document_tab(path.name)
        self.populate_grid_from_reader(path, reader, grid)

    def target_grid_for_new_file(self, title: str) -> PageGrid:
        grid = self.current_grid()
        workspace = self.current_workspace()
        if grid is not None and workspace is not None and not workspace["items"] and self.document_tabs.count() == 1:
            index = self.document_tabs.indexOf(grid)
            self.document_tabs.setTabText(index, document_tab_title(title))
            self.document_tabs.setTabToolTip(index, title)
            return grid
        return self.create_document_tab(title)

    def push_undo_state(self, label: str, grid: PageGrid | None = None) -> None:
        grid = grid or self.current_grid()
        if grid is None:
            return
        workspace = self.workspaces.get(grid)
        if workspace is None:
            return
        workspace["undo"].append(
            {
                "label": label,
                "items": list(workspace["items"]),
                "selected": self.selected_indexes_for_grid(grid),
            }
        )
        if len(workspace["undo"]) > 30:
            workspace["undo"].pop(0)

    def undo_last_action(self) -> None:
        if self._erase_tab_active():
            self.undo_erase_mark()
            return
        if self._annotation_tab_active():
            self.undo_annotation_action()
            return
        if self._markup_tab_active():
            self.undo_markup_action()
            return
        if self._workspace_tab_active():
            self.document_workspace.undo()
            return
        grid = self.current_grid()
        if grid is None:
            self.set_status("沒有可復原的動作。")
            return
        workspace = self.workspaces.get(grid)
        if not workspace or not workspace["undo"]:
            self.set_status("沒有可復原的動作。")
            return
        state = workspace["undo"].pop()
        workspace["items"] = list(state["items"])
        if grid is self.current_grid():
            self.page_items = workspace["items"]
        self.rebuild_grid(set(state["selected"]), grid)
        self.set_status(f"已復原：{state['label']}。")

    def selected_indexes_for_grid(self, grid: PageGrid) -> list[int]:
        return sorted(grid.row(item) for item in grid.selectedItems())

    def rebuild_grid(self, selected_indexes: set[int] | None = None, grid: PageGrid | None = None) -> None:
        grid = grid or self.current_grid()
        if grid is None:
            return
        workspace = self.workspaces[grid]
        selected_indexes = selected_indexes or set()
        workspace["generation"] += 1
        generation = workspace["generation"]
        workspace["pending"] = []
        workspace["pending_rest"] = []

        grid.blockSignals(True)
        grid.clear()
        pending_all: list[int] = []
        for index, item in enumerate(workspace["items"]):
            icon = workspace["cache"].get(self.thumbnail_key(item), self.placeholder_icon)
            list_item = QListWidgetItem(icon, self.page_card_label(index, item))
            list_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            list_item.setData(Qt.UserRole, item)
            list_item.setSizeHint(THUMB_SIZE)
            grid.addItem(list_item)
            if index in selected_indexes:
                list_item.setSelected(True)
            if self.thumbnail_key(item) not in workspace["cache"]:
                pending_all.append(index)
        grid.blockSignals(False)
        self.update_stats()
        QApplication.processEvents()
        workspace["pending"] = pending_all[:THUMB_PRIORITY_COUNT]
        workspace["pending_rest"] = pending_all[THUMB_PRIORITY_COUNT:]
        self._prioritize_visible_thumbnails(grid)
        if workspace["pending"] or workspace.get("pending_rest"):
            QTimer.singleShot(
                0,
                lambda page_grid=grid, token=generation: self.render_next_thumbnails(page_grid, token),
            )

    def render_next_thumbnails(self, grid: PageGrid, generation: int) -> None:
        workspace = self.workspaces.get(grid)
        if not workspace or generation != workspace["generation"]:
            return
        if not workspace["pending"]:
            rest = workspace.get("pending_rest") or []
            if rest:
                workspace["pending"] = rest[:THUMB_PRIORITY_COUNT]
                workspace["pending_rest"] = rest[THUMB_PRIORITY_COUNT:]
            if not workspace["pending"]:
                return

        batch: list[int] = []
        while workspace["pending"] and len(batch) < THUMB_RENDER_BATCH:
            batch.append(workspace["pending"].pop(0))

        # Reuse one opened PDF document per path inside this batch.
        docs: dict[str, object] = {}
        try:
            for index in batch:
                if index >= len(workspace["items"]) or index >= grid.count():
                    continue
                item = workspace["items"][index]
                key = self.thumbnail_key(item)
                icon = workspace["cache"].get(key)
                if icon is None:
                    path_key = str(item.pdf_path)
                    document = docs.get(path_key)
                    if document is None:
                        document = self.get_pdfium_document(item.pdf_path)
                        if document is not None:
                            docs[path_key] = document
                    icon = QIcon(
                        QPixmap.fromImage(
                            ImageQt(self.render_page_thumbnail(item, document=document))
                        )
                    )
                    workspace["cache"][key] = icon
                grid.item(index).setIcon(icon)
        finally:
            # Keep documents cached for later batches; do not close here.
            pass
        QApplication.processEvents()

        if workspace["pending"] or workspace.get("pending_rest"):
            QTimer.singleShot(
                THUMB_RENDER_DELAY_MS,
                lambda page_grid=grid, token=generation: self.render_next_thumbnails(page_grid, token),
            )

    def _visible_item_indexes(self, grid: PageGrid) -> list[int]:
        viewport = grid.viewport().rect()
        pad = max(viewport.height() // 4, 40)
        expanded = viewport.adjusted(0, -pad, 0, pad)
        visible: list[int] = []
        for index in range(grid.count()):
            item = grid.item(index)
            if item is None:
                continue
            if grid.visualItemRect(item).intersects(expanded):
                visible.append(index)
        return visible

    def _prioritize_visible_thumbnails(self, grid: PageGrid) -> None:
        workspace = self.workspaces.get(grid)
        if not workspace:
            return
        visible = self._visible_item_indexes(grid)
        if not visible:
            return
        visible_set = set(visible)
        pending_all = list(workspace.get("pending") or []) + list(workspace.get("pending_rest") or [])
        if not pending_all:
            return
        workspace["pending"] = [index for index in pending_all if index in visible_set]
        workspace["pending_rest"] = [index for index in pending_all if index not in visible_set]

    def show_page_grid_context_menu(self, grid: PageGrid, pos: QPoint) -> None:
        item = grid.itemAt(pos)
        if item is not None and not item.isSelected():
            grid.clearSelection()
            item.setSelected(True)
        menu = QMenu(grid)
        open_action = menu.addAction("在工作台開啟")
        preview_action = menu.addAction("大圖預覽")
        chosen = menu.exec(grid.mapToGlobal(pos))
        if chosen == open_action:
            self.open_current_pdf_in_workspace(grid)
        elif chosen == preview_action and item is not None:
            self.preview_page_item(grid, item)

    def open_current_pdf_in_workspace(self, grid: PageGrid | None = None) -> None:
        grid = grid or self.current_grid()
        if grid is None:
            self.set_status("請先加入 PDF。")
            return
        workspace = self.workspaces.get(grid)
        if not workspace or not workspace["items"]:
            self.set_status("請先加入 PDF。")
            return
        selected = grid.selectedItems()
        if selected:
            item = selected[0].data(Qt.UserRole)
        else:
            item = workspace["items"][0]
        path = Path(item.pdf_path)
        workspace_index = self.main_tabs.indexOf(self._workspace_tab)
        self.main_tabs.setCurrentIndex(workspace_index)
        self.document_workspace.open_path(path)
        self.set_status(f"已在工作台開啟 {path.name}")

    def preview_page_item(self, grid: PageGrid, list_item: QListWidgetItem) -> None:
        item = list_item.data(Qt.UserRole)
        index = grid.row(list_item)
        PagePreviewDialog(self, item, f"Page {index + 1} - {item.pdf_path.name}").exec()

    def reorder_pages(self, source_rows: list[int], target_row: int, grid: PageGrid | None = None) -> None:
        grid = grid or self.current_grid()
        if grid is None:
            return
        items = self.workspaces[grid]["items"]
        source_rows = sorted(set(row for row in source_rows if 0 <= row < len(items)))
        if not source_rows:
            return
        if target_row in source_rows and len(source_rows) == 1:
            return
        self.push_undo_state("移動頁面", grid)
        moving = [items[row] for row in source_rows]
        remaining = [item for index, item in enumerate(items) if index not in source_rows]
        adjusted_target = target_row - sum(1 for row in source_rows if row < target_row)
        adjusted_target = max(0, min(adjusted_target, len(remaining)))
        self.workspaces[grid]["items"] = remaining[:adjusted_target] + moving + remaining[adjusted_target:]
        if grid is self.current_grid():
            self.page_items = self.workspaces[grid]["items"]
        selected = set(range(adjusted_target, adjusted_target + len(moving)))
        self.rebuild_grid(selected, grid)
        self.set_status("頁面順序已更新。")

    def page_card_label(self, index: int, item: PageItem) -> str:
        label = f"Page {index + 1}\n原頁 {item.page_index + 1}"
        if item.rotation:
            label += f"\n旋轉 {item.rotation}度"
        return label

    def selected_indexes(self) -> list[int]:
        grid = self.current_grid()
        if grid is None:
            return []
        return self.selected_indexes_for_grid(grid)

    def selected_or_range_indexes(self) -> list[int]:
        spec = self.range_input.text().strip()
        if spec:
            return parse_pages(spec, len(self.page_items))
        return self.selected_indexes()

    def update_stats(self) -> None:
        self.stats_label.setText(f"總頁數：{len(self.page_items)}　已選取：{len(self.selected_indexes())}")

    def move_selected_page(self, direction: int) -> None:
        indexes = self.selected_indexes()
        if len(indexes) != 1:
            self.set_status("請選取一頁來上移或下移。")
            return
        source = indexes[0]
        target = source + direction
        if target < 0 or target >= len(self.page_items):
            return
        self.push_undo_state("上移/下移頁面")
        self.page_items[source], self.page_items[target] = self.page_items[target], self.page_items[source]
        self.rebuild_grid({target})
        self.set_status("頁面順序已更新。")

    def rotate_selected_pages(self, angle: int) -> None:
        indexes = self.selected_indexes()
        if not indexes:
            self.set_status("請先選取要旋轉的頁面。")
            return
        self.push_undo_state("旋轉頁面")
        for index in indexes:
            item = self.page_items[index]
            self.page_items[index] = PageItem(item.pdf_path, item.page_index, item.label, (item.rotation + angle) % 360)
        self.rebuild_grid(set(indexes))
        self.set_status(f"已旋轉 {len(indexes)} 頁，按「儲存目前 Tab PDF」輸出新檔。")

    def remove_selected_pages(self) -> None:
        armed = self._box_delete_armed()
        if self._annotation_tab_active():
            if armed or self.annotation_preview_label.hasFocus():
                self.delete_current_annotation_box()
                return
            if self._focused_text_editor() is not None:
                self._delete_in_focused_editor()
                return
            self.delete_current_annotation_box()
            return
        if self._markup_tab_active():
            if armed or self.markup_preview_label.hasFocus():
                self.delete_selected_markup()
                return
            if self._focused_text_editor() is not None:
                self._delete_in_focused_editor()
                return
            self.delete_selected_markup()
            return
        if self._erase_tab_active():
            if armed or self.erase_preview_label.hasFocus():
                self.delete_current_erase_item()
                return
            if self._focused_text_editor() is not None:
                self._delete_in_focused_editor()
                return
            self.delete_current_erase_item()
            return
        if self._workspace_tab_active():
            if armed or self.document_workspace.preview_widget.hasFocus():
                self.document_workspace.delete_selected_item()
                self._clear_box_delete_arm()
                return
            if self._focused_text_editor() is not None:
                self._delete_in_focused_editor()
                return
            self.document_workspace.delete_selected_item()
            return
        indexes = self.selected_indexes()
        if not indexes:
            self.set_status("請先選取要移除的頁面。")
            return
        self.push_undo_state("刪除頁面")
        for index in reversed(indexes):
            self.page_items.pop(index)
        self.rebuild_grid()
        self.set_status(f"已移除 {len(indexes)} 頁。")

    def copy_selected_pages(self) -> None:
        if self._erase_text_tool_active():
            self.copy_erase_text_box()
            return
        if self._annotation_tab_active():
            self._copy_text_selection_or_run(self.copy_annotation_box)
            return
        if self._markup_tab_active():
            self._copy_text_selection_or_run(self.copy_markup_item)
            return
        if self._workspace_tab_active():
            self._copy_text_selection_or_run(self.document_workspace.copy_markup_item)
            return
        indexes = self.selected_indexes()
        if not indexes:
            self.set_status("請先選取要複製的頁面。")
            return
        self.page_clipboard = [self.page_items[index] for index in indexes]
        self.set_status(f"已複製 {len(self.page_clipboard)} 頁。")

    def cut_selected_pages(self) -> None:
        indexes = self.selected_indexes()
        if not indexes:
            self.set_status("請先選取要剪下的頁面。")
            return
        self.push_undo_state("剪下頁面")
        self.page_clipboard = [self.page_items[index] for index in indexes]
        for index in reversed(indexes):
            self.page_items.pop(index)
        self.rebuild_grid()
        self.set_status(f"已剪下 {len(self.page_clipboard)} 頁，可切到其他 Tab 後貼上。")

    def paste_pages(self) -> None:
        if self._erase_text_tool_active():
            if self._erase_text_clipboard is None:
                self.set_status("請先點選文字方塊後按 Ctrl+C。")
                return
            self.paste_erase_text_box()
            return
        if self._annotation_tab_active():
            self._paste_into_editor_or_run(self.paste_annotation_box)
            return
        if self._markup_tab_active():
            self._paste_into_editor_or_run(self.paste_markup_item)
            return
        if self._workspace_tab_active():
            self._paste_into_editor_or_run(self.document_workspace.paste_markup_item)
            return
        if not self.page_clipboard:
            self.set_status("剪貼簿沒有頁面。")
            return
        if self.current_grid() is None:
            self.create_document_tab("貼上頁面")
        indexes = self.selected_indexes()
        insert_at = indexes[-1] + 1 if indexes else len(self.page_items)
        self.push_undo_state("貼上頁面")
        self.page_items[insert_at:insert_at] = list(self.page_clipboard)
        selected = set(range(insert_at, insert_at + len(self.page_clipboard)))
        self.rebuild_grid(selected)
        self.set_status(f"已貼上 {len(self.page_clipboard)} 頁。")

    def clear_pages(self) -> None:
        if not self.page_items:
            return
        self.push_undo_state("清空目前 Tab")
        self.page_items.clear()
        self.thumbnail_cache.clear()
        self.rebuild_grid()
        self.set_status("已清空目前 Tab。")

    def export_arranged_pdf(self) -> None:
        if not self.page_items:
            self.set_status("請先加入 PDF 頁面。")
            return
        target, _ = QFileDialog.getSaveFileName(self, "儲存目前 Tab PDF", "arranged-pages.pdf", "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)

        def on_success() -> None:
            if self.open_pdf_after_save_checkbox.isChecked():
                self.open_pdf_as_new_tab(target_path)

        self.run_pdf_job(
            lambda: write_page_items_merged(
                self.page_items, list(range(len(self.page_items))), target_path, self.password_input.text()
            ),
            f"已儲存目前 Tab PDF：{target}",
            on_success=on_success,
        )

    def extract_pages_merged(self) -> None:
        try:
            indexes = self.selected_or_range_indexes()
        except Exception as exc:
            self.show_error(exc)
            return
        if not indexes:
            self.set_status("請先選取要擷取的頁面，或輸入頁碼範圍。")
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "擷取目前 Tab 頁面並合併", "extracted-selected-pages.pdf", "PDF files (*.pdf)"
        )
        if not target:
            return
        self.run_pdf_job(
            lambda: write_page_items_merged(self.page_items, indexes, Path(target), self.password_input.text()),
            f"已擷取並合併 {len(indexes)} 頁。",
            on_success=lambda target_path=Path(target): self.open_pdf_as_new_tab(target_path),
        )

    def open_merge_files_dialog(self) -> None:
        dialog = MergeFilesDialog(self)
        dialog.add_open_tabs(silent_if_empty=True)
        if dialog.exec() != QDialog.Accepted:
            return
        merge_items = dialog.page_items()
        if not merge_items:
            self.set_status("請先加入要合併的文件。")
            return
        target, _ = QFileDialog.getSaveFileName(self, "合併文件", "merged-files.pdf", "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)
        self.run_pdf_job(
            lambda: write_page_items_merged(merge_items, list(range(len(merge_items))), target_path, self.password_input.text()),
            f"已合併 {dialog.source_list.count()} 個文件，共 {len(merge_items)} 頁。",
            on_success=lambda: self.open_pdf_as_new_tab(target_path),
        )

    def all_tab_page_items(self) -> list[PageItem]:
        items: list[PageItem] = []
        for index in range(self.document_tabs.count()):
            grid = self.document_tabs.widget(index)
            if isinstance(grid, PageGrid):
                items.extend(self.workspaces.get(grid, {}).get("items", []))
        return items

    def extract_pages_separate(self) -> None:
        try:
            indexes = self.selected_or_range_indexes()
        except Exception as exc:
            self.show_error(exc)
            return
        if not indexes:
            self.set_status("請先選取要擷取的頁面，或輸入頁碼範圍。")
            return
        folder = QFileDialog.getExistingDirectory(self, "選擇單獨匯出資料夾")
        if not folder:
            return
        folder_path = Path(folder)

        def on_success() -> None:
            if self.open_folder_after_export_checkbox.isChecked():
                reveal_output(folder_path)

        self.run_pdf_job(
            lambda: write_page_items_separately(self.page_items, indexes, folder_path, self.password_input.text()),
            f"已單獨匯出 {len(indexes)} 頁。",
            on_success=on_success,
        )

    def show_audit_log_dialog(self) -> None:
        AuditLogDialog(self).exec()

    def open_audit_log(self) -> None:
        self.show_audit_log_dialog()

    def run_pdf_job(
        self,
        job,
        success_message: str,
        on_success=None,
        *,
        audit_operation: str = "",
        audit_source: Path | str = "",
        audit_target: Path | str = "",
        audit_detail: str = "",
    ) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            job()
        except Exception as exc:
            self.show_error(exc)
        else:
            if audit_operation:
                source_name = Path(audit_source).name if audit_source else ""
                target_name = Path(audit_target).name if audit_target else ""
                append_audit_event(audit_operation, source_name, target_name, audit_detail)
            if on_success is not None:
                on_success()
            if success_message:
                self.set_status(success_message)
        finally:
            QApplication.restoreOverrideCursor()

    def thumbnail_key(self, item: PageItem) -> tuple[str, int, int]:
        return (str(item.pdf_path), item.page_index, item.rotation)

    def get_pdfium_document(self, path: Path):
        if not PDF_RENDER_AVAILABLE or pdfium is None:
            return None
        key = str(Path(path))
        document = self._pdfium_docs.get(key)
        if document is not None:
            return document
        try:
            document = pdfium.PdfDocument(str(path), password=self.password_input.text() or None)
        except Exception:
            return None
        self._pdfium_docs[key] = document
        return document

    def release_unused_pdfium_documents(self, candidates: set[str]) -> None:
        still_needed: set[str] = set()
        for workspace in self.workspaces.values():
            still_needed.update(str(item.pdf_path) for item in workspace["items"])
        for key in list(candidates):
            if key in still_needed:
                continue
            document = self._pdfium_docs.pop(key, None)
            if document is None:
                continue
            try:
                document.close()
            except Exception:
                pass

    def release_all_pdfium_documents(self) -> None:
        if getattr(self, "_advanced_thumb_timer", None) is not None:
            self._advanced_thumb_timer.stop()
        if getattr(self, "_advanced_thumb_resize_timer", None) is not None:
            self._advanced_thumb_resize_timer.stop()
        self._advanced_thumb_generation += 1
        self._advanced_thumb_pending = []
        for key in list(self._pdfium_docs):
            document = self._pdfium_docs.pop(key, None)
            if document is None:
                continue
            try:
                document.close()
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        self.release_all_pdfium_documents()
        super().closeEvent(event)

    def render_page_thumbnail(self, item: PageItem, document=None) -> Image.Image:
        return self.render_page_image(
            item,
            scale=THUMB_RENDER_SCALE,
            max_size=(ICON_SIZE.width() - 12, ICON_SIZE.height() - 12),
            document=document,
            decorate=False,
        )

    def render_page_preview(self, item: PageItem) -> Image.Image:
        return self.render_page_image(item, scale=1.2, max_size=(900, 1200), decorate=True)

    def render_page_image(
        self,
        item: PageItem,
        scale: float,
        max_size: tuple[int, int],
        document=None,
        decorate: bool = True,
    ) -> Image.Image:
        if PDF_RENDER_AVAILABLE and pdfium is not None:
            try:
                if document is None:
                    document = self.get_pdfium_document(item.pdf_path)
                if document is None:
                    return self.placeholder_thumbnail(item)
                page = document.get_page(item.page_index)
                try:
                    bitmap = page.render(scale=scale, rotation=item.rotation)
                    image = bitmap.to_pil().convert("RGB")
                    image.thumbnail(max_size, Image.Resampling.BILINEAR)
                    if decorate:
                        return self.page_canvas(image, max_size)
                    return image
                finally:
                    page.close()
            except Exception:
                pass
        return self.placeholder_thumbnail(item)

    def page_canvas(self, page_image: Image.Image, max_size: tuple[int, int]) -> Image.Image:
        width, height = max_size
        canvas = Image.new("RGB", (width + 12, height + 12), "#f2f2f2")
        x = (canvas.width - page_image.width) // 2
        y = (canvas.height - page_image.height) // 2
        shadow = Image.new("RGB", (page_image.width, page_image.height), "#d5d5d5")
        canvas.paste(shadow, (x + 3, y + 3))
        canvas.paste(page_image, (x, y))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((x, y, x + page_image.width - 1, y + page_image.height - 1), outline="#b7b7b7", width=1)
        return canvas

    def placeholder_thumbnail(self, item: PageItem | None) -> Image.Image:
        image = Image.new("RGB", (ICON_SIZE.width(), ICON_SIZE.height()), "#f2f2f2")
        draw = ImageDraw.Draw(image)
        draw.rectangle((14, 14, ICON_SIZE.width() - 14, ICON_SIZE.height() - 14), fill="#ffffff", outline="#d0d0d0", width=2)
        draw.text((22, 76), "PDF", fill="#666666")
        if item is not None:
            draw.text((22, 102), f"Page {item.page_index + 1}", fill="#666666")
        return image

    def set_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def show_error(self, error: Exception) -> None:
        QMessageBox.critical(self, "Victor PDF Tools Box", str(error))


def main() -> int:
    app = QApplication(sys.argv)
    window = VictorPdfToolsQt()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
