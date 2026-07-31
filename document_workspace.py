from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path

from PIL import Image, ImageDraw
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QIntValidator, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from audit_log import append_audit_event
from pdf_core import (
    MARKUP_COLOR_PRESETS,
    PDF_RENDER_AVAILABLE,
    PDF_SUFFIXES,
    PYMUPDF_AVAILABLE,
    BookmarkItem,
    MarkupAnnotation,
    TextBlock,
    add_signature_image,
    add_text_stamp,
    apply_markup_annotations,
    apply_outline,
    apply_text_markups_for_query,
    compress_pdf_advanced,
    compare_pdf_text,
    crop_pdf_pages,
    delete_pdf_pages,
    extract_outline,
    extract_page_text_blocks,
    flatten_form_fields,
    insert_pdf_pages,
    open_reader,
    pdfium,
    replace_pdf_pages,
    replace_text_block_seamless,
    rotate_pdf_pages,
    safe_output_name,
    secure_redact_query,
    split_pdf_by_bookmarks,
)

PREVIEW_MAX_WIDTH = 760
PREVIEW_MAX_HEIGHT = 760
THUMB_MAX_SIZE = (120, 160)
THUMB_BATCH_SIZE = 6
ZOOM_MIN = 0.5
ZOOM_MAX = 3.0
ZOOM_STEP = 0.1
UNDO_STACK_MAX = 30

MODE_IDS = ("read", "annotate", "edit", "organize", "crop", "tools")
MODE_DEFAULT_INTERACTION = {
    "read": None,
    "annotate": "annotate",
    "edit": "edit",
    "organize": None,
    "crop": "crop",
    "tools": None,
}


def _wrap_side_panel(panel: QWidget, max_width: int = 300) -> QScrollArea:
    panel.setMinimumWidth(max(220, max_width - 24))
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


class PreviewImageLabel(QLabel):
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


