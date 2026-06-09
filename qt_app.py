from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QByteArray, QMimeData, QPoint, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QDragEnterEvent, QDropEvent, QIcon, QIntValidator, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
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
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pdf_core import (
    IMAGE_SUFFIXES,
    OCR_LANGUAGE_OPTIONS,
    PDF_RENDER_AVAILABLE,
    PDF_SUFFIXES,
    PageItem,
    TextBlock,
    add_page_numbers,
    ANNOTATION_COLOR_PRESETS,
    add_text_overlay_annotation,
    add_watermark,
    rgb_to_hex,
    clean_metadata,
    compress_pdf,
    decrypt_pdf,
    delete_pdf_pages,
    encrypt_pdf,
    extract_pdf_pages,
    extract_page_text_blocks,
    extract_pdf_text,
    images_to_pdf,
    merge_pdf_files,
    ocr_pdf_to_searchable_pdf,
    ocr_pdf_to_text,
    pdf_to_images,
    open_reader,
    page_item_label,
    parse_pages,
    pdfium,
    redact_text_block_secure,
    redact_text_block_overlay,
    remove_blank_pages,
    replace_text_block_content_stream,
    replace_text_block_overlay,
    rotate_pdf_pages,
    safe_output_name,
    split_pdf_to_zip,
    write_page_items_merged,
    write_page_items_separately,
    write_pdf_info,
)

TOOL_OPERATIONS = [
    ("merge", "合併 PDF"),
    ("split", "逐頁拆分 (ZIP)"),
    ("extract", "抽取頁碼"),
    ("delete", "刪除頁碼"),
    ("rotate", "旋轉頁面"),
    ("encrypt", "加密 PDF"),
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
]

PDF_OUTPUT_OPERATIONS = frozenset(
    {
        "merge",
        "extract",
        "delete",
        "rotate",
        "encrypt",
        "decrypt",
        "compress",
        "images_to_pdf",
        "add_page_numbers",
        "watermark",
        "remove_blank_pages",
        "clean_metadata",
        "ocr_searchable_pdf",
    }
)

FOLDER_REVEAL_OPERATIONS = frozenset({"split", "extract_text", "ocr_text", "info", "pdf_to_images"})

SETTINGS_ORG = "VictorSuen"
SETTINGS_APP = "VictorPDFToolsBox"


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

THUMB_SIZE = QSize(195, 292)
ICON_SIZE = QSize(165, 215)
ANNOT_PREVIEW_MAX_WIDTH = 760
ANNOT_PREVIEW_MAX_HEIGHT = 760
ANNOT_PREVIEW_OFFSET = 12


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


class AnnotationPreviewLabel(QLabel):
    positionClicked = Signal(QPoint)

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setStyleSheet("background: #f6f8fb; border: 1px solid #dce3ec;")

    def mousePressEvent(self, event) -> None:
        self.positionClicked.emit(event.position().toPoint())
        super().mousePressEvent(event)


