from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw
from PIL.ImageQt import ImageQt
from pypdf import PdfReader
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
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


THUMB_SIZE = QSize(170, 230)
ICON_SIZE = QSize(150, 200)


class PageGrid(QListWidget):
    filesDropped = Signal(list)
    reorderRequested = Signal(list, int)

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
        self.setSpacing(14)
        self.setIconSize(ICON_SIZE)
        self.setGridSize(THUMB_SIZE)
        self.setUniformItemSizes(True)
        self.setStyleSheet(
            """
            QListWidget {
                border: 1px solid #c8c5bd;
                background: #f7f7f4;
                padding: 12px;
            }
            QListWidget::item {
                background: #ffffff;
                border: 1px solid #d2d2d2;
                border-radius: 8px;
                padding: 8px;
            }
            QListWidget::item:selected {
                background: #d9f0ea;
                border: 2px solid #128576;
                color: #10201d;
            }
            """
        )

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
        if event.source() is self:
            source_rows = sorted(self.row(item) for item in self.selectedItems())
            if not source_rows:
                event.ignore()
                return
            target_row = self.drop_target_row(event)
            self.reorderRequested.emit(source_rows, target_row)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def drop_target_row(self, event: QDropEvent) -> int:
        point = event.position().toPoint()
        item = self.itemAt(point)
        if item is None:
            return self.count()
        row = self.row(item)
        rect = self.visualItemRect(item)
        if point.y() > rect.center().y() or point.x() > rect.center().x():
            return row + 1
        return row


