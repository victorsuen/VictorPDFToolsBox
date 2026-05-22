import os
from pathlib import Path
import tempfile
import unittest

from pypdf import PdfWriter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from qt_app import VictorPdfToolsQt


class QtAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.source = Path(self.temp_dir.name) / "source.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.add_blank_page(width=300, height=400)
        with self.source.open("wb") as stream:
            writer.write(stream)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_pdf_updates_grid_and_stats(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])

        self.assertEqual(len(window.page_items), 2)
        self.assertEqual(window.page_grid.count(), 2)
        self.assertEqual(window.stats_label.text(), "總頁數：2　已選取：0")

    def test_rotate_selected_page_updates_model(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.page_grid.item(0).setSelected(True)

        window.rotate_selected_pages(90)

        self.assertEqual(window.page_items[0].rotation, 90)
        self.assertEqual(window.stats_label.text(), "總頁數：2　已選取：1")

    def test_reorder_pages_moves_selected_items_to_insert_position(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])

        window.reorder_pages([0], 2)

        self.assertEqual([item.page_index for item in window.page_items], [1, 0])
        self.assertTrue(window.page_grid.item(1).isSelected())


if __name__ == "__main__":
    unittest.main()