class WorkspacePreviewLabel(PreviewImageLabel):
    rectDrawn = Signal(QPoint, QPoint)
    pointClicked = Signal(QPoint)

    def __init__(self) -> None:
        super().__init__()
        self.band_color = QColor(18, 133, 118)
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

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._start is not None and self._current is not None:
            painter = QPainter(self)
            pen = QPen(self.band_color, 2, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(QRect(self._start, self._current).normalized())
            painter.end()


def _render_page_image(
    pdf_path: Path,
    page_index: int,
    password: str,
    max_size: tuple[int, int],
    scale_cap: float = 1.25,
    zoom: float = 1.0,
) -> tuple[Image.Image | None, tuple[float, float]]:
    if not PDF_RENDER_AVAILABLE or pdfium is None:
        return None, (0.0, 0.0)
    try:
        document = pdfium.PdfDocument(str(pdf_path), password=password or None)
        page = document.get_page(page_index)
        try:
            page_width, page_height = page.get_size()
            base_scale = min(max_size[0] / page_width, max_size[1] / page_height, scale_cap)
            scale = base_scale * max(ZOOM_MIN, min(zoom, ZOOM_MAX))
            image = page.render(scale=scale).to_pil().convert("RGB")
            return image, (float(page_width), float(page_height))
        finally:
            page.close()
            document.close()
    except Exception:
        return None, (0.0, 0.0)


def _placeholder_image(width: int, height: int, label: str = "PDF") -> Image.Image:
    image = Image.new("RGB", (width, height), "#f2f2f2")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, width - 8, height - 8), fill="#ffffff", outline="#d0d0d0", width=2)
    draw.text((18, height // 2 - 8), label, fill="#666666")
    return image


MARKUP_TOOL_OPTIONS = [
    ("highlight", "螢光標示"),
    ("underline", "底線"),
    ("strikeout", "刪除線"),
    ("rect", "矩形框"),
    ("ellipse", "橢圓框"),
    ("line", "直線"),
    ("arrow", "箭頭"),
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

TEXT_STAMP_PRESETS = ["APPROVED", "CONFIDENTIAL", "DRAFT", "COPY"]


class DocumentWorkspace(QWidget):
    """Acrobat-like document workspace with reading, annotation, edit, organize, and tools modes."""

    status_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pdf_path: Path | None = None
        self.password = ""
        self.page_count = 0
        self.current_page = 0
        self.page_size = (0.0, 0.0)
        self.preview_image: Image.Image | None = None
        self.preview_zoom = 1.0
        self.interaction: str | None = None
        self.markup_items: list[tuple[int, MarkupAnnotation]] = []
        self.markup_color_rgb = MARKUP_COLOR_PRESETS["yellow"]
        self.text_blocks: list[TextBlock] = []
        self.undo_stack: list[dict] = []
        self.crop_rect: tuple[float, float, float, float] | None = None
        self.signature_rect: tuple[float, float, float, float] | None = None
        self.signature_image_path: Path | None = None
        self.stamp_rect: tuple[float, float, float, float] | None = None
        self.stamp_text: str = ""
        self.bookmark_items: list[BookmarkItem] = []
        self._thumb_generation = 0
        self._thumb_pending: list[int] = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._render_next_thumb_batch)
        self._build_ui()
        self._install_shortcuts()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(8)

        top = QHBoxLayout()
        self.add_button(top, "開啟 PDF...", self.choose_pdf)
        self.add_button(top, "復原", self.undo)
        top.addSpacing(8)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for index, (mode_id, label) in enumerate(
            [
                ("read", "閱讀"),
                ("annotate", "註解"),
                ("edit", "編輯"),
                ("organize", "整理"),
                ("crop", "裁切"),
                ("tools", "工具"),
            ]
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("mode_id", mode_id)
            if index == 0:
                button.setChecked(True)
            self.mode_group.addButton(button, index)
            top.addWidget(button)
        self.mode_group.idClicked.connect(self._on_mode_changed)
        top.addStretch(1)
        self.path_label = QLabel("尚未載入 PDF")
        self.path_label.setObjectName("muted")
        top.addWidget(self.path_label)
        root.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(10)

        left_tabs = QTabWidget()
        left_tabs.setMinimumWidth(200)
        left_tabs.setMaximumWidth(220)

        self.thumb_list = QListWidget()
        self.thumb_list.setIconSize(QSize(96, 128))
        self.thumb_list.currentRowChanged.connect(self._on_thumb_selected)
        left_tabs.addTab(self.thumb_list, "縮圖")

        self.bookmark_tree = QTreeWidget()
        self.bookmark_tree.setHeaderHidden(True)
        self.bookmark_tree.itemSelectionChanged.connect(self._on_bookmark_tree_selected)
        self.bookmark_tree.itemDoubleClicked.connect(self._on_bookmark_activated)
        bookmark_tab = QWidget()
        bookmark_layout = QVBoxLayout(bookmark_tab)
        bookmark_layout.setContentsMargins(4, 4, 4, 4)
        bookmark_layout.setSpacing(6)
        bookmark_layout.addWidget(self.bookmark_tree, 1)
        bookmark_layout.addWidget(QLabel("書籤標題"))
        self.bookmark_title_input = QLineEdit()
        self.bookmark_title_input.setPlaceholderText("例如：第一章")
        bookmark_layout.addWidget(self.bookmark_title_input)
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("頁碼"))
        self.bookmark_page_input = QLineEdit("1")
        self.bookmark_page_input.setFixedWidth(56)
        self.bookmark_page_validator = QIntValidator(1, 1, self)
        self.bookmark_page_input.setValidator(self.bookmark_page_validator)
        page_row.addWidget(self.bookmark_page_input)
        page_row.addStretch(1)
        bookmark_layout.addLayout(page_row)
        bookmark_layout.addWidget(QLabel("層級"))
        self.bookmark_level_combo = QComboBox()
        self.bookmark_level_combo.addItem("主層 (0)", 0)
        self.bookmark_level_combo.addItem("子層 (1)", 1)
        self.bookmark_level_combo.addItem("次子層 (2)", 2)
        bookmark_layout.addWidget(self.bookmark_level_combo)
        bm_row1 = QHBoxLayout()
        self.add_button(bm_row1, "新增", self._add_bookmark_item)
        self.add_button(bm_row1, "更新", self._update_bookmark_item)
        self.add_button(bm_row1, "刪除", self._delete_bookmark_item, "danger")
        bookmark_layout.addLayout(bm_row1)
        bm_row2 = QHBoxLayout()
        self.add_button(bm_row2, "上移", lambda: self._move_bookmark_item(-1))
        self.add_button(bm_row2, "下移", lambda: self._move_bookmark_item(1))
        bookmark_layout.addLayout(bm_row2)
        self.add_button(bookmark_layout, "套用書籤並另存 PDF", self._save_bookmark_outline, "primary")
        left_tabs.addTab(bookmark_tab, "書籤")
        body.addWidget(left_tabs)

        center = QVBoxLayout()
        nav = QHBoxLayout()
        self.add_button(nav, "上一頁", lambda: self.change_page(-1))
        self.add_button(nav, "下一頁", lambda: self.change_page(1))
        nav.addWidget(QLabel("頁碼"))
        self.page_input = QLineEdit("1")
        self.page_input.setFixedWidth(56)
        self.page_validator = QIntValidator(1, 1, self)
        self.page_input.setValidator(self.page_validator)
        self.page_input.editingFinished.connect(self._sync_page_from_input)
        nav.addWidget(self.page_input)
        nav.addWidget(QLabel(f"/ {self.page_count}"))
        self.page_total_label = nav.itemAt(nav.count() - 1).widget()
        nav.addSpacing(12)
        self.add_button(nav, "−", lambda: self._change_zoom(-ZOOM_STEP))
        self.zoom_label = QLabel("100%")
        self.zoom_label.setFixedWidth(48)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        nav.addWidget(self.zoom_label)
        self.add_button(nav, "+", lambda: self._change_zoom(ZOOM_STEP))
        self.add_button(nav, "適合頁面", self._fit_preview_zoom)
        nav.addSpacing(12)
        self.add_button(nav, "更新預覽", self.render_preview)
        nav.addStretch(1)
        center.addLayout(nav)

        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(False)
        preview_scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.preview_scroll = preview_scroll
        self.preview_label = WorkspacePreviewLabel()
        self.preview_label.rectDrawn.connect(self._on_preview_rect_drawn)
        self.preview_label.pointClicked.connect(self._on_preview_point_clicked)
        preview_scroll.setWidget(self.preview_label)
        center.addWidget(preview_scroll, 1)
        body.addLayout(center, 1)

        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self._build_read_panel())
        self.right_stack.addWidget(self._build_annotate_panel())
        self.right_stack.addWidget(self._build_edit_panel())
        self.right_stack.addWidget(self._build_organize_panel())
        self.right_stack.addWidget(self._build_crop_panel())
        self.right_stack.addWidget(self._build_tools_panel())
        body.addWidget(_wrap_side_panel(self.right_stack, 300))
        root.addLayout(body, 1)
        self.interaction = MODE_DEFAULT_INTERACTION["read"]

    def _build_read_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("搜尋"))
        self.read_search_input = QLineEdit()
        self.read_search_input.setPlaceholderText("輸入關鍵字")
        layout.addWidget(self.read_search_input)
        self.add_button(layout, "搜尋並螢光標註", self.search_and_highlight)
        self.add_button(layout, "安全塗銷關鍵字", self.secure_redact_keyword)
        layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.read_password_input = QLineEdit()
        self.read_password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.read_password_input)
        hint = QLabel("搜尋會另存新檔；安全塗銷會永久移除符合文字。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return panel

    def _build_annotate_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("標註工具"))
        self.markup_tool_combo = QComboBox()
        for value, label in MARKUP_TOOL_OPTIONS:
            self.markup_tool_combo.addItem(label, value)
        layout.addWidget(self.markup_tool_combo)
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("顏色"))
        self.markup_color_combo = QComboBox()
        for value, label in MARKUP_COLOR_OPTIONS:
            self.markup_color_combo.addItem(label, value)
        self.markup_color_combo.currentIndexChanged.connect(self._on_markup_color_changed)
        color_row.addWidget(self.markup_color_combo, 1)
        self.markup_color_button = QPushButton("選色")
        self.markup_color_button.setFixedWidth(56)
        self.markup_color_button.clicked.connect(self._choose_markup_color)
        color_row.addWidget(self.markup_color_button)
        layout.addLayout(color_row)
        layout.addWidget(QLabel("便利貼 / 註解文字"))
        self.markup_note_input = QLineEdit()
        layout.addWidget(self.markup_note_input)
        layout.addWidget(QLabel("待定標註"))
        self.markup_pending_list = QListWidget()
        self.markup_pending_list.setMaximumHeight(140)
        layout.addWidget(self.markup_pending_list)
        row = QHBoxLayout()
        self.add_button(row, "刪除", self._delete_pending_markup, "danger")
        self.add_button(row, "清空", self._clear_pending_markups)
        layout.addLayout(row)
        self.add_button(layout, "套用待定標註", self.apply_pending_markups, "primary")
        layout.addStretch(1)
        return panel

    def _build_edit_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("文字區塊（目前頁）"))
        self.text_block_list = QListWidget()
        self.text_block_list.setMaximumHeight(180)
        self.text_block_list.currentRowChanged.connect(self._on_text_block_selected)
        layout.addWidget(self.text_block_list)
        layout.addWidget(QLabel("替換文字"))
        self.text_replacement_input = QTextEdit()
        self.text_replacement_input.setFixedHeight(72)
        layout.addWidget(self.text_replacement_input)
        self.add_button(layout, "替換選取區塊", self.replace_selected_text_block)
        self.add_button(layout, "壓平表單欄位", self.flatten_forms)
        layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.edit_password_input = QLineEdit()
        self.edit_password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.edit_password_input)
        layout.addStretch(1)
        return panel

    def _build_organize_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("插入頁面來源（頁碼）"))
        self.organize_insert_pages_input = QLineEdit()
        self.organize_insert_pages_input.setPlaceholderText("留空=全部；例 1-3")
        layout.addWidget(self.organize_insert_pages_input)
        self.add_button(layout, "插入頁面...", self.insert_pages)
        self.add_button(layout, "取代目前頁...", self.replace_pages)
        self.add_button(layout, "旋轉目前頁 90°", lambda: self.rotate_current_page(90))
        self.add_button(layout, "刪除目前頁", self.delete_current_page, "danger")
        layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.organize_password_input = QLineEdit()
        self.organize_password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.organize_password_input)
        layout.addStretch(1)
        return panel

    def _build_crop_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        hint = QLabel("在預覽上拖曳框選裁切區域，或手動輸入邊界（PDF 點，原點左下）。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        for label_text, attr in (
            ("左 (L)", "crop_left_input"),
            ("下 (B)", "crop_bottom_input"),
            ("右 (R)", "crop_right_input"),
            ("上 (T)", "crop_top_input"),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label_text))
            widget = QLineEdit()
            widget.textChanged.connect(self._on_crop_inputs_changed)
            setattr(self, attr, widget)
            row.addWidget(widget, 1)
            layout.addLayout(row)
        layout.addWidget(QLabel("套用範圍"))
        self.crop_scope_combo = QComboBox()
        self.crop_scope_combo.addItem("目前頁", "current")
        self.crop_scope_combo.addItem("全部頁", "all")
        self.crop_scope_combo.addItem("自訂頁碼", "spec")
        self.crop_scope_combo.currentIndexChanged.connect(self._on_crop_scope_changed)
        layout.addWidget(self.crop_scope_combo)
        self.crop_pages_input = QLineEdit()
        self.crop_pages_input.setPlaceholderText("例如 1-3,5")
        self.crop_pages_input.setEnabled(False)
        layout.addWidget(self.crop_pages_input)
        self.add_button(layout, "重設為整頁", self._reset_crop_rect)
        self.add_button(layout, "套用裁切", self.apply_crop, "primary")
        layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.crop_password_input = QLineEdit()
        self.crop_password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.crop_password_input)
        layout.addStretch(1)
        return panel

    def _build_tools_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel("簽名 / 印章"))
        self.add_button(layout, "選擇簽名圖並框選位置...", self.choose_signature_image)
        self.add_button(layout, "套用簽名到 PDF", self.apply_signature_to_pdf, "primary")
        self.add_button(layout, "取消待套用簽名", self.cancel_pending_signature)
        layout.addSpacing(8)
        layout.addWidget(QLabel("文字圖章"))
        self.stamp_preset_combo = QComboBox()
        for preset in TEXT_STAMP_PRESETS:
            self.stamp_preset_combo.addItem(preset, preset)
        self.stamp_preset_combo.addItem("自訂", "custom")
        layout.addWidget(self.stamp_preset_combo)
        self.stamp_custom_input = QLineEdit()
        self.stamp_custom_input.setPlaceholderText("自訂圖章文字")
        layout.addWidget(self.stamp_custom_input)
        self.add_button(layout, "在預覽框選後蓋章", self.start_text_stamp_placement)
        self.add_button(layout, "套用文字圖章", self.apply_text_stamp_to_pdf, "primary")
        self.add_button(layout, "取消待套用圖章", self.cancel_pending_text_stamp)
        note = QLabel("Bates 編號請使用「常用 PDF 工具」分頁。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.add_button(layout, "進階壓縮", self.compress_advanced)
        self.add_button(layout, "比對 PDF 文字...", self.compare_pdf)
        self.add_button(layout, "依書籤拆分", self.split_by_bookmarks)
        self.add_button(layout, "壓平表單欄位", self.flatten_forms)
        layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.tools_password_input = QLineEdit()
        self.tools_password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.tools_password_input)
        self.add_button(layout, "開啟處理紀錄", self._open_audit_log)
        layout.addStretch(1)
        return panel

    def _install_shortcuts(self) -> None:
        context = Qt.WidgetWithChildrenShortcut

        undo_action = QAction("復原", self)
        undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        undo_action.setShortcutContext(context)
        undo_action.triggered.connect(self.undo)
        self.addAction(undo_action)

        for key, delta in (
            (QKeySequence(Qt.Key_Left), -1),
            (QKeySequence(Qt.Key_Right), 1),
            (QKeySequence(Qt.Key_PageUp), -1),
            (QKeySequence(Qt.Key_PageDown), 1),
        ):
            action = QAction(self)
            action.setShortcut(key)
            action.setShortcutContext(context)
            action.triggered.connect(lambda _checked=False, step=delta: self.change_page(step))
            self.addAction(action)

        self.preview_scroll.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.preview_scroll and event.type() == event.Type.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self._change_zoom(ZOOM_STEP)
                elif delta < 0:
                    self._change_zoom(-ZOOM_STEP)
                return True
        return super().eventFilter(obj, event)

    def _open_audit_log(self) -> None:
        import os

        from audit_log import audit_log_path

        path = audit_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")
        if os.name == "nt":
            os.startfile(str(path))
        else:
            import subprocess

            subprocess.run(["xdg-open", str(path)], check=False)

    def add_button(self, layout, text: str, callback, kind: str | None = None) -> QPushButton:
        button = QPushButton(text)
        if kind:
            button.setObjectName(kind)
        button.clicked.connect(callback)
        if isinstance(layout, QVBoxLayout):
            layout.addWidget(button)
        else:
            layout.addWidget(button)
        return button

    def current_path(self) -> Path | None:
        return self.pdf_path

    def open_path(self, path: Path) -> None:
        path = Path(path)
        if path.suffix.lower() not in PDF_SUFFIXES:
            self._emit_status("請選擇 PDF 檔案。")
            return
        password = self._active_password()
        try:
            reader = open_reader(path, password)
            page_count = len(reader.pages)
        except Exception as exc:
            QMessageBox.critical(self, "文件工作台", str(exc))
            return
        self.pdf_path = path
        self.password = password
        self.page_count = page_count
        self.current_page = 0
        self.markup_items = []
        self.crop_rect = None
        self.signature_rect = None
        self.signature_image_path = None
        self.stamp_rect = None
        self.stamp_text = ""
        self._refresh_markup_list()
        self.path_label.setText(path.name)
        self.page_validator.setRange(1, max(page_count, 1))
        self.bookmark_page_validator.setRange(1, max(page_count, 1))
        self.page_input.setText("1")
        self.page_total_label.setText(f"/ {page_count}")
        self._populate_thumbnails()
        self._populate_bookmarks()
        self._load_text_blocks()
        self.render_preview()
        self._emit_status(f"已載入 {path.name}，共 {page_count} 頁。")

    def choose_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "開啟 PDF", "", "PDF files (*.pdf)")
        if path:
            self.open_path(Path(path))

    def _active_password(self) -> str:
        for widget in (
            self.read_password_input,
            self.edit_password_input,
            self.organize_password_input,
            self.crop_password_input,
            self.tools_password_input,
        ):
            if widget.text():
                return widget.text()
        return self.password

    def _on_mode_changed(self, index: int) -> None:
        self.right_stack.setCurrentIndex(index)
        mode_id = MODE_IDS[index] if 0 <= index < len(MODE_IDS) else "read"
        self.interaction = MODE_DEFAULT_INTERACTION.get(mode_id)
        if mode_id == "crop":
            self.preview_label.band_color = QColor(214, 69, 65)
        elif mode_id == "signature" or self.interaction == "signature":
            self.preview_label.band_color = QColor(18, 133, 118)
        else:
            self.preview_label.band_color = QColor(18, 133, 118)
        self._update_preview_display()

    def change_page(self, delta: int) -> None:
        if self.page_count <= 0:
            return
        target = min(max(self.current_page + delta, 0), self.page_count - 1)
        if target != self.current_page:
            self.current_page = target
            self.page_input.setText(str(target + 1))
            self.thumb_list.setCurrentRow(target)
            self._load_text_blocks()
            self.render_preview()

    def _sync_page_from_input(self) -> None:
        if self.page_count <= 0:
            return
        page = min(max(int(self.page_input.text() or "1"), 1), self.page_count)
        self.current_page = page - 1
        self.page_input.setText(str(page))
        self.thumb_list.blockSignals(True)
        self.thumb_list.setCurrentRow(self.current_page)
        self.thumb_list.blockSignals(False)
        self._load_text_blocks()
        self.render_preview()

    def _on_thumb_selected(self, row: int) -> None:
        if row < 0 or row >= self.page_count:
            return
        self.current_page = row
        self.page_input.setText(str(row + 1))
        self._load_text_blocks()
        self.render_preview()

    def _populate_thumbnails(self) -> None:
        self._thumb_timer.stop()
        self._thumb_generation += 1
        self._thumb_pending = []
        self.thumb_list.clear()
        if self.pdf_path is None:
            return
        for index in range(self.page_count):
            self.thumb_list.addItem(QListWidgetItem(f"第 {index + 1} 頁"))
        self._thumb_pending = self._thumb_render_order()
        if self.page_count:
            self.thumb_list.setCurrentRow(self.current_page)
        self._schedule_thumb_batch()

    def _thumb_render_order(self) -> list[int]:
        if self.page_count <= 0:
            return []
        current = self.current_page
        order = [current]
        for delta in range(1, self.page_count):
            for candidate in (current - delta, current + delta):
                if 0 <= candidate < self.page_count and candidate not in order:
                    order.append(candidate)
        return order

    def _schedule_thumb_batch(self) -> None:
        if self._thumb_pending:
            self._thumb_timer.start(0)

    def _render_next_thumb_batch(self) -> None:
        generation = self._thumb_generation
        if self.pdf_path is None or generation != self._thumb_generation:
            return
        password = self._active_password()
        batch: list[int] = []
        while self._thumb_pending and len(batch) < THUMB_BATCH_SIZE:
            batch.append(self._thumb_pending.pop(0))
        for index in batch:
            if generation != self._thumb_generation:
                return
            item = self.thumb_list.item(index)
            if item is None:
                continue
            image, _ = _render_page_image(
                self.pdf_path,
                index,
                password,
                THUMB_MAX_SIZE,
                scale_cap=0.5,
            )
            if image is None:
                image = _placeholder_image(THUMB_MAX_SIZE[0], THUMB_MAX_SIZE[1], f"P{index + 1}")
            else:
                image.thumbnail(THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
            item.setIcon(QIcon(QPixmap.fromImage(ImageQt(image))))
        if self._thumb_pending and generation == self._thumb_generation:
            self._thumb_timer.start(1)

    def _populate_bookmarks(self) -> None:
        if self.pdf_path is None:
            self.bookmark_items = []
            self._refresh_bookmark_tree()
            return
        try:
            self.bookmark_items = extract_outline(self.pdf_path, self._active_password())
        except Exception:
            self.bookmark_items = []
        self._refresh_bookmark_tree()

    def _refresh_bookmark_tree(self) -> None:
        self.bookmark_tree.clear()
        for item in self.bookmark_items:
            indent = "　" * item.level
            tree_item = QTreeWidgetItem([f"{indent}{item.title}（第 {item.page_index + 1} 頁）"])
            tree_item.setData(0, Qt.UserRole, item.page_index)
            self.bookmark_tree.addTopLevelItem(tree_item)

    def _bookmark_selected_index(self) -> int:
        item = self.bookmark_tree.currentItem()
        if item is None:
            return -1
        return self.bookmark_tree.indexOfTopLevelItem(item)

    def _on_bookmark_tree_selected(self) -> None:
        index = self._bookmark_selected_index()
        if index < 0 or index >= len(self.bookmark_items):
            return
        item = self.bookmark_items[index]
        self.bookmark_title_input.setText(item.title)
        self.bookmark_page_input.setText(str(item.page_index + 1))
        level_index = self.bookmark_level_combo.findData(item.level)
        if level_index >= 0:
            self.bookmark_level_combo.setCurrentIndex(level_index)

    def _bookmark_from_inputs(self) -> BookmarkItem | None:
        title = self.bookmark_title_input.text().strip()
        if not title:
            self._emit_status("請輸入書籤標題。")
            return None
        page_index = int(self.bookmark_page_input.text() or "1") - 1
        if self.page_count:
            page_index = max(0, min(page_index, self.page_count - 1))
        level = self.bookmark_level_combo.currentData() or 0
        return BookmarkItem(title, page_index, int(level))

    def _add_bookmark_item(self) -> None:
        new_item = self._bookmark_from_inputs()
        if new_item is None:
            return
        index = self._bookmark_selected_index()
        insert_at = index + 1 if 0 <= index < len(self.bookmark_items) else len(self.bookmark_items)
        self.bookmark_items.insert(insert_at, new_item)
        self._refresh_bookmark_tree()
        self.bookmark_tree.setCurrentItem(self.bookmark_tree.topLevelItem(insert_at))
        self._emit_status(f"已新增書籤：{new_item.title}")

    def _update_bookmark_item(self) -> None:
        index = self._bookmark_selected_index()
        if not (0 <= index < len(self.bookmark_items)):
            self._emit_status("請選取要更新的書籤。")
            return
        new_item = self._bookmark_from_inputs()
        if new_item is None:
            return
        self.bookmark_items[index] = new_item
        self._refresh_bookmark_tree()
        self.bookmark_tree.setCurrentItem(self.bookmark_tree.topLevelItem(index))
        self._emit_status(f"已更新書籤：{new_item.title}")

    def _delete_bookmark_item(self) -> None:
        index = self._bookmark_selected_index()
        if not (0 <= index < len(self.bookmark_items)):
            self._emit_status("請選取要刪除的書籤。")
            return
        removed = self.bookmark_items.pop(index)
        self._refresh_bookmark_tree()
        if self.bookmark_items:
            self.bookmark_tree.setCurrentItem(
                self.bookmark_tree.topLevelItem(min(index, len(self.bookmark_items) - 1))
            )
        self._emit_status(f"已刪除書籤：{removed.title}")

    def _move_bookmark_item(self, direction: int) -> None:
        index = self._bookmark_selected_index()
        target = index + direction
        if not (0 <= index < len(self.bookmark_items)) or not (0 <= target < len(self.bookmark_items)):
            return
        self.bookmark_items[index], self.bookmark_items[target] = (
            self.bookmark_items[target],
            self.bookmark_items[index],
        )
        self._refresh_bookmark_tree()
        self.bookmark_tree.setCurrentItem(self.bookmark_tree.topLevelItem(target))

    def _save_bookmark_outline(self) -> None:
        if self.pdf_path is None:
            self._emit_status("請先載入 PDF。")
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存書籤 PDF", safe_output_name("bookmarked.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        items = list(self.bookmark_items)
        password = self._active_password()

        def job() -> None:
            apply_outline(self.pdf_path, target_path, items, password)

        if self._run_job(job, "已套用書籤。", audit_operation="bookmark_outline", audit_target=target_path) is not None:
            self._offer_reload_output(target_path)

    def _on_bookmark_activated(self, item: QTreeWidgetItem) -> None:
        page_index = item.data(0, Qt.UserRole)
        if page_index is None:
            return
        self.current_page = int(page_index)
        self.page_input.setText(str(self.current_page + 1))
        self.thumb_list.setCurrentRow(self.current_page)
        self._load_text_blocks()
        self.render_preview()

    def render_preview(self) -> None:
        if self.pdf_path is None:
            self.preview_label.clear()
            return
        image, page_size = _render_page_image(
            self.pdf_path,
            self.current_page,
            self._active_password(),
            (PREVIEW_MAX_WIDTH, PREVIEW_MAX_HEIGHT),
            zoom=self.preview_zoom,
        )
        if image is None:
            image = _placeholder_image(PREVIEW_MAX_WIDTH, PREVIEW_MAX_HEIGHT)
            page_size = (float(PREVIEW_MAX_WIDTH), float(PREVIEW_MAX_HEIGHT))
        self.page_size = page_size
        self.preview_image = image
        self._update_preview_display()

    def _change_zoom(self, delta: float) -> None:
        self.preview_zoom = max(ZOOM_MIN, min(self.preview_zoom + delta, ZOOM_MAX))
        self._update_zoom_label()
        self.render_preview()

    def _fit_preview_zoom(self) -> None:
        self.preview_zoom = 1.0
        self._update_zoom_label()
        self.render_preview()
        self._emit_status("已重設為適合頁面。")

    def _update_zoom_label(self) -> None:
        self.zoom_label.setText(f"{int(round(self.preview_zoom * 100))}%")

    def _make_undo_snapshot(self) -> dict:
        markup_copy = [
            (page_index, MarkupAnnotation(
                kind=markup.kind,
                x0=markup.x0,
                y0=markup.y0,
                x1=markup.x1,
                y1=markup.y1,
                color_rgb=markup.color_rgb,
                contents=markup.contents,
            ))
            for page_index, markup in self.markup_items
        ]
        return {
            "pdf_path": self.pdf_path,
            "password": self.password,
            "markup_items": markup_copy,
            "current_page": self.current_page,
            "crop_rect": self.crop_rect,
            "signature_rect": self.signature_rect,
            "signature_image_path": self.signature_image_path,
            "stamp_rect": self.stamp_rect,
            "stamp_text": self.stamp_text,
        }

    def _push_undo_snapshot(self) -> None:
        self.undo_stack.append(self._make_undo_snapshot())
        if len(self.undo_stack) > UNDO_STACK_MAX:
            self.undo_stack.pop(0)

    def undo(self) -> None:
        if not self.undo_stack:
            self._emit_status("沒有可復原的動作。")
            return
        snapshot = self.undo_stack.pop()
        self._restore_undo_snapshot(snapshot)
        self._emit_status("已復原上一動作。")

    def _restore_undo_snapshot(self, snapshot: dict) -> None:
        target_path = snapshot.get("pdf_path")
        if target_path is not None and target_path != self.pdf_path:
            self.pdf_path = target_path
            self.password = snapshot.get("password", "")
            try:
                reader = open_reader(target_path, self.password)
                self.page_count = len(reader.pages)
            except Exception:
                pass
            self.path_label.setText(target_path.name)
            self.page_validator.setRange(1, max(self.page_count, 1))
            self.bookmark_page_validator.setRange(1, max(self.page_count, 1))
            self.page_total_label.setText(f"/ {self.page_count}")
            self._populate_thumbnails()
            self._populate_bookmarks()
        self.markup_items = deepcopy(snapshot.get("markup_items", []))
        self.current_page = snapshot.get("current_page", 0)
        self.crop_rect = snapshot.get("crop_rect")
        self.signature_rect = snapshot.get("signature_rect")
        self.signature_image_path = snapshot.get("signature_image_path")
        self.stamp_rect = snapshot.get("stamp_rect")
        self.stamp_text = snapshot.get("stamp_text", "")
        self.page_input.setText(str(self.current_page + 1))
        self.thumb_list.blockSignals(True)
        self.thumb_list.setCurrentRow(self.current_page)
        self.thumb_list.blockSignals(False)
        self._refresh_markup_list()
        if self.crop_rect is not None:
            self._set_crop_rect(self.crop_rect, update_inputs=True)
        self._load_text_blocks()
        self.render_preview()

    def _on_preview_rect_drawn(self, start: QPoint, end: QPoint) -> None:
        interaction = self.interaction
        if interaction == "annotate":
            self._add_markup_from_rect(start, end)
        elif interaction == "crop":
            self._set_crop_rect_from_drag(start, end)
        elif interaction == "signature":
            self._set_signature_rect_from_drag(start, end)
        elif interaction == "text_stamp":
            self._set_stamp_rect_from_drag(start, end)
        else:
            self._emit_status("目前模式不支援框選操作。")

    def _on_preview_point_clicked(self, point: QPoint) -> None:
        interaction = self.interaction
        if interaction == "annotate":
            self._add_markup_from_point(point)
        elif interaction == "edit":
            self._select_text_block_at_point(point)
        else:
            pass

    def _update_preview_display(self) -> None:
        if self.preview_image is None:
            self.preview_label.clear()
            return
        page_width, page_height = self.page_size
        canvas = self.preview_image.convert("RGBA")
        image_width, image_height = canvas.size
        scale_x = image_width / page_width if page_width else 1.0
        scale_y = image_height / page_height if page_height else 1.0

        if self.interaction == "crop" and self.crop_rect is not None and page_width > 0 and page_height > 0:
            left, bottom, right, top = self.crop_rect
            ix0 = left * scale_x
            ix1 = right * scale_x
            iy0 = image_height - top * scale_y
            iy1 = image_height - bottom * scale_y
            dim = Image.new("RGBA", canvas.size, (0, 0, 0, 120))
            clear = ImageDraw.Draw(dim)
            clear.rectangle((ix0, iy0, ix1, iy1), fill=(0, 0, 0, 0))
            canvas = Image.alpha_composite(canvas, dim)
            crop_draw = ImageDraw.Draw(canvas)
            crop_draw.rectangle((ix0, iy0, ix1, iy1), outline=(214, 69, 65, 255), width=2)

        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        def to_image(x: float, y: float) -> tuple[float, float]:
            return (x * scale_x, image_height - y * scale_y)

        for page_index, markup in self.markup_items:
            if page_index != self.current_page:
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
                draw.rectangle((ix0, iy0 - 16, ix0 + 16, iy0), fill=(red, green, blue, 230))

        if self.signature_rect is not None and page_width > 0 and page_height > 0:
            sx, sy, sw, sh = self.signature_rect
            sig_ix0 = sx * scale_x
            sig_ix1 = (sx + sw) * scale_x
            sig_iy0 = image_height - (sy + sh) * scale_y
            sig_iy1 = image_height - sy * scale_y
            draw.rectangle(
                (sig_ix0, sig_iy0, sig_ix1, sig_iy1),
                outline=(18, 133, 118, 255),
                width=2,
            )

        if self.stamp_rect is not None and page_width > 0 and page_height > 0:
            tx, ty, tw, th = self.stamp_rect
            stamp_ix0 = tx * scale_x
            stamp_ix1 = (tx + tw) * scale_x
            stamp_iy0 = image_height - (ty + th) * scale_y
            stamp_iy1 = image_height - ty * scale_y
            draw.rectangle(
                (stamp_ix0, stamp_iy0, stamp_ix1, stamp_iy1),
                outline=(204, 0, 0, 255),
                width=2,
            )
            if self.stamp_text:
                draw.text(
                    (stamp_ix0 + 4, stamp_iy0 + 4),
                    self.stamp_text,
                    fill=(204, 0, 0, 220),
                )

        merged = Image.alpha_composite(canvas, overlay).convert("RGB")
        self.preview_label.set_preview_pixmap(QPixmap.fromImage(ImageQt(merged)))

    def _draw_arrow_head(self, draw, x0: float, y0: float, x1: float, y1: float, color) -> None:
        angle = math.atan2(y1 - y0, x1 - x0)
        length = 12
        for offset in (math.pi - 0.5, math.pi + 0.5):
            hx = x1 + length * math.cos(angle + offset)
            hy = y1 + length * math.sin(angle + offset)
            draw.line((x1, y1, hx, hy), fill=color, width=2)

    def _image_point_to_pdf(self, point: QPoint) -> tuple[float, float]:
        page_width, page_height = self.page_size
        image = self.preview_image
        if image is None or page_width <= 0 or page_height <= 0:
            return (0.0, 0.0)
        image_width, image_height = image.size
        ix = min(max(point.x(), 0), image_width)
        iy = min(max(point.y(), 0), image_height)
        pdf_x = ix / image_width * page_width
        pdf_y = page_height - (iy / image_height * page_height)
        return (pdf_x, pdf_y)

    def _markup_color(self) -> tuple[float, float, float]:
        preset = self.markup_color_combo.currentData()
        if preset in MARKUP_COLOR_PRESETS:
            return MARKUP_COLOR_PRESETS[preset]
        return self.markup_color_rgb

    def _on_markup_color_changed(self) -> None:
        preset = self.markup_color_combo.currentData()
        if preset == "custom":
            self._choose_markup_color()
            return
        if preset in MARKUP_COLOR_PRESETS:
            self.markup_color_rgb = MARKUP_COLOR_PRESETS[preset]

    def _choose_markup_color(self) -> None:
        current = QColor.fromRgbF(*self.markup_color_rgb)
        chosen = QColorDialog.getColor(current, self, "選擇標註顏色")
        if not chosen.isValid():
            return
        self.markup_color_rgb = (chosen.redF(), chosen.greenF(), chosen.blueF())
        custom_index = self.markup_color_combo.findData("custom")
        if custom_index >= 0:
            self.markup_color_combo.setCurrentIndex(custom_index)

    def _add_markup_from_rect(self, start: QPoint, end: QPoint) -> None:
        if self.preview_image is None:
            return
        kind = self.markup_tool_combo.currentData() or "highlight"
        if kind == "note":
            self._add_markup_from_point(start)
            return
        self._push_undo_snapshot()
        x0, y0 = self._image_point_to_pdf(start)
        x1, y1 = self._image_point_to_pdf(end)
        markup = MarkupAnnotation(
            kind=kind,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            color_rgb=self._markup_color(),
            contents=self.markup_note_input.text().strip(),
        )
        self.markup_items.append((self.current_page, markup))
        self._refresh_markup_list()
        self._update_preview_display()

    def _add_markup_from_point(self, point: QPoint) -> None:
        if self.preview_image is None:
            return
        kind = self.markup_tool_combo.currentData() or "highlight"
        if kind != "note":
            return
        self._push_undo_snapshot()
        x0, y0 = self._image_point_to_pdf(point)
        markup = MarkupAnnotation(
            kind="note",
            x0=x0,
            y0=y0,
            x1=x0,
            y1=y0,
            color_rgb=self._markup_color(),
            contents=self.markup_note_input.text().strip() or "備註",
        )
        self.markup_items.append((self.current_page, markup))
        self._refresh_markup_list()
        self._update_preview_display()

    def _markup_label(self, markup: MarkupAnnotation) -> str:
        return dict(MARKUP_TOOL_OPTIONS).get(markup.kind, markup.kind)

    def _refresh_markup_list(self) -> None:
        self.markup_pending_list.clear()
        for page_index, markup in self.markup_items:
            label = f"第 {page_index + 1} 頁 · {self._markup_label(markup)}"
            if markup.contents and markup.kind == "note":
                label += f"：{markup.contents[:12]}"
            self.markup_pending_list.addItem(label)

    def _delete_pending_markup(self) -> None:
        row = self.markup_pending_list.currentRow()
        if 0 <= row < len(self.markup_items):
            self._push_undo_snapshot()
            self.markup_items.pop(row)
            self._refresh_markup_list()
            self._update_preview_display()

    def _clear_pending_markups(self) -> None:
        if not self.markup_items:
            return
        self._push_undo_snapshot()
        self.markup_items = []
        self._refresh_markup_list()
        self._update_preview_display()

    def apply_pending_markups(self) -> None:
        if self.pdf_path is None or not self.markup_items:
            self._emit_status("請先載入 PDF 並加入標註。")
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存註解 PDF", safe_output_name("marked-up.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        markups = list(self.markup_items)
        password = self._active_password()

        def job() -> int:
            return apply_markup_annotations(self.pdf_path, target_path, markups, password)

        count = self._run_job(
            job,
            f"已套用 {len(markups)} 個標註。",
            audit_operation="apply_markup",
            audit_target=target_path,
        )
        if count is not None:
            self._offer_reload_output(target_path)

    def _load_text_blocks(self) -> None:
        self.text_block_list.clear()
        self.text_blocks = []
        if self.pdf_path is None or not PYMUPDF_AVAILABLE:
            return
        try:
            self.text_blocks = extract_page_text_blocks(
                self.pdf_path,
                self.current_page,
                self.edit_password_input.text() or self.password,
            )
        except Exception:
            self.text_blocks = []
        for block in self.text_blocks:
            preview = block.text.replace("\n", " ")[:48]
            self.text_block_list.addItem(preview or "(空白)")

    def _on_text_block_selected(self, row: int) -> None:
        if 0 <= row < len(self.text_blocks):
            self.text_replacement_input.setPlainText(self.text_blocks[row].text)

    def _text_block_to_image_rect(self, block: TextBlock) -> tuple[float, float, float, float]:
        if self.preview_image is None:
            return (0.0, 0.0, 0.0, 0.0)
        page_width, page_height = self.page_size
        if page_width <= 0 or page_height <= 0:
            return (0.0, 0.0, 0.0, 0.0)
        scale_x = self.preview_image.width / page_width
        scale_y = self.preview_image.height / page_height
        left = block.x * scale_x
        bottom = self.preview_image.height - block.y * scale_y
        top = bottom - block.height * scale_y
        right = left + block.width * scale_x
        return (left, top, right, bottom)

    def _select_text_block_at_point(self, point: QPoint) -> None:
        if self.preview_image is None:
            return
        best_index = -1
        best_distance = float("inf")
        for index, block in enumerate(self.text_blocks):
            left, top, right, bottom = self._text_block_to_image_rect(block)
            margin = 6
            if left - margin <= point.x() <= right + margin and top - margin <= point.y() <= bottom + margin:
                center_x = (left + right) / 2
                center_y = (top + bottom) / 2
                distance = abs(point.x() - center_x) + abs(point.y() - center_y)
                if distance < best_distance:
                    best_distance = distance
                    best_index = index
        if best_index >= 0:
            self.text_block_list.setCurrentRow(best_index)
            self._emit_status("已從預覽選取文字區塊。")
        else:
            self._emit_status("此位置附近沒有偵測到文字區塊。")

    def _set_crop_rect_from_drag(self, start: QPoint, end: QPoint) -> None:
        if self.preview_image is None:
            self._emit_status("請先載入 PDF 並更新預覽。")
            return
        x0, y0 = self._image_point_to_pdf(start)
        x1, y1 = self._image_point_to_pdf(end)
        left, right = min(x0, x1), max(x0, x1)
        bottom, top = min(y0, y1), max(y0, y1)
        self._set_crop_rect((left, bottom, right, top))
        self._emit_status(f"裁切框：左 {left:.0f} 下 {bottom:.0f} 右 {right:.0f} 上 {top:.0f}")

    def _set_crop_rect(
        self, rect: tuple[float, float, float, float], update_inputs: bool = True
    ) -> None:
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
        self._update_preview_display()

    def _on_crop_inputs_changed(self) -> None:
        rect = self._crop_rect_from_inputs()
        if rect is not None:
            self.crop_rect = rect
            self._update_preview_display()

    def _crop_rect_from_inputs(self) -> tuple[float, float, float, float] | None:
        try:
            left = float(self.crop_left_input.text())
            bottom = float(self.crop_bottom_input.text())
            right = float(self.crop_right_input.text())
            top = float(self.crop_top_input.text())
        except ValueError:
            return None
        return (left, bottom, right, top)

    def _reset_crop_rect(self) -> None:
        page_width, page_height = self.page_size
        if page_width <= 0 or page_height <= 0:
            return
        self._set_crop_rect((0.0, 0.0, page_width, page_height))

    def _on_crop_scope_changed(self) -> None:
        self.crop_pages_input.setEnabled(self.crop_scope_combo.currentData() == "spec")

    def apply_crop(self) -> None:
        if self.pdf_path is None:
            self._emit_status("請先載入 PDF。")
            return
        rect = self._crop_rect_from_inputs()
        if rect is None:
            self._emit_status("裁切框數值無效，請重新框選或輸入數字。")
            return
        scope = self.crop_scope_combo.currentData()
        if scope == "current":
            pages_spec = str(self.current_page + 1)
        elif scope == "spec":
            pages_spec = self.crop_pages_input.text().strip()
            if not pages_spec:
                self._emit_status("請輸入要裁切的頁碼範圍。")
                return
        else:
            pages_spec = ""
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存裁切 PDF", safe_output_name("cropped.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        password = self.crop_password_input.text() or self.password

        def job() -> int:
            return crop_pdf_pages(self.pdf_path, target_path, rect, pages_spec, password)

        cropped = self._run_job(job, "裁切完成。", audit_operation="crop", audit_target=target_path)
        if cropped is not None:
            self._emit_status(f"已裁切 {cropped} 頁。")
            self._offer_reload_output(target_path)

    def choose_signature_image(self) -> None:
        image_path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇簽名 / 印章圖片",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not image_path:
            return
        self.signature_image_path = Path(image_path)
        self.signature_rect = None
        self.interaction = "signature"
        self._update_preview_display()
        self._emit_status("請在預覽上拖曳框選簽名位置。")

    def _set_signature_rect_from_drag(self, start: QPoint, end: QPoint) -> None:
        if self.preview_image is None or self.signature_image_path is None:
            self._emit_status("請先選擇簽名圖片。")
            return
        x0, y0 = self._image_point_to_pdf(start)
        x1, y1 = self._image_point_to_pdf(end)
        left, right = min(x0, x1), max(x0, x1)
        bottom, top = min(y0, y1), max(y0, y1)
        width = max(right - left, 1.0)
        height = max(top - bottom, 1.0)
        self.signature_rect = (left, bottom, width, height)
        self._update_preview_display()
        self._emit_status(f"簽名框：x={left:.0f} y={bottom:.0f} w={width:.0f} h={height:.0f}")

    def cancel_pending_signature(self) -> None:
        self.signature_rect = None
        self.signature_image_path = None
        tools_index = MODE_IDS.index("tools")
        if self.mode_group.checkedId() == tools_index:
            self.interaction = MODE_DEFAULT_INTERACTION["tools"]
        self._update_preview_display()
        self._emit_status("已取消待套用簽名。")

    def apply_signature_to_pdf(self) -> None:
        if self.pdf_path is None:
            self._emit_status("請先載入 PDF。")
            return
        if self.signature_image_path is None:
            self._emit_status("請先選擇簽名圖片。")
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存 PDF", safe_output_name("signed.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        password = self.tools_password_input.text() or self.password
        if self.signature_rect is not None:
            x, y, width, height = self.signature_rect
        else:
            page_width = self.page_size[0] or 612.0
            x = 72.0
            y = 120.0
            width = min(180.0, page_width * 0.35)
            height = width * 0.35
        image_path = self.signature_image_path

        def job() -> None:
            add_signature_image(
                self.pdf_path,
                target_path,
                image_path,
                self.current_page,
                x,
                y,
                width,
                height,
                password,
            )

        if self._run_job(job, "已加入簽名影像。", audit_operation="signature_image", audit_target=target_path) is not None:
            self._offer_reload_output(target_path)

    def _stamp_text_value(self) -> str:
        if self.stamp_preset_combo.currentData() == "custom":
            return self.stamp_custom_input.text().strip()
        return str(self.stamp_preset_combo.currentData() or "").strip()

    def start_text_stamp_placement(self) -> None:
        text = self._stamp_text_value()
        if not text:
            self._emit_status("請輸入或選擇圖章文字。")
            return
        self.stamp_text = text
        self.stamp_rect = None
        self.interaction = "text_stamp"
        self.preview_label.band_color = QColor(204, 0, 0)
        self._update_preview_display()
        self._emit_status("請在預覽上拖曳框選圖章位置。")

    def _set_stamp_rect_from_drag(self, start: QPoint, end: QPoint) -> None:
        if self.preview_image is None or not self.stamp_text:
            self._emit_status("請先選擇圖章文字。")
            return
        x0, y0 = self._image_point_to_pdf(start)
        x1, y1 = self._image_point_to_pdf(end)
        left, right = min(x0, x1), max(x0, x1)
        bottom, top = min(y0, y1), max(y0, y1)
        width = max(right - left, 1.0)
        height = max(top - bottom, 1.0)
        self.stamp_rect = (left, bottom, width, height)
        self._update_preview_display()
        self._emit_status(f"圖章框：x={left:.0f} y={bottom:.0f} w={width:.0f} h={height:.0f}")

    def cancel_pending_text_stamp(self) -> None:
        self.stamp_rect = None
        self.stamp_text = ""
        tools_index = MODE_IDS.index("tools")
        if self.mode_group.checkedId() == tools_index:
            self.interaction = MODE_DEFAULT_INTERACTION["tools"]
        self._update_preview_display()
        self._emit_status("已取消待套用圖章。")

    def apply_text_stamp_to_pdf(self) -> None:
        if self.pdf_path is None:
            self._emit_status("請先載入 PDF。")
            return
        text = self.stamp_text or self._stamp_text_value()
        if not text:
            self._emit_status("請輸入或選擇圖章文字。")
            return
        if not PYMUPDF_AVAILABLE:
            self._emit_status("文字圖章需要 PyMuPDF。")
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存 PDF", safe_output_name("stamped.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        password = self.tools_password_input.text() or self.password
        if self.stamp_rect is not None:
            x, y, width, height = self.stamp_rect
        else:
            page_width = self.page_size[0] or 612.0
            x = 72.0
            y = 120.0
            width = min(180.0, page_width * 0.35)
            height = max(36.0, width * 0.28)
        stamp_text = text

        def job() -> None:
            add_text_stamp(
                self.pdf_path,
                target_path,
                stamp_text,
                self.current_page,
                x,
                y,
                width,
                height,
                password=password,
            )

        if self._run_job(
            job,
            "已加入文字圖章。",
            audit_operation="text_stamp",
            audit_target=target_path,
            audit_detail=stamp_text,
        ) is not None:
            self._offer_reload_output(target_path)

    def replace_selected_text_block(self) -> None:
        if self.pdf_path is None:
            return
        row = self.text_block_list.currentRow()
        if row < 0 or row >= len(self.text_blocks):
            self._emit_status("請選取要替換的文字區塊。")
            return
        replacement = self.text_replacement_input.toPlainText().strip()
        if not replacement:
            self._emit_status("請輸入替換文字。")
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存編輯 PDF", safe_output_name("edited.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        block = self.text_blocks[row]
        password = self.edit_password_input.text() or self.password

        def job() -> None:
            replace_text_block_seamless(
                self.pdf_path,
                target_path,
                self.current_page,
                block,
                replacement,
                password,
            )

        if self._run_job(job, "已替換文字區塊。", audit_operation="replace_text", audit_target=target_path) is not None:
            self._offer_reload_output(target_path)

    def flatten_forms(self) -> None:
        if self.pdf_path is None:
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存壓平 PDF", safe_output_name("flattened.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        password = self._active_password()

        def job() -> int:
            return flatten_form_fields(self.pdf_path, target_path, password)

        if self._run_job(job, "已壓平表單欄位。", audit_operation="flatten_forms", audit_target=target_path) is not None:
            self._offer_reload_output(target_path)

    def search_and_highlight(self) -> None:
        if self.pdf_path is None:
            return
        query = self.read_search_input.text().strip()
        if not query:
            self._emit_status("請輸入搜尋文字。")
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存標註 PDF", safe_output_name("search-marked.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        password = self.read_password_input.text() or self.password

        def job() -> int:
            return apply_text_markups_for_query(self.pdf_path, target_path, query, password=password)

        count = self._run_job(
            job,
            "搜尋標註完成。",
            audit_operation="search_markup",
            audit_target=target_path,
            audit_detail=query,
        )
        if count is not None:
            self._emit_status(f"已標註 {count} 處符合文字。")
            self._offer_reload_output(target_path)

    def secure_redact_keyword(self) -> None:
        if self.pdf_path is None:
            return
        query = self.read_search_input.text().strip()
        if not query:
            self._emit_status("請輸入要塗銷的關鍵字。")
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存塗銷 PDF", safe_output_name("redacted.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        password = self.read_password_input.text() or self.password

        def job() -> int:
            return secure_redact_query(self.pdf_path, target_path, query, password)

        count = self._run_job(
            job,
            "安全塗銷完成。",
            audit_operation="secure_redact",
            audit_target=target_path,
            audit_detail=query,
        )
        if count is not None:
            self._emit_status(f"已塗銷 {count} 處符合文字。")
            self._offer_reload_output(target_path)

    def insert_pages(self) -> None:
        if self.pdf_path is None:
            return
        insert_from, _ = QFileDialog.getOpenFileName(self, "選擇要插入的 PDF", "", "PDF files (*.pdf)")
        if not insert_from:
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存 PDF", safe_output_name("inserted.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        pages_spec = self.organize_insert_pages_input.text().strip()
        password = self.organize_password_input.text() or self.password

        def job() -> int:
            return insert_pdf_pages(
                self.pdf_path,
                Path(insert_from),
                target_path,
                at_index=self.current_page,
                pages_spec=pages_spec,
                password=password,
            )

        inserted = self._run_job(job, "插入頁面完成。", audit_operation="insert_pages", audit_target=target_path)
        if inserted is not None:
            self._emit_status(f"已插入 {inserted} 頁。")
            self._offer_reload_output(target_path)

    def replace_pages(self) -> None:
        if self.pdf_path is None:
            return
        replacement, _ = QFileDialog.getOpenFileName(self, "選擇取代來源 PDF", "", "PDF files (*.pdf)")
        if not replacement:
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存 PDF", safe_output_name("replaced.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        pages_spec = self.organize_insert_pages_input.text().strip()
        password = self.organize_password_input.text() or self.password

        def job() -> int:
            return replace_pdf_pages(
                self.pdf_path,
                Path(replacement),
                target_path,
                start_index=self.current_page,
                pages_spec=pages_spec,
                password=password,
            )

        replaced = self._run_job(job, "取代頁面完成。", audit_operation="replace_pages", audit_target=target_path)
        if replaced is not None:
            self._emit_status(f"已取代 {replaced} 頁。")
            self._offer_reload_output(target_path)

    def rotate_current_page(self, angle: int) -> None:
        if self.pdf_path is None:
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存 PDF", safe_output_name("rotated.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        page_spec = str(self.current_page + 1)
        password = self.organize_password_input.text() or self.password

        def job() -> None:
            rotate_pdf_pages(self.pdf_path, target_path, angle, page_spec, password)

        if self._run_job(job, "已旋轉目前頁。", audit_operation="rotate", audit_target=target_path) is not None:
            self._offer_reload_output(target_path)

    def delete_current_page(self) -> None:
        if self.pdf_path is None:
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存 PDF", safe_output_name("deleted.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        page_spec = str(self.current_page + 1)
        password = self.organize_password_input.text() or self.password

        def job() -> None:
            delete_pdf_pages(self.pdf_path, target_path, page_spec, password)

        if self._run_job(job, "已刪除目前頁。", audit_operation="delete", audit_target=target_path) is not None:
            self._offer_reload_output(target_path)

    def compress_advanced(self) -> None:
        if self.pdf_path is None:
            return
        self._push_undo_snapshot()
        target, _ = QFileDialog.getSaveFileName(
            self, "另存壓縮 PDF", safe_output_name("compressed.pdf"), "PDF files (*.pdf)"
        )
        if not target:
            return
        target_path = Path(target)
        password = self.tools_password_input.text() or self.password

        def job() -> tuple[int, int]:
            return compress_pdf_advanced(self.pdf_path, target_path, password=password)

        result = self._run_job(job, "進階壓縮完成。", audit_operation="compress_advanced", audit_target=target_path)
        if result is not None:
            old_size, new_size = result
            self._emit_status(f"大小 {old_size} → {new_size} bytes")
            self._offer_reload_output(target_path)

    def compare_pdf(self) -> None:
        if self.pdf_path is None:
            return
        other, _ = QFileDialog.getOpenFileName(self, "選擇要比對的 PDF", "", "PDF files (*.pdf)")
        if not other:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "另存比對報告", safe_output_name("compare-report.txt"), "Text files (*.txt)"
        )
        if not target:
            return
        target_path = Path(target)
        password = self.tools_password_input.text() or self.password

        def job() -> int:
            return compare_pdf_text(self.pdf_path, Path(other), target_path, password)

        diff_count = self._run_job(job, "文字比對完成。", audit_operation="compare_text", audit_target=target_path)
        if diff_count is not None:
            self._emit_status(f"共有 {diff_count} 頁文字不同；報告已儲存。")

    def split_by_bookmarks(self) -> None:
        if self.pdf_path is None:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, "另存 ZIP", safe_output_name("bookmark-split.zip"), "ZIP files (*.zip)"
        )
        if not target:
            return
        target_path = Path(target)
        password = self.tools_password_input.text() or self.password

        def job() -> int:
            return split_pdf_by_bookmarks(self.pdf_path, target_path, password)

        count = self._run_job(job, "依書籤拆分完成。", audit_operation="split_bookmarks", audit_target=target_path)
        if count is not None:
            self._emit_status(f"已拆分為 {count} 個檔案。")

    def _run_job(
        self,
        job,
        success_message: str,
        *,
        audit_operation: str = "",
        audit_target: Path | None = None,
        audit_detail: str = "",
    ):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = job()
        except Exception as exc:
            QMessageBox.critical(self, "文件工作台", str(exc))
            return None
        finally:
            QApplication.restoreOverrideCursor()
        self._emit_status(success_message)
        if audit_operation and self.pdf_path is not None:
            append_audit_event(
                audit_operation,
                self.pdf_path.name,
                audit_target.name if audit_target else "",
                audit_detail,
            )
        return result

    def _offer_reload_output(self, output_path: Path) -> None:
        answer = QMessageBox.question(
            self,
            "文件工作台",
            f"已儲存：{output_path.name}\n要重新載入輸出檔嗎？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self.open_path(output_path)

    def _emit_status(self, message: str) -> None:
        self.status_changed.emit(message)
