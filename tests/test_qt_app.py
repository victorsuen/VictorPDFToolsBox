import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfWriter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from pdf_core import TextBlock
from qt_app import FOLDER_REVEAL_OPERATIONS, MergeFilesDialog, VictorPdfToolsQt, reveal_output


class QtAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.source = Path(self.temp_dir.name) / "source.pdf"
        self.second_source = Path(self.temp_dir.name) / "second.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.add_blank_page(width=300, height=400)
        with self.source.open("wb") as stream:
            writer.write(stream)
        second_writer = PdfWriter()
        second_writer.add_blank_page(width=300, height=400)
        with self.second_source.open("wb") as stream:
            second_writer.write(stream)

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

    def test_page_card_label_shows_current_and_original_page(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])

        self.assertIn("Page 1", window.page_grid.item(0).text())
        self.assertIn("原頁 1", window.page_grid.item(0).text())
        self.assertIn("source.pdf", window.page_grid.item(0).text())

    def test_cut_and_paste_pages_across_tabs(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.add_files_from_paths([str(self.second_source)])
        window.document_tabs.setCurrentIndex(0)
        window.page_grid.item(0).setSelected(True)

        window.cut_selected_pages()
        self.assertEqual(len(window.workspaces[window.document_tabs.widget(0)]["items"]), 1)

        window.document_tabs.setCurrentIndex(1)
        window.paste_pages()

        self.assertEqual([item.pdf_path.name for item in window.page_items], ["second.pdf", "source.pdf"])
        self.assertEqual([item.page_index for item in window.page_items], [0, 0])

    def test_delete_selected_pages_removes_items(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.page_grid.item(0).setSelected(True)

        window.remove_selected_pages()

        self.assertEqual(len(window.page_items), 1)
        self.assertEqual(window.page_items[0].page_index, 1)

    def test_undo_restores_cut_pages(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.page_grid.item(0).setSelected(True)

        window.cut_selected_pages()
        window.undo_last_action()

        self.assertEqual([item.page_index for item in window.page_items], [0, 1])
        self.assertTrue(window.page_grid.item(0).isSelected())

    def test_undo_restores_deleted_pages(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.page_grid.item(0).setSelected(True)

        window.remove_selected_pages()
        window.undo_last_action()

        self.assertEqual([item.page_index for item in window.page_items], [0, 1])

    def test_undo_removes_pasted_pages(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.page_grid.item(0).setSelected(True)
        window.copy_selected_pages()

        window.paste_pages()
        window.undo_last_action()

        self.assertEqual([item.page_index for item in window.page_items], [0, 1])

    def test_each_pdf_opens_in_its_own_document_tab(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.add_files_from_paths([str(self.second_source)])

        self.assertEqual(window.document_tabs.count(), 2)
        self.assertEqual(window.document_tabs.tabText(0), "source.pdf")
        self.assertEqual(window.document_tabs.tabText(1), "second.pdf")
        self.assertEqual(len(window.page_items), 1)
        self.assertEqual(window.stats_label.text(), "總頁數：1　已選取：0")

        window.document_tabs.setCurrentIndex(0)

        self.assertEqual(len(window.page_items), 2)
        self.assertEqual(window.stats_label.text(), "總頁數：2　已選取：0")

    def test_all_tab_page_items_merges_tabs_in_tab_order(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.add_files_from_paths([str(self.second_source)])

        items = window.all_tab_page_items()

        self.assertEqual([item.pdf_path.name for item in items], ["source.pdf", "source.pdf", "second.pdf"])
        self.assertEqual([item.page_index for item in items], [0, 1, 0])

    def test_open_pdf_as_new_tab_adds_output_document(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])

        window.open_pdf_as_new_tab(self.second_source)

        self.assertEqual(window.document_tabs.count(), 2)
        self.assertEqual(window.document_tabs.tabText(1), "second.pdf")
        self.assertEqual(len(window.page_items), 1)

    def test_merge_dialog_uses_user_controlled_file_order(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.add_files_from_paths([str(self.second_source)])
        dialog = MergeFilesDialog(window)
        dialog.add_open_tabs()

        moved = dialog.source_list.takeItem(1)
        dialog.source_list.insertItem(0, moved)

        items = dialog.page_items()
        self.assertEqual([item.pdf_path.name for item in items], ["second.pdf", "source.pdf", "source.pdf"])
        self.assertEqual([item.page_index for item in items], [0, 0, 1])

    def test_merge_dialog_remove_selected_source(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.add_files_from_paths([str(self.second_source)])
        dialog = MergeFilesDialog(window)
        dialog.add_open_tabs()

        dialog.source_list.item(0).setSelected(True)
        dialog.remove_selected()

        self.assertEqual(dialog.source_list.count(), 1)
        self.assertEqual(dialog.source_list.item(0).text().split("\n", 1)[0], "second.pdf")

    def test_tool_tab_accepts_pdf_files(self):
        window = VictorPdfToolsQt()
        window.add_tool_files_from_paths([self.source], {".pdf"})

        self.assertEqual(len(window.tool_file_items), 1)
        self.assertEqual(window.tool_file_list.count(), 1)

    def test_tool_tab_accepts_dropped_pdf_files(self):
        window = VictorPdfToolsQt()
        window.drop_tool_files([str(self.source), str(self.second_source)])

        self.assertEqual(len(window.tool_file_items), 2)

    def test_annotation_tab_loads_pdf(self):
        window = VictorPdfToolsQt()
        window.set_annotation_pdf(self.source)

        self.assertEqual(window.annotation_pdf_path, self.source)
        self.assertEqual(window.annotation_page_count, 2)
        self.assertEqual(window.annotation_page_validator.top(), 2)

    def test_text_edit_tab_loads_pdf(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)

        self.assertEqual(window.text_edit_pdf_path, self.source)
        self.assertEqual(window.text_edit_page_count, 2)
        self.assertEqual(window.text_edit_page_validator.top(), 2)
        self.assertEqual(window.text_edit_mode_combo.currentData(), "overlay")
        self.assertEqual(window.text_edit_mode_combo.itemData(1), "content_stream")

    def test_text_edit_preview_click_selects_block(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [TextBlock("Hello", 72, 300, 100, 20, 12)]
        window.render_text_edit_preview()
        left, top, right, bottom = window.text_block_to_image_rect(window.text_edit_blocks[0])
        window.refresh_text_edit_blocks()

        window.select_text_edit_block_at_point(QPoint(int((left + right) / 2), int((top + bottom) / 2)))

        self.assertEqual(window.text_edit_block_list.currentRow(), 0)

    def test_output_preferences_default_enabled(self):
        window = VictorPdfToolsQt()

        self.assertTrue(window.open_pdf_after_save_checkbox.isChecked())
        self.assertTrue(window.open_folder_after_export_checkbox.isChecked())
        self.assertTrue(window.tool_open_pdf_tab_checkbox.isChecked())
        self.assertTrue(window.tool_open_output_folder_checkbox.isChecked())

    def test_folder_reveal_operations_include_zip_and_text_tools(self):
        self.assertEqual(FOLDER_REVEAL_OPERATIONS, {"split", "extract_text", "ocr_text", "info", "pdf_to_images"})

    def test_reveal_output_skips_missing_path(self):
        with patch("qt_app.subprocess.Popen") as popen, patch("qt_app.os.startfile") as startfile:
            reveal_output(Path(self.temp_dir.name) / "missing.zip")
            popen.assert_not_called()
            startfile.assert_not_called()

    @patch("qt_app.sys.platform", "win32")
    def test_reveal_output_selects_existing_file_on_windows(self):
        target = Path(self.temp_dir.name) / "output.txt"
        target.write_text("demo", encoding="utf-8")
        with patch("qt_app.subprocess.Popen") as popen:
            reveal_output(target)
            popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0], ["explorer", "/select,", str(target.resolve())])

    def test_annotation_preview_draws_overlay_text(self):
        window = VictorPdfToolsQt()
        window.set_annotation_pdf(self.source)
        window.annotation_text_input.setPlainText("Hello World")
        window.annotation_x_input.setText("72")
        window.annotation_y_input.setText("300")
        window.update_annotation_preview_display()

        self.assertIsNotNone(window.annotation_preview_label.pixmap())
        self.assertFalse(window.annotation_preview_label.pixmap().isNull())

    def test_merge_dialog_undo_restores_removed_source(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.add_files_from_paths([str(self.second_source)])
        dialog = MergeFilesDialog(window)
        dialog.add_open_tabs()

        dialog.source_list.item(0).setSelected(True)
        dialog.remove_selected()
        dialog.undo_last()

        self.assertEqual(dialog.source_list.count(), 2)
        self.assertEqual(dialog.source_list.item(0).text().split("\n", 1)[0], "source.pdf")
        self.assertEqual(dialog.source_list.item(1).text().split("\n", 1)[0], "second.pdf")


if __name__ == "__main__":
    unittest.main()
