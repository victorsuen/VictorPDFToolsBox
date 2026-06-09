from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QByteArray, QMimeData, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QDrag, QDragEnterEvent, QDropEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
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
    QVBoxLayout,
    QWidget,
)

from pdf_core import (
    PDF_RENDER_AVAILABLE,
    PageItem,
    open_reader,
    page_item_label,
    parse_pages,
    pdfium,
    write_page_items_merged,
    write_page_items_separately,
)


THUMB_SIZE = QSize(195, 292)
ICON_SIZE = QSize(165, 215)


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
            QLineEdit {
                min-height: 30px;
                padding: 2px 8px;
                border: 1px solid #aaa69d;
                border-radius: 6px;
                background: #ffffff;
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
        layout.addWidget(tabs, 1)
        self.setCentralWidget(root)

        open_action = QAction("加入 PDF", self)
        open_action.triggered.connect(self.choose_pdf_files)
        self.addAction(open_action)

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
        layout = QGridLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        title = QLabel("常用工具會逐步搬到 Qt 介面")
        title.setObjectName("title")
        title.setStyleSheet("font-size: 16pt;")
        note = QLabel("這一版先重構最常用的頁面組織、旋轉、擷取流程。舊版 Tkinter 入口仍保留，可作為過渡。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(title, 0, 0)
        layout.addWidget(note, 1, 0)
        layout.setRowStretch(2, 1)
        return tab

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
        self.run_pdf_job(
            lambda: write_page_items_merged(
                self.page_items, list(range(len(self.page_items))), Path(target), self.password_input.text()
            ),
            f"已儲存目前 Tab PDF：{target}",
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
        self.run_pdf_job(
            lambda: write_page_items_separately(self.page_items, indexes, Path(folder), self.password_input.text()),
            f"已單獨匯出 {len(indexes)} 頁。",
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