class TextEditPreviewLabel(QLabel):
    positionClicked = Signal(QPoint)

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setStyleSheet("background: #f6f8fb; border: 1px solid #dce3ec;")

    def mousePressEvent(self, event) -> None:
        self.positionClicked.emit(event.position().toPoint())
        super().mousePressEvent(event)


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
    reorderRequested = Signal(list, int)
    PAGE_DRAG_MIME = "application/x-victor-pdf-pages"

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropMode(QListWidget.DragDrop)
        self.setDragDropOverwriteMode(False)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setViewMode(QListWidget.IconMode)
        self.setMovement(QListWidget.Static)
        self.setResizeMode(QListWidget.Adjust)
        self.setWrapping(True)
        self.setSpacing(24)
        self.setIconSize(ICON_SIZE)
        self.setGridSize(THUMB_SIZE)
        self.setUniformItemSizes(True)
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

    def startDrag(self, supported_actions) -> None:
        source_rows = sorted(self.row(item) for item in self.selectedItems())
        if not source_rows:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(self.PAGE_DRAG_MIME, QByteArray(",".join(str(row) for row in source_rows).encode("ascii")))
        drag.setMimeData(mime)
        drag.setPixmap(self.drag_pixmap_for_rows(source_rows))
        drag.setHotSpot(QPoint(drag.pixmap().width() // 2, drag.pixmap().height() // 2))
        drag.exec(Qt.MoveAction)

    def drag_pixmap_for_rows(self, source_rows: list[int]) -> QPixmap:
        first_item = self.item(source_rows[0])
        pixmap = first_item.icon().pixmap(ICON_SIZE)
        preview = pixmap.scaled(105, 136, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if len(source_rows) > 1:
            stacked = QPixmap(preview.width() + 18, preview.height() + 18)
            stacked.fill(Qt.transparent)
            from PySide6.QtGui import QPainter

            painter = QPainter(stacked)
            painter.drawPixmap(18, 18, preview)
            painter.drawPixmap(0, 0, preview)
            painter.end()
            return stacked
        return preview

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.source() is self and event.mimeData().hasFormat(self.PAGE_DRAG_MIME):
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.source() is self and event.mimeData().hasFormat(self.PAGE_DRAG_MIME):
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
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
        if event.source() is self and event.mimeData().hasFormat(self.PAGE_DRAG_MIME):
            raw_rows = bytes(event.mimeData().data(self.PAGE_DRAG_MIME)).decode("ascii")
            source_rows = sorted(int(row) for row in raw_rows.split(",") if row)
            if not source_rows:
                event.ignore()
                return
            self.reorderRequested.emit(source_rows, self.drop_target_row(event))
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def drop_target_row(self, event: QDropEvent) -> int:
        return self.row_from_point(event.position().toPoint())

    def row_from_point(self, point: QPoint) -> int:
        item = self.itemAt(point)
        if item is None:
            return self.count()
        row = self.row(item)
        rect = self.visualItemRect(item)
        if point.y() > rect.center().y() or point.x() > rect.center().x():
            return row + 1
        return row


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
        self.resize(760, 520)

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
        self.resize(980, 820)

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        image = parent.render_page_preview(item)
        label.setPixmap(QPixmap.fromImage(ImageQt(image)))
        scroll.setWidget(label)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class VictorPdfToolsQt(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Victor PDF Tools Box")
        self.resize(1280, 820)
        self.setAcceptDrops(True)

        self.workspaces: dict[PageGrid, dict] = {}
        self.page_grid: PageGrid | None = None
        self.page_items: list[PageItem] = []
        self.thumbnail_cache: dict[tuple[str, int, int], QIcon] = {}
        self.page_clipboard: list[PageItem] = []
        self.tool_file_items: list[Path] = []
        self._last_tool_status_message = ""
        self.annotation_pdf_path: Path | None = None
        self.annotation_page_count = 0
        self.annotation_page_size = (0.0, 0.0)
        self.annotation_preview_image: Image.Image | None = None
        self.annotation_color_rgb = (0.0, 0.0, 0.0)
        self.text_edit_pdf_path: Path | None = None
        self.text_edit_page_count = 0
        self.text_edit_blocks: list[TextBlock] = []
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
        self.setStatusBar(QStatusBar())
        self.create_document_tab("未命名")
        self.set_status("把 PDF 直接拖入縮圖區；每個 PDF 會像 DC 一樣開成獨立文件 Tab。")

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
            self.add_files_from_paths(self.paths_from_drop_event(event))
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def has_pdf_urls(self, event) -> bool:
        if not event.mimeData().hasUrls():
            return False
        return any(Path(url.toLocalFile()).suffix.lower() == ".pdf" for url in event.mimeData().urls())

    def paths_from_drop_event(self, event: QDropEvent) -> list[str]:
        return [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile()]

    def build_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #e9e7e1; color: #111; font-size: 10.5pt; }
            QLabel#title { font-size: 23pt; font-weight: 700; }
            QLabel#muted { color: #52697a; }
            QPushButton {
                min-height: 30px;
                padding: 4px 12px;
                border: 1px solid #9f9d96;
                border-radius: 6px;
                background: #f7f6f2;
            }
            QPushButton:hover { background: #ffffff; border-color: #128576; }
            QPushButton#primary { background: #128576; color: #ffffff; border-color: #0d6f63; }
            QPushButton#danger { color: #9d2828; }
            QLineEdit, QComboBox {
                min-height: 30px;
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
            """
        )

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("Victor PDF Tools Box")
        title.setObjectName("title")
        subtitle = QLabel("第二代 Qt 介面：本機處理 PDF，支援文件 Tab、縮圖重排、旋轉、擷取與合併。")
        subtitle.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.addTab(self.build_organize_tab(), "組織 / 擷取")
        tabs.addTab(self.build_tools_tab(), "常用 PDF 工具")
        tabs.addTab(self.build_annotation_tab(), "文字標註 / 覆蓋")
        tabs.addTab(self.build_text_edit_tab(), "文字編輯 Beta")
        layout.addWidget(tabs, 1)
        self.setCentralWidget(root)

        open_action = QAction("加入 PDF", self)
        open_action.triggered.connect(self.choose_pdf_files)
        self.addAction(open_action)
        self.load_output_preferences()

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

    def build_organize_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        controls = QHBoxLayout()
        self.add_button(controls, "加入 PDF", self.choose_pdf_files)
        self.add_button(controls, "複製頁", self.copy_selected_pages)
        self.add_button(controls, "剪下頁", self.cut_selected_pages)
        self.add_button(controls, "貼上頁", self.paste_pages)
        self.add_button(controls, "復原", self.undo_last_action)
        self.add_button(controls, "刪除頁", self.remove_selected_pages, "danger")
        self.add_button(controls, "清空目前 Tab", self.clear_pages)
        controls.addSpacing(10)
        self.add_button(controls, "選取左轉", lambda: self.rotate_selected_pages(270))
        self.add_button(controls, "選取右轉", lambda: self.rotate_selected_pages(90))
        controls.addStretch(1)
        controls.addWidget(self.stats_label)
        left_layout.addLayout(controls)

        self.document_tabs = PdfDropTabWidget()
        self.document_tabs.filesDropped.connect(self.add_files_from_paths)
        self.document_tabs.setTabsClosable(True)
        self.document_tabs.currentChanged.connect(self.on_document_tab_changed)
        self.document_tabs.tabCloseRequested.connect(self.close_document_tab)
        left_layout.addWidget(self.document_tabs, 1)
        layout.addWidget(left, 1)

        side = QFrame()
        side.setObjectName("panel")
        side.setFixedWidth(270)
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
        layout.addWidget(side)
        return tab

    def build_tools_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        controls = QHBoxLayout()
        self.add_button(controls, "加入 PDF", self.add_tool_pdf_files)
        self.add_button(controls, "加入圖片", self.add_tool_image_files)
        self.add_button(controls, "移除選取", self.remove_tool_files, "danger")
        self.add_button(controls, "上移", lambda: self.move_tool_file(-1))
        self.add_button(controls, "下移", lambda: self.move_tool_file(1))
        self.add_button(controls, "清空", self.clear_tool_files, "danger")
        controls.addStretch(1)
        layout.addLayout(controls)

        body = QHBoxLayout()
        body.setSpacing(14)

        self.tool_file_list = ToolFileList()
        self.tool_file_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.tool_file_list.filesDropped.connect(self.drop_tool_files)
        body.addWidget(self.tool_file_list, 1)

        form = QFrame()
        form.setObjectName("panel")
        form.setFixedWidth(300)
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setSpacing(10)

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
        self.tool_ocr_language_combo.setCurrentIndex(self.tool_ocr_language_combo.findData("eng+chi_tra"))
        form_layout.addWidget(self.tool_ocr_language_combo)

        form_layout.addWidget(QLabel("文字 / 模板"))
        self.tool_batch_text_input = QLineEdit("CONFIDENTIAL")
        form_layout.addWidget(self.tool_batch_text_input)
        template_hint = QLabel("頁碼模板可用 {page} / {total}")
        template_hint.setObjectName("muted")
        template_hint.setWordWrap(True)
        form_layout.addWidget(template_hint)

        form_layout.addWidget(QLabel("空白頁靈敏度"))
        self.tool_blank_threshold_combo = QComboBox()
        for value in ("10", "15", "25", "50", "100", "200", "500"):
            self.tool_blank_threshold_combo.addItem(value)
        self.tool_blank_threshold_combo.setCurrentText("25")
        form_layout.addWidget(self.tool_blank_threshold_combo)

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

        hint = QLabel("提示：可把 PDF / 圖片直接拖入左側清單；合併 / 圖片轉 PDF 可加入多個檔案，其餘工具使用清單第一個 PDF。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form_layout.addWidget(hint)
        form_layout.addStretch(1)
        body.addWidget(form)
        layout.addLayout(body, 1)
        return tab

    def build_annotation_tab(self) -> QWidget:
        tab = PdfDropPanel()
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
        self.annotation_page_input.editingFinished.connect(self.render_annotation_preview)
        top.addWidget(self.annotation_page_input)
        self.add_button(top, "更新預覽", self.render_annotation_preview)
        top.addStretch(1)
        left.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.annotation_preview_label = AnnotationPreviewLabel()
        self.annotation_preview_label.positionClicked.connect(self.set_annotation_position_from_click)
        scroll.setWidget(self.annotation_preview_label)
        left.addWidget(scroll, 1)
        layout.addLayout(left, 1)

        side = QFrame()
        side.setObjectName("panel")
        side.setFixedWidth(320)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

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
        self.annotation_font_combo.addItem("Helvetica", "helvetica")
        self.annotation_font_combo.addItem("Times New Roman", "times")
        self.annotation_font_combo.addItem("Courier", "courier")
        side_layout.addWidget(self.annotation_font_combo)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("大小"))
        self.annotation_font_size_combo = QComboBox()
        for size in ("8", "10", "12", "14", "16", "18", "24", "36"):
            self.annotation_font_size_combo.addItem(size)
        self.annotation_font_size_combo.setCurrentText("12")
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

        side_layout.addWidget(QLabel("X / Y 位置"))
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

        side_layout.addWidget(QLabel("PDF 密碼（如適用）"))
        self.annotation_password_input = QLineEdit()
        self.annotation_password_input.setEchoMode(QLineEdit.Password)
        side_layout.addWidget(self.annotation_password_input)

        save_button = self.add_button(side_layout, "套用並另存 PDF", self.save_annotation_pdf, "primary")
        save_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        guide = QLabel("提示：左側會即時預覽白底覆蓋與文字效果；點擊預覽可調整位置。也可直接把 PDF 拖入此分頁。")
        guide.setObjectName("muted")
        guide.setWordWrap(True)
        side_layout.addWidget(guide)
        side_layout.addStretch(1)
        layout.addWidget(side)
        self.connect_annotation_preview_updates()
        return tab

    def connect_annotation_preview_updates(self) -> None:
        self.annotation_text_input.textChanged.connect(self.update_annotation_preview_display)
        self.annotation_cover_checkbox.toggled.connect(self.update_annotation_preview_display)
        self.annotation_font_combo.currentIndexChanged.connect(self.update_annotation_preview_display)
        self.annotation_font_size_combo.currentTextChanged.connect(self.update_annotation_preview_display)
        self.annotation_bold_checkbox.toggled.connect(self.update_annotation_preview_display)
        self.annotation_color_combo.currentIndexChanged.connect(self.on_annotation_color_preset_changed)
        self.annotation_color_button.clicked.connect(self.choose_annotation_color)
        self.annotation_x_input.textChanged.connect(self.update_annotation_preview_display)
        self.annotation_y_input.textChanged.connect(self.update_annotation_preview_display)
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
        return {
            "text": self.annotation_text_input.toPlainText(),
            "cover": self.annotation_cover_checkbox.isChecked(),
            "font_key": self.annotation_font_combo.currentData() or "helvetica",
            "font_size": int(self.annotation_font_size_combo.currentText()),
            "bold": self.annotation_bold_checkbox.isChecked(),
            "color_rgb": self.annotation_color_rgb,
            "pdf_x": pdf_x,
            "pdf_y": pdf_y,
            "rect_width": rect_width,
            "rect_height": rect_height,
        }

    def annotation_preview_font(
        self,
        font_size_pt: float,
        bold: bool,
        font_key: str,
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        windows_fonts = Path("C:/Windows/Fonts")
        font_files = {
            "helvetica": ("arialbd.ttf", "arial.ttf"),
            "times": ("timesbd.ttf", "times.ttf"),
            "courier": ("courbd.ttf", "cour.ttf"),
        }
        bold_name, regular_name = font_files.get(font_key, font_files["helvetica"])
        primary = windows_fonts / (bold_name if bold else regular_name)
        candidates = [
            primary,
            windows_fonts / ("msyhbd.ttc" if bold else "msyh.ttc"),
            windows_fonts / ("arialbd.ttf" if bold else "arial.ttf"),
        ]
        size = max(int(font_size_pt), 8)
        for path in candidates:
            if path.exists():
                try:
                    return ImageFont.truetype(str(path), size=size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def draw_annotation_overlay_on_image(self, image: Image.Image, style: dict) -> Image.Image:
        page_width, page_height = self.annotation_page_size
        if page_width <= 0 or page_height <= 0:
            return image
        canvas = image.copy()
        draw = ImageDraw.Draw(canvas)
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

        if style["cover"]:
            draw.rectangle((left, top, right, bottom), fill="#ffffff", outline="#b7c4ce", width=1)

        text = style["text"].strip()
        if text:
            preview_font_size = max(style["font_size"] * scale_y * 0.92, 8)
            font = self.annotation_preview_font(preview_font_size, style["bold"], style["font_key"])
            text_color = rgb_to_hex(style["color_rgb"])
            draw.text((left + 4, top + 2), text, fill=text_color, font=font)
        return canvas

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
        self.text_edit_page_input.editingFinished.connect(self.refresh_text_edit_page)
        top.addWidget(self.text_edit_page_input)
        self.add_button(top, "偵測文字", self.refresh_text_edit_page)
        top.addStretch(1)
        left.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.text_edit_preview_label = TextEditPreviewLabel()
        self.text_edit_preview_label.positionClicked.connect(self.select_text_edit_block_at_point)
        scroll.setWidget(self.text_edit_preview_label)
        left.addWidget(scroll, 1)
        layout.addLayout(left, 1)

        side = QFrame()
        side.setObjectName("panel")
        side.setFixedWidth(360)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(10)

        side_layout.addWidget(QLabel("搜尋文字"))
        search_row = QHBoxLayout()
        self.text_edit_search_input = QLineEdit()
        self.text_edit_search_input.setPlaceholderText("輸入要尋找的文字")
        self.text_edit_search_input.returnPressed.connect(self.find_next_text_edit_block)
        search_row.addWidget(self.text_edit_search_input, 1)
        self.add_button(search_row, "下一個", self.find_next_text_edit_block)
        side_layout.addLayout(search_row)

        side_layout.addWidget(QLabel("偵測到的文字片段"))
        self.text_edit_block_list = QListWidget()
        self.text_edit_block_list.currentRowChanged.connect(self.on_text_edit_block_selected)
        side_layout.addWidget(self.text_edit_block_list, 1)

        self.text_edit_block_info = QLabel("選取文字片段後可替換。")
        self.text_edit_block_info.setObjectName("muted")
        self.text_edit_block_info.setWordWrap(True)
        side_layout.addWidget(self.text_edit_block_info)

        side_layout.addWidget(QLabel("替換成"))
        self.text_edit_replacement_input = QTextEdit()
        self.text_edit_replacement_input.setFixedHeight(80)
        side_layout.addWidget(self.text_edit_replacement_input)

        side_layout.addWidget(QLabel("替換方式"))
        self.text_edit_mode_combo = QComboBox()
        self.text_edit_mode_combo.addItem("覆蓋替換（最穩定）", "overlay")
        self.text_edit_mode_combo.addItem("直接改內容流（實驗：英文/數字同長度）", "content_stream")
        side_layout.addWidget(self.text_edit_mode_combo)

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

        guide = QLabel(
            "Beta：覆蓋替換最穩定；安全遮蔽會嘗試移除簡單英文/數字底層文字再加黑框；直接改內容流只適合簡單英文/數字且新舊長度相同，"
            "可保留原文字樣式。掃描 PDF 請先用 OCR 轉可搜尋 PDF。"
        )
        guide.setObjectName("muted")
        guide.setWordWrap(True)
        side_layout.addWidget(guide)
        layout.addWidget(side)
        return tab

    def load_text_edit_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "載入 PDF", "", "PDF files (*.pdf)")
        if path:
            self.set_text_edit_pdf(Path(path))

    def drop_text_edit_pdf(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() in PDF_SUFFIXES]
        if not pdf_paths:
            self.set_status("請拖放 PDF 檔案到文字編輯分頁。")
            return
        self.set_text_edit_pdf(pdf_paths[0])

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
            self.text_edit_block_info.setText("此頁沒有偵測到文字層。掃描 PDF 請先 OCR。")

    def find_next_text_edit_block(self) -> None:
        query = self.text_edit_search_input.text().strip().lower()
        if not query:
            self.set_status("請輸入要搜尋的文字。")
            return
        if not self.text_edit_blocks:
            self.set_status("此頁沒有可搜尋的文字片段。")
            return

        start = self.text_edit_block_list.currentRow() + 1
        indexes = list(range(start, len(self.text_edit_blocks))) + list(range(0, max(start, 0)))
        matches = [
            index
            for index in indexes
            if query in self.text_edit_blocks[index].text.lower()
        ]
        if not matches:
            self.set_status(f"找不到文字：{self.text_edit_search_input.text().strip()}")
            return
        self.text_edit_block_list.setCurrentRow(matches[0])
        total = sum(1 for block in self.text_edit_blocks if query in block.text.lower())
        self.set_status(f"找到第 {matches[0] + 1} 個文字片段，共 {total} 個符合。")

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
                    scale = min(760 / page_width, 980 / page_height, 1.8)
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
        self.text_edit_block_info.setText(
            f"位置 X {block.x:.1f}, Y {block.y:.1f}；估計字體大小 {block.font_size:.1f}；字型 {block.font_name or '未知'}"
        )
        self.update_text_edit_preview(block)

    def update_text_edit_preview(self, selected_block: TextBlock | None = None) -> None:
        if self.text_edit_preview_image is None:
            self.text_edit_preview_label.clear()
            return
        image = self.text_edit_preview_image.copy()
        if selected_block is not None:
            reader = open_reader(self.text_edit_pdf_path, self.text_edit_password_input.text())
            page = reader.pages[int(self.text_edit_page_input.text() or "1") - 1]
            page_width = float(page.mediabox.width)
            page_height = float(page.mediabox.height)
            draw = ImageDraw.Draw(image)
            scale_x = image.width / page_width
            scale_y = image.height / page_height
            left = selected_block.x * scale_x
            bottom = image.height - selected_block.y * scale_y
            top = bottom - selected_block.height * scale_y
            right = left + selected_block.width * scale_x
            draw.rectangle((left, top, right, bottom), outline="#0f766e", width=3)
        pixmap = QPixmap.fromImage(ImageQt(image))
        self.text_edit_preview_label.setPixmap(pixmap)
        self.text_edit_preview_label.resize(pixmap.size())

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
        mode = self.text_edit_mode_combo.currentData() or "overlay"
        replacement_job = replace_text_block_overlay
        if mode == "content_stream":
            replacement_job = replace_text_block_content_stream

        self.run_pdf_job(
            lambda: replacement_job(
                self.text_edit_pdf_path,
                target_path,
                int(self.text_edit_page_input.text() or "1") - 1,
                block,
                replacement,
                self.text_edit_password_input.text(),
            ),
            f"已替換文字並另存：{target_path.name}",
            on_success=lambda: self.open_pdf_as_new_tab(target_path),
        )

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

    def save_output_preferences(self) -> None:
        settings = self.output_settings()
        settings.setValue("open_pdf_after_save", self.open_pdf_after_save_checkbox.isChecked())
        settings.setValue("open_folder_after_export", self.open_folder_after_export_checkbox.isChecked())
        settings.setValue("tool_open_pdf_tab", self.tool_open_pdf_tab_checkbox.isChecked())
        settings.setValue("tool_open_output_folder", self.tool_open_output_folder_checkbox.isChecked())

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
        if pdf_paths:
            self.add_tool_files_from_paths(pdf_paths, PDF_SUFFIXES)
        if image_paths:
            self.add_tool_files_from_paths(image_paths, IMAGE_SUFFIXES)
        if not pdf_paths and not image_paths:
            self.set_status("請拖放 PDF 或圖片檔案到工具清單。")

    def load_annotation_pdf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "載入 PDF", "", "PDF files (*.pdf)")
        if path:
            self.set_annotation_pdf(Path(path))

    def drop_annotation_pdf(self, paths: list[str]) -> None:
        pdf_paths = [Path(path) for path in paths if Path(path).suffix.lower() in PDF_SUFFIXES]
        if not pdf_paths:
            self.set_status("請拖放 PDF 檔案到標註分頁。")
            return
        self.set_annotation_pdf(pdf_paths[0])

    def set_annotation_pdf(self, path: Path) -> None:
        try:
            reader = open_reader(path, self.annotation_password_input.text())
        except Exception as exc:
            self.show_error(exc)
            return
        self.annotation_pdf_path = path
        self.annotation_page_count = len(reader.pages)
        self.annotation_page_validator.setRange(1, max(self.annotation_page_count, 1))
        self.annotation_page_input.setText("1")
        self.render_annotation_preview()
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
            scale = min(ANNOT_PREVIEW_MAX_WIDTH / page_width, ANNOT_PREVIEW_MAX_HEIGHT / page_height, 1.25)
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
            return
        style = self.annotation_style_values()
        preview_image = self.draw_annotation_overlay_on_image(self.annotation_preview_image, style)
        pixmap = QPixmap.fromImage(ImageQt(preview_image))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        page_width, page_height = self.annotation_page_size
        image_width, image_height = preview_image.size
        if page_width > 0 and page_height > 0:
            x = style["pdf_x"] / page_width * image_width
            y = (page_height - style["pdf_y"]) / page_height * image_height
            pen = QPen(Qt.GlobalColor.darkCyan, 2)
            painter.setPen(pen)
            painter.drawEllipse(QPoint(int(x), int(y)), 5, 5)
            painter.drawLine(int(x) - 12, int(y), int(x) + 12, int(y))
            painter.drawLine(int(x), int(y) - 12, int(x), int(y) + 12)
        painter.end()
        self.annotation_preview_label.setPixmap(pixmap)
        self.annotation_preview_label.resize(pixmap.size())

    def set_annotation_position_from_click(self, point: QPoint) -> None:
        page_width, page_height = self.annotation_page_size
        if self.annotation_preview_image is None or page_width <= 0 or page_height <= 0:
            return
        image_width, image_height = self.annotation_preview_image.size
        image_x = min(max(point.x(), 0), image_width)
        image_y = min(max(point.y(), 0), image_height)
        pdf_x = image_x / image_width * page_width
        pdf_y = page_height - (image_y / image_height * page_height)
        self.annotation_x_input.setText(f"{pdf_x:.1f}")
        self.annotation_y_input.setText(f"{pdf_y:.1f}")
        self.update_annotation_preview_display()
        self.set_status(f"已設定文字位置：X {pdf_x:.1f}, Y {pdf_y:.1f}")

    def save_annotation_pdf(self) -> None:
        if self.annotation_pdf_path is None:
            self.set_status("請先載入 PDF。")
            return
        text = self.annotation_text_input.toPlainText().strip()
        if not text:
            self.set_status("請輸入標註文字。")
            return
        target, _ = QFileDialog.getSaveFileName(self, "另存標註 PDF", "annotated.pdf", "PDF files (*.pdf)")
        if not target:
            return
        target_path = Path(target)

        style = self.annotation_style_values()

        def job() -> None:
            add_text_overlay_annotation(
                source=self.annotation_pdf_path,
                target=target_path,
                page_index=int(self.annotation_page_input.text() or "1") - 1,
                x=style["pdf_x"],
                y=style["pdf_y"],
                text=text,
                font_size=style["font_size"],
                cover_original=style["cover"],
                cover_width=style["rect_width"],
                cover_height=style["rect_height"],
                password=self.annotation_password_input.text(),
                font_key=style["font_key"],
                bold=style["bold"],
                color_rgb=style["color_rgb"],
            )

        self.run_pdf_job(
            job,
            f"已套用文字標註：{target_path.name}",
            on_success=lambda: self.open_pdf_as_new_tab(target_path),
        )

    def run_tool_operation(self) -> None:
        if not self.tool_file_items:
            self.set_status("請先加入檔案。")
            return
        operation = self.tool_operation.currentData()
        password = self.tool_password_input.text()
        source = self.tool_file_items[0]
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
            extension = ".txt" if operation in {"extract_text", "ocr_text", "info"} else ".pdf"
            if operation == "split":
                extension = ".zip"
            target, _ = QFileDialog.getSaveFileName(
                self,
                "另存輸出檔案",
                safe_output_name(f"{operation}{extension}"),
                f"Output files (*{extension})",
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
        )

    def _execute_tool_operation(self, operation: str, source: Path, target_path: Path, password: str) -> None:
        if operation == "merge":
            merge_pdf_files(self.tool_file_items, target_path, password)
            self._last_tool_status_message = f"已合併 {len(self.tool_file_items)} 個 PDF。"
            return
        if operation == "split":
            page_count = split_pdf_to_zip(source, target_path, password)
            self._last_tool_status_message = f"已拆分 {page_count} 頁並打包成 ZIP。"
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
                language=self.tool_ocr_language_combo.currentData(),
                pages_spec=self.tool_pages_input.text(),
                dpi=int(self.tool_image_dpi_combo.currentText()),
            )
            self._last_tool_status_message = f"已 OCR 抽出 {page_count} 頁文字。"
            return
        elif operation == "ocr_searchable_pdf":
            page_count = ocr_pdf_to_searchable_pdf(
                source,
                target_path,
                password,
                language=self.tool_ocr_language_combo.currentData(),
                pages_spec=self.tool_pages_input.text(),
                dpi=int(self.tool_image_dpi_combo.currentText()),
            )
            self._last_tool_status_message = f"已產生 {page_count} 頁可搜尋 PDF。"
            return
        elif operation == "info":
            write_pdf_info(source, target_path, password)
        elif operation == "add_page_numbers":
            template = self.tool_batch_text_input.text().strip() or "Page {page} of {total}"
            add_page_numbers(source, target_path, template, password)
        elif operation == "watermark":
            add_watermark(source, target_path, self.tool_batch_text_input.text(), password)
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
        else:
            raise ValueError(f"未知工具：{operation}")
        self._last_tool_status_message = f"已完成：{self.tool_operation.currentText()}"

    def add_button(self, layout, text: str, callback, kind: str | None = None) -> QPushButton:
        button = QPushButton(text)
        if kind:
            button.setObjectName(kind)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def create_document_tab(self, title: str) -> PageGrid:
        grid = PageGrid()
        grid.filesDropped.connect(self.add_files_from_paths)
        grid.reorderRequested.connect(lambda rows, target, page_grid=grid: self.reorder_pages(rows, target, page_grid))
        grid.itemSelectionChanged.connect(self.update_stats)
        grid.itemDoubleClicked.connect(lambda list_item, page_grid=grid: self.preview_page_item(page_grid, list_item))
        self.workspaces[grid] = {"items": [], "cache": {}, "pending": [], "generation": 0, "undo": []}
        self.document_tabs.addTab(grid, title)
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
        if isinstance(widget, PageGrid):
            self.workspaces.pop(widget, None)
        self.document_tabs.removeTab(index)
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
            self.set_status(f"已加入 {added_files} 個 PDF，共 {added_pages} 頁。")
        elif skipped:
            self.set_status("沒有加入頁面，請確認檔案是 PDF 或密碼正確。")

    def populate_grid_from_reader(self, path: Path, reader, grid: PageGrid) -> int:
        workspace = self.workspaces[grid]
        workspace["items"].clear()
        workspace["cache"].clear()
        for page_index in range(len(reader.pages)):
            workspace["items"].append(PageItem(path, page_index, f"{path.name} - Page {page_index + 1}"))
        self.rebuild_grid(grid=grid)
        self.document_tabs.setTabText(self.document_tabs.indexOf(grid), path.name)
        return len(reader.pages)

    def open_pdf_as_new_tab(self, path: Path) -> None:
        reader = open_reader(path, self.password_input.text())
        grid = self.create_document_tab(path.name)
        self.populate_grid_from_reader(path, reader, grid)

    def target_grid_for_new_file(self, title: str) -> PageGrid:
        grid = self.current_grid()
        workspace = self.current_workspace()
        if grid is not None and workspace is not None and not workspace["items"] and self.document_tabs.count() == 1:
            self.document_tabs.setTabText(self.document_tabs.indexOf(grid), title)
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

        grid.blockSignals(True)
        grid.clear()
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
                workspace["pending"].append(index)
        grid.blockSignals(False)
        self.update_stats()
        if workspace["pending"]:
            QTimer.singleShot(0, lambda page_grid=grid, token=generation: self.render_next_thumbnails(page_grid, token))

    def render_next_thumbnails(self, grid: PageGrid, generation: int) -> None:
        workspace = self.workspaces.get(grid)
        if not workspace or generation != workspace["generation"]:
            return
        for _ in range(3):
            if not workspace["pending"]:
                return
            index = workspace["pending"].pop(0)
            if index >= len(workspace["items"]) or index >= grid.count():
                continue
            item = workspace["items"][index]
            key = self.thumbnail_key(item)
            icon = workspace["cache"].get(key)
            if icon is None:
                icon = QIcon(QPixmap.fromImage(ImageQt(self.render_page_thumbnail(item))))
                workspace["cache"][key] = icon
            grid.item(index).setIcon(icon)
        if workspace["pending"]:
            QTimer.singleShot(1, lambda page_grid=grid, token=generation: self.render_next_thumbnails(page_grid, token))

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
        label = f"Page {index + 1}\n原頁 {item.page_index + 1}\n{item.pdf_path.name}"
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

    def run_pdf_job(self, job, success_message: str, on_success=None) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            job()
        except Exception as exc:
            self.show_error(exc)
        else:
            if on_success is not None:
                on_success()
            if success_message:
                self.set_status(success_message)
        finally:
            QApplication.restoreOverrideCursor()

    def thumbnail_key(self, item: PageItem) -> tuple[str, int, int]:
        return (str(item.pdf_path), item.page_index, item.rotation)

    def render_page_thumbnail(self, item: PageItem) -> Image.Image:
        return self.render_page_image(item, scale=0.34, max_size=(ICON_SIZE.width() - 12, ICON_SIZE.height() - 12))

    def render_page_preview(self, item: PageItem) -> Image.Image:
        return self.render_page_image(item, scale=1.45, max_size=(900, 1200))

    def render_page_image(self, item: PageItem, scale: float, max_size: tuple[int, int]) -> Image.Image:
        if PDF_RENDER_AVAILABLE and pdfium is not None:
            try:
                document = pdfium.PdfDocument(str(item.pdf_path), password=self.password_input.text() or None)
                page = document.get_page(item.page_index)
                try:
                    bitmap = page.render(scale=scale, rotation=item.rotation)
                    image = bitmap.to_pil().convert("RGB")
                    image.thumbnail(max_size, Image.Resampling.LANCZOS)
                    return self.page_canvas(image, max_size)
                finally:
                    page.close()
                    document.close()
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