class VictorPdfToolsQt(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Victor PDF Tools Box")
        self.resize(1280, 820)
        self.page_items: list[PageItem] = []
        self.thumbnail_cache: dict[tuple[str, int, int], QIcon] = {}

        self.page_grid = PageGrid()
        self.page_grid.filesDropped.connect(self.add_files_from_paths)
        self.page_grid.reorderRequested.connect(self.reorder_pages)
        self.page_grid.itemSelectionChanged.connect(self.update_stats)

        self.stats_label = QLabel("總頁數：0　已選取：0")
        self.stats_label.setObjectName("muted")
        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("例如 1-12,15-18；留空則用選取頁")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("如 PDF 已加密，在此輸入密碼")

        self.build_ui()
        self.setStatusBar(QStatusBar())
        self.set_status("把 PDF 直接拖入左邊縮圖區，或按「加入 PDF」。")

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
        subtitle = QLabel("第二代 Qt 介面：本機處理 PDF，支援拖入檔案、縮圖重排、旋轉、擷取與合併。")
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
        self.add_button(controls, "移除選取", self.remove_selected_pages, "danger")
        self.add_button(controls, "清空", self.clear_pages)
        controls.addSpacing(10)
        self.add_button(controls, "選取左轉", lambda: self.rotate_selected_pages(270))
        self.add_button(controls, "選取右轉", lambda: self.rotate_selected_pages(90))
        controls.addStretch(1)
        controls.addWidget(self.stats_label)
        left_layout.addLayout(controls)
        left_layout.addWidget(self.page_grid, 1)
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
        save_button = self.add_button(side_layout, "儲存最新版 PDF", self.export_arranged_pdf, "primary")
        save_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        side_layout.addSpacing(12)
        side_layout.addWidget(QLabel("擷取頁碼範圍"))
        side_layout.addWidget(self.range_input)
        hint = QLabel("可輸入 1-12,15-18。留空時使用目前選取的縮圖頁面。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        side_layout.addWidget(hint)
        self.add_button(side_layout, "擷取選取 - 合併", self.extract_pages_merged)
        self.add_button(side_layout, "擷取選取 - 單獨", self.extract_pages_separate)

        side_layout.addSpacing(12)
        side_layout.addWidget(QLabel("加密 PDF 密碼"))
        side_layout.addWidget(self.password_input)
        side_layout.addStretch(1)
        guide = QLabel("提示：縮圖可直接拖拉重排；Ctrl 或 Shift 可多選。旋轉、擷取會套用目前排列。")
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

    def choose_pdf_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "加入 PDF", "", "PDF files (*.pdf)")
        self.add_files_from_paths(files)

    def add_files_from_paths(self, paths: list[str]) -> None:
        added = 0
        skipped = 0
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_file() or path.suffix.lower() != ".pdf":
                skipped += 1
                continue
            try:
                reader = open_reader(path, self.password_input.text())
            except Exception as exc:
                skipped += 1
                self.show_error(exc)
                continue
            for page_index in range(len(reader.pages)):
                self.page_items.append(PageItem(path, page_index, f"{path.name} - Page {page_index + 1}"))
                added += 1
        self.rebuild_grid()
        if added:
            self.set_status(f"已加入 {added} 頁。")
        elif skipped:
            self.set_status("沒有加入頁面，請確認檔案是 PDF 或密碼正確。")

    def rebuild_grid(self, selected_indexes: set[int] | None = None) -> None:
        selected_indexes = selected_indexes or set()
        self.page_grid.blockSignals(True)
        self.page_grid.clear()
        for index, item in enumerate(self.page_items):
            list_item = QListWidgetItem(self.thumbnail_for_page(item), page_item_label(item))
            list_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            list_item.setData(Qt.UserRole, item)
            list_item.setSizeHint(THUMB_SIZE)
            self.page_grid.addItem(list_item)
            if index in selected_indexes:
                list_item.setSelected(True)
        self.page_grid.blockSignals(False)
        self.update_stats()

    def reorder_pages(self, source_rows: list[int], target_row: int) -> None:
        source_rows = sorted(set(row for row in source_rows if 0 <= row < len(self.page_items)))
        if not source_rows:
            return
        if target_row in source_rows and len(source_rows) == 1:
            return
        moving = [self.page_items[row] for row in source_rows]
        remaining = [item for index, item in enumerate(self.page_items) if index not in source_rows]
        adjusted_target = target_row - sum(1 for row in source_rows if row < target_row)
        adjusted_target = max(0, min(adjusted_target, len(remaining)))
        self.page_items = remaining[:adjusted_target] + moving + remaining[adjusted_target:]
        selected = set(range(adjusted_target, adjusted_target + len(moving)))
        self.rebuild_grid(selected)
        self.set_status("頁面順序已更新。")

    def selected_indexes(self) -> list[int]:
        return sorted(self.page_grid.row(item) for item in self.page_grid.selectedItems())

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
        self.page_items[source], self.page_items[target] = self.page_items[target], self.page_items[source]
        self.rebuild_grid({target})
        self.set_status("頁面順序已更新。")

    def rotate_selected_pages(self, angle: int) -> None:
        indexes = self.selected_indexes()
        if not indexes:
            self.set_status("請先選取要旋轉的頁面。")
            return
        for index in indexes:
            item = self.page_items[index]
            self.page_items[index] = PageItem(item.pdf_path, item.page_index, item.label, (item.rotation + angle) % 360)
        self.rebuild_grid(set(indexes))
        self.set_status(f"已旋轉 {len(indexes)} 頁，按「儲存最新版 PDF」輸出新檔。")

    def remove_selected_pages(self) -> None:
        indexes = self.selected_indexes()
        if not indexes:
            self.set_status("請先選取要移除的頁面。")
            return
        for index in reversed(indexes):
            self.page_items.pop(index)
        self.rebuild_grid()
        self.set_status(f"已移除 {len(indexes)} 頁。")

    def clear_pages(self) -> None:
        self.page_items.clear()
        self.thumbnail_cache.clear()
        self.rebuild_grid()
        self.set_status("已清空頁面。")

    def export_arranged_pdf(self) -> None:
        if not self.page_items:
            self.set_status("請先加入 PDF 頁面。")
            return
        target, _ = QFileDialog.getSaveFileName(self, "儲存最新版 PDF", "arranged-pages.pdf", "PDF files (*.pdf)")
        if not target:
            return
        self.run_pdf_job(
            lambda: write_page_items_merged(
                self.page_items, list(range(len(self.page_items))), Path(target), self.password_input.text()
            ),
            f"已儲存最新版 PDF：{target}",
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
            self, "擷取選取頁面並合併", "extracted-selected-pages.pdf", "PDF files (*.pdf)"
        )
        if not target:
            return
        self.run_pdf_job(
            lambda: write_page_items_merged(self.page_items, indexes, Path(target), self.password_input.text()),
            f"已擷取並合併 {len(indexes)} 頁。",
        )

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

    def run_pdf_job(self, job, success_message: str) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            job()
        except Exception as exc:
            self.show_error(exc)
        else:
            self.set_status(success_message)
        finally:
            QApplication.restoreOverrideCursor()

    def thumbnail_for_page(self, item: PageItem) -> QIcon:
        key = (str(item.pdf_path), item.page_index, item.rotation)
        cached = self.thumbnail_cache.get(key)
        if cached is not None:
            return cached
        image = self.render_page_thumbnail(item)
        icon = QIcon(QPixmap.fromImage(ImageQt(image)))
        self.thumbnail_cache[key] = icon
        return icon

    def render_page_thumbnail(self, item: PageItem) -> Image.Image:
        if PDF_RENDER_AVAILABLE and pdfium is not None:
            try:
                document = pdfium.PdfDocument(str(item.pdf_path), password=self.password_input.text() or None)
                page = document.get_page(item.page_index)
                try:
                    bitmap = page.render(scale=0.34, rotation=item.rotation)
                    image = bitmap.to_pil().convert("RGB")
                    image.thumbnail((ICON_SIZE.width(), ICON_SIZE.height()), Image.Resampling.LANCZOS)
                    canvas = Image.new("RGB", (ICON_SIZE.width(), ICON_SIZE.height()), "white")
                    x = (canvas.width - image.width) // 2
                    y = (canvas.height - image.height) // 2
                    canvas.paste(image, (x, y))
                    return canvas
                finally:
                    page.close()
                    document.close()
            except Exception:
                pass
        return self.placeholder_thumbnail(item)

    def placeholder_thumbnail(self, item: PageItem) -> Image.Image:
        image = Image.new("RGB", (ICON_SIZE.width(), ICON_SIZE.height()), "#ffffff")
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, ICON_SIZE.width() - 8, ICON_SIZE.height() - 8), outline="#d0d0d0", width=2)
        draw.text((22, 76), "PDF", fill="#666666")
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
