import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QPushButton, QTabWidget

from pdf_core import MarkupAnnotation, TextBlock
from document_workspace import DocumentWorkspace
from qt_app import (
    AuditLogDialog,
    BATCHABLE_OPERATIONS,
    FOLDER_REVEAL_OPERATIONS,
    TOOL_OPERATIONS,
    WINDOW_MIN_SIZE,
    MergeFilesDialog,
    VictorPdfToolsQt,
    document_tab_title,
    preferred_window_geometry,
    reveal_output,
)


class QtAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
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
        import gc

        app = QApplication.instance()
        if app is not None:
            for widget in list(app.topLevelWidgets()):
                if isinstance(widget, VictorPdfToolsQt):
                    for workspace in widget.workspaces.values():
                        workspace["generation"] = workspace.get("generation", 0) + 1
                        workspace["pending"] = []
                        workspace["pending_rest"] = []
                    widget.release_all_pdfium_documents()
                    widget.close()
            for widget in list(app.allWidgets()):
                if isinstance(widget, DocumentWorkspace):
                    widget._thumb_generation += 1
                    widget._thumb_timer.stop()
                    widget._close_pdfium_doc()
            app.processEvents()
        gc.collect()
        self.temp_dir.cleanup()

    def test_preferred_window_geometry_fits_available_screen(self):
        geometry = preferred_window_geometry()
        screen = self.app.primaryScreen().availableGeometry()
        self.assertLessEqual(geometry.width(), screen.width())
        self.assertLessEqual(geometry.height(), screen.height())
        self.assertGreaterEqual(geometry.width(), min(WINDOW_MIN_SIZE.width(), screen.width()))
        self.assertGreaterEqual(geometry.height(), min(WINDOW_MIN_SIZE.height(), screen.height()))

    def test_main_window_is_resizable_and_not_oversized(self):
        window = VictorPdfToolsQt()
        screen = self.app.primaryScreen().availableGeometry()
        self.assertLessEqual(window.width(), screen.width())
        self.assertLessEqual(window.height(), screen.height())
        self.assertLessEqual(window.minimumWidth(), screen.width())
        self.assertLessEqual(window.minimumHeight(), screen.height())
        # Tall tool options live in a scroll area, so shrinking remains possible.
        target = window.minimumSize()
        window.resize(target)
        self.assertEqual(window.width(), target.width())
        self.assertEqual(window.height(), target.height())

    def test_organize_toolbar_keeps_full_button_text_when_narrow(self):
        window = VictorPdfToolsQt()
        window.show()
        window.resize(WINDOW_MIN_SIZE)
        self.app.processEvents()
        buttons = window.organize_toolbar.findChildren(QPushButton)
        self.assertGreaterEqual(len(buttons), 8)
        labels = [button.text() for button in buttons]
        self.assertIn("加入 PDF", labels)
        self.assertIn("在工作台開啟", labels)
        for button in buttons:
            self.assertGreaterEqual(button.width(), button.sizeHint().width())
            self.assertFalse(button.text().endswith("…"))
        layout = window.organize_toolbar.layout()
        self.assertTrue(layout.hasHeightForWidth())
        self.assertGreater(layout.heightForWidth(240), layout.heightForWidth(1600))

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
        self.assertNotIn("source.pdf", window.page_grid.item(0).text())

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

    def test_multiple_pdfs_create_visible_short_tabs(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.add_files_from_paths([str(self.second_source)])
        self.assertEqual(window.main_tabs.currentIndex(), 0)
        self.assertEqual(window.document_tabs.count(), 2)
        self.assertFalse(window.document_tabs.tabBar().isHidden())
        self.assertEqual(window.document_tabs.tabText(0), "source.pdf")
        self.assertEqual(window.document_tabs.tabText(1), "second.pdf")

    def test_document_tab_title_shortens_long_names(self):
        long_name = "深圳投資2025年合併審計報告-信會師報字[2026]第ZI21041號.pdf"
        title = document_tab_title(long_name)
        self.assertLessEqual(len(title), 18)
        self.assertTrue(title.endswith(".pdf"))
        self.assertIn("…", title)

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
        self.assertEqual(window.text_edit_mode_combo.currentData(), "seamless")
        self.assertEqual(window.text_edit_mode_combo.itemData(1), "overlay")
        self.assertEqual(window.text_edit_mode_combo.itemData(2), "content_stream")
        self.assertEqual(window.text_edit_redaction_mode_combo.currentData(), "visual")
        self.assertEqual(window.text_edit_redaction_mode_combo.itemData(1), "secure")
        self.assertFalse(window.text_edit_case_sensitive_checkbox.isChecked())
        self.assertFalse(window.text_edit_whole_word_checkbox.isChecked())
        self.assertIn("替換限制", window.text_edit_replacement_hint.text())
        self.assertIn("符合數", window.text_edit_search_feedback.text())

    def test_text_edit_page_navigation_changes_page_within_bounds(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)

        window.change_text_edit_page(1)
        self.assertEqual(window.text_edit_page_input.text(), "2")

        window.change_text_edit_page(1)
        self.assertEqual(window.text_edit_page_input.text(), "2")

        window.change_text_edit_page(-1)
        self.assertEqual(window.text_edit_page_input.text(), "1")

        window.change_text_edit_page(-1)
        self.assertEqual(window.text_edit_page_input.text(), "1")

    def test_text_edit_preview_click_selects_block(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [TextBlock("Hello", 72, 300, 100, 20, 12)]
        window.render_text_edit_preview()
        left, top, right, bottom = window.text_block_to_image_rect(window.text_edit_blocks[0])
        window.refresh_text_edit_blocks()

        window.select_text_edit_block_at_point(QPoint(int((left + right) / 2), int((top + bottom) / 2)))

        self.assertEqual(window.text_edit_block_list.currentRow(), 0)

    def test_text_edit_search_selects_next_matching_block(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [
            TextBlock("Invoice Number", 72, 320, 100, 20, 12),
            TextBlock("Customer Name", 72, 290, 100, 20, 12),
            TextBlock("Invoice Total", 72, 260, 100, 20, 12),
        ]
        window.refresh_text_edit_blocks()
        window.text_edit_search_input.setText("invoice")

        window.find_next_text_edit_block()
        self.assertEqual(window.text_edit_block_list.currentRow(), 0)

        window.find_next_text_edit_block()
        self.assertEqual(window.text_edit_block_list.currentRow(), 2)

        window.find_previous_text_edit_block()
        self.assertEqual(window.text_edit_block_list.currentRow(), 0)

    def test_text_edit_search_text_highlights_preview_matches(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [
            TextBlock("Invoice Number", 72, 320, 100, 20, 12),
            TextBlock("Customer Name", 72, 290, 100, 20, 12),
        ]
        window.render_text_edit_preview()
        window.refresh_text_edit_blocks()
        window.text_edit_block_list.setCurrentRow(0)

        window.text_edit_search_input.setText("invoice")

        self.assertIsNotNone(window.text_edit_preview_label.pixmap())
        self.assertFalse(window.text_edit_preview_label.pixmap().isNull())

    def test_text_edit_search_feedback_counts_current_page_matches(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [
            TextBlock("Invoice Number", 72, 320, 100, 20, 12),
            TextBlock("Invoice Total", 72, 290, 100, 20, 12),
            TextBlock("Customer Name", 72, 260, 100, 20, 12),
        ]
        window.refresh_text_edit_blocks()

        window.text_edit_search_input.setText("invoice")

        self.assertIn("2", window.text_edit_search_feedback.text())

    def test_text_edit_count_all_search_matches_counts_document(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [
            TextBlock("Invoice Number", 72, 320, 100, 20, 12),
            TextBlock("Customer Name", 72, 260, 100, 20, 12),
        ]
        window.refresh_text_edit_blocks()
        window.text_edit_search_input.setText("invoice")
        next_page_blocks = [
            TextBlock("Invoice Total", 72, 300, 100, 20, 12),
            TextBlock("Invoice Date", 72, 270, 100, 20, 12),
        ]

        with patch("qt_app.extract_page_text_blocks", return_value=next_page_blocks):
            window.count_all_text_search_matches()

        self.assertIn("3", window.text_edit_search_feedback.text())

    def test_text_edit_clear_search_removes_query_and_keeps_preview(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [TextBlock("Invoice Number", 72, 320, 100, 20, 12)]
        window.render_text_edit_preview()
        window.refresh_text_edit_blocks()
        window.text_edit_block_list.setCurrentRow(0)
        window.text_edit_search_input.setText("invoice")

        window.clear_text_edit_search()

        self.assertEqual(window.text_edit_search_input.text(), "")
        self.assertIsNotNone(window.text_edit_preview_label.pixmap())
        self.assertFalse(window.text_edit_preview_label.pixmap().isNull())

    def test_text_edit_replacement_text_updates_preview(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [TextBlock("Old Value", 72, 320, 100, 20, 12, "/Helvetica")]
        window.render_text_edit_preview()
        window.refresh_text_edit_blocks()
        window.text_edit_block_list.setCurrentRow(0)

        window.text_edit_replacement_input.setPlainText("New Value")

        self.assertIsNotNone(window.text_edit_preview_label.pixmap())
        self.assertFalse(window.text_edit_preview_label.pixmap().isNull())

    def test_text_edit_replacement_preview_expands_for_long_text(self):
        window = VictorPdfToolsQt()
        block = TextBlock("Old", 72, 320, 30, 20, 12, "/Helvetica")

        left, _top, right, _bottom = window.text_replacement_preview_rect(
            block,
            "Long replacement value",
            1.0,
            1.0,
            500,
        )

        self.assertGreater(right - left, block.width)

    def test_text_edit_replacement_hint_reports_content_stream_limits(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [TextBlock("Old", 72, 320, 30, 20, 12, "/Helvetica")]
        window.refresh_text_edit_blocks()
        window.text_edit_block_list.setCurrentRow(0)
        window.text_edit_mode_combo.setCurrentIndex(window.text_edit_mode_combo.findData("content_stream"))

        window.text_edit_replacement_input.setPlainText("Long")
        self.assertIn("長度不同", window.text_edit_replacement_hint.text())

        window.text_edit_replacement_input.setPlainText("New")
        self.assertIn("可嘗試", window.text_edit_replacement_hint.text())

    def test_text_edit_search_respects_case_sensitive_option(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [TextBlock("Invoice Number", 72, 320, 100, 20, 12)]
        window.refresh_text_edit_blocks()
        window.text_edit_search_input.setText("invoice")
        window.text_edit_case_sensitive_checkbox.setChecked(True)

        window.find_next_text_edit_block()
        self.assertEqual(window.text_edit_block_list.currentRow(), -1)

        window.text_edit_search_input.setText("Invoice")
        window.find_next_text_edit_block()
        self.assertEqual(window.text_edit_block_list.currentRow(), 0)

    def test_text_edit_search_respects_whole_word_option(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [
            TextBlock("InvoiceNumber", 72, 320, 100, 20, 12),
            TextBlock("Invoice Number", 72, 290, 100, 20, 12),
        ]
        window.refresh_text_edit_blocks()
        window.text_edit_search_input.setText("invoice")
        window.text_edit_whole_word_checkbox.setChecked(True)

        window.find_next_text_edit_block()
        self.assertEqual(window.text_edit_block_list.currentRow(), 1)

    def test_text_edit_search_moves_to_next_page_match(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [TextBlock("Customer Name", 72, 320, 100, 20, 12)]
        window.refresh_text_edit_blocks()
        window.text_edit_search_input.setText("invoice")
        next_page_blocks = [TextBlock("Invoice Total", 72, 300, 100, 20, 12)]

        with patch("qt_app.extract_page_text_blocks", return_value=next_page_blocks):
            window.find_next_text_edit_block()

        self.assertEqual(window.text_edit_page_input.text(), "2")
        self.assertEqual(window.text_edit_block_list.currentRow(), 0)
        self.assertEqual(window.text_edit_block_list.currentItem().text(), "Invoice Total")

    def test_text_edit_search_moves_to_previous_page_match(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_page_input.setText("2")
        window.text_edit_blocks = [TextBlock("Customer Name", 72, 320, 100, 20, 12)]
        window.refresh_text_edit_blocks()
        window.text_edit_search_input.setText("invoice")
        previous_page_blocks = [TextBlock("Invoice Number", 72, 300, 100, 20, 12)]

        with patch("qt_app.extract_page_text_blocks", return_value=previous_page_blocks):
            window.find_previous_text_edit_block()

        self.assertEqual(window.text_edit_page_input.text(), "1")
        self.assertEqual(window.text_edit_block_list.currentRow(), 0)
        self.assertEqual(window.text_edit_block_list.currentItem().text(), "Invoice Number")

    def test_text_edit_redact_selected_block_writes_output(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [TextBlock("Secret", 72, 300, 80, 20, 12)]
        window.refresh_text_edit_blocks()
        window.text_edit_block_list.setCurrentRow(0)
        target = Path(self.temp_dir.name) / "redacted.pdf"

        with patch("qt_app.QFileDialog.getSaveFileName", return_value=(str(target), "PDF files (*.pdf)")):
            with patch.object(window, "open_pdf_as_new_tab"):
                window.redact_text_edit_pdf()

        self.assertTrue(target.exists())
        self.assertEqual(len(PdfReader(str(target)).pages[0].get("/Annots")), 1)

    def test_text_edit_redact_all_search_matches_uses_query(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_search_input.setText("invoice")
        window.text_edit_case_sensitive_checkbox.setChecked(True)
        window.text_edit_whole_word_checkbox.setChecked(True)
        target = Path(self.temp_dir.name) / "redacted-all.pdf"

        with patch("qt_app.QFileDialog.getSaveFileName", return_value=(str(target), "PDF files (*.pdf)")):
            with patch("qt_app.redact_matching_text_blocks_overlay", return_value=3) as redact_all:
                with patch.object(window, "open_pdf_as_new_tab"):
                    window.redact_all_text_search_matches()

        redact_all.assert_called_once_with(
            self.source,
            target,
            "invoice",
            "",
            True,
            True,
        )

    def test_output_preferences_default_enabled(self):
        from PySide6.QtCore import QSettings
        from qt_app import SETTINGS_APP, SETTINGS_ORG

        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        settings.clear()
        window = VictorPdfToolsQt()

        self.assertTrue(window.open_pdf_after_save_checkbox.isChecked())
        self.assertTrue(window.open_folder_after_export_checkbox.isChecked())
        self.assertTrue(window.tool_open_pdf_tab_checkbox.isChecked())
        self.assertTrue(window.tool_open_output_folder_checkbox.isChecked())
        self.assertTrue(window.office_open_pdf_checkbox.isChecked())

    def test_folder_reveal_operations_include_zip_and_text_tools(self):
        self.assertEqual(
            FOLDER_REVEAL_OPERATIONS,
            {
                "split",
                "split_advanced",
                "extract_text",
                "ocr_text",
                "info",
                "pdf_to_images",
                "compare_text",
                "split_bookmarks",
            },
        )

    def test_organize_tab_is_first_tab(self):
        window = VictorPdfToolsQt()
        main_tabs = window.main_tabs
        self.assertEqual(main_tabs.tabText(0), "組織")
        self.assertEqual(main_tabs.currentIndex(), 0)
        self.assertIsNotNone(window.page_grid)

    def test_main_tabs_flat_structure(self):
        window = VictorPdfToolsQt()
        main_tabs = window.main_tabs
        main_texts = [main_tabs.tabText(index) for index in range(main_tabs.count())]
        self.assertEqual(main_texts, ["組織", "文件工作台", "常用工具", "Office 轉 PDF", "進階"])
        advanced_tabs = window.advanced_tabs
        self.assertIsInstance(advanced_tabs, QTabWidget)
        advanced_texts = [advanced_tabs.tabText(index) for index in range(advanced_tabs.count())]
        for expected in (
            "文字標註 / 覆蓋",
            "螢光 / 圖形註解",
            "裁切頁面",
            "文字編輯 Beta",
            "書籤 / 目錄",
        ):
            self.assertIn(expected, advanced_texts)
        workspace_tab = main_tabs.widget(1)
        self.assertIs(workspace_tab.findChild(DocumentWorkspace), window.document_workspace)

    def test_document_workspace_single_page_preview(self):
        workspace = DocumentWorkspace()
        self.assertTrue(hasattr(workspace, "preview_widget"))
        self.assertTrue(hasattr(workspace, "preview_scroll"))
        workspace.open_path(self.source)
        self.assertEqual(workspace.page_count, 2)
        self.assertIs(workspace.preview_scroll.widget(), workspace.preview_widget)

    def test_document_workspace_open_does_not_create_all_page_widgets(self):
        big_pdf = Path(self.temp_dir.name) / "big.pdf"
        writer = PdfWriter()
        for _ in range(100):
            writer.add_blank_page(width=300, height=400)
        with big_pdf.open("wb") as stream:
            writer.write(stream)

        workspace = DocumentWorkspace()
        workspace.open_path(big_pdf)
        self.assertEqual(workspace.page_count, 100)
        self.assertEqual(workspace.thumb_list.count(), 100)
        self.assertIs(workspace.preview_scroll.widget(), workspace.preview_widget)

    def test_document_workspace_lazy_thumbnails_create_page_items(self):
        workspace = DocumentWorkspace()
        workspace.open_path(self.source)
        self.assertEqual(workspace.thumb_list.count(), 2)
        self.assertEqual(workspace.thumb_list.item(0).text(), "第 1 頁")
        self.assertEqual(workspace.thumb_list.item(1).text(), "第 2 頁")

    def test_document_workspace_thumb_panel_is_wide_enough(self):
        from document_workspace import THUMB_PANEL_MIN_WIDTH, THUMB_PANEL_MAX_WIDTH

        from PySide6.QtWidgets import QListView

        workspace = DocumentWorkspace()
        self.assertGreaterEqual(workspace.left_tabs.minimumWidth(), THUMB_PANEL_MIN_WIDTH)
        self.assertGreaterEqual(workspace.left_tabs.maximumWidth(), THUMB_PANEL_MAX_WIDTH - 1)
        self.assertGreaterEqual(workspace.thumb_list.iconSize().width(), 140)
        self.assertEqual(workspace.thumb_list.viewMode(), QListView.ListMode)

    def test_document_workspace_accepts_pdf_drop(self):
        from PySide6.QtCore import QMimeData, QPoint, QUrl
        from PySide6.QtGui import QDropEvent

        workspace = DocumentWorkspace()
        received: list[list[str]] = []
        workspace.files_dropped.connect(lambda paths: received.append(list(paths)))
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.source))])
        event = QDropEvent(
            QPoint(10, 10),
            Qt.CopyAction,
            mime,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        workspace.dropEvent(event)
        self.assertEqual(workspace.current_path(), self.source)
        self.assertEqual(len(received), 1)
        self.assertEqual([Path(path) for path in received[0]], [self.source])

    def test_main_window_drop_adds_to_organize_by_default(self):
        from PySide6.QtCore import QMimeData, QPoint, QUrl
        from PySide6.QtGui import QDropEvent

        window = VictorPdfToolsQt()
        self.assertEqual(window.main_tabs.currentIndex(), 0)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.source))])
        event = QDropEvent(
            QPoint(20, 20),
            Qt.CopyAction,
            mime,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        window.dropEvent(event)
        self.assertTrue(any(item.pdf_path == self.source for item in window.page_items))
        self.assertIsNone(window.document_workspace.current_path())

    def test_main_window_drop_on_workspace_also_opens_workspace(self):
        from PySide6.QtCore import QMimeData, QPoint, QUrl
        from PySide6.QtGui import QDropEvent

        window = VictorPdfToolsQt()
        window.main_tabs.setCurrentIndex(1)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.source))])
        event = QDropEvent(
            QPoint(20, 20),
            Qt.CopyAction,
            mime,
            Qt.LeftButton,
            Qt.NoModifier,
        )
        window.dropEvent(event)
        self.assertEqual(window.document_workspace.current_path(), self.source)
        self.assertTrue(any(item.pdf_path == self.source for item in window.page_items))

    def test_document_workspace_shortcuts_include_undo_and_page_nav(self):
        workspace = DocumentWorkspace()
        shortcuts = {
            action.shortcut().toString(): action
            for action in workspace.actions()
            if not action.shortcut().isEmpty()
        }
        self.assertIn("Ctrl+Z", shortcuts)
        self.assertIn("Ctrl+S", shortcuts)
        self.assertIn("Left", shortcuts)
        self.assertIn("Right", shortcuts)
        page_keys = [key for key in shortcuts if "pg" in key.lower()]
        self.assertGreaterEqual(len(page_keys), 2)
        self.assertEqual(shortcuts["Ctrl+Z"].shortcutContext(), Qt.WidgetWithChildrenShortcut)

    def test_audit_log_append_writes_line(self):
        from audit_log import append_audit_event

        log_path = Path(self.temp_dir.name) / "audit.log"
        with patch("audit_log.audit_log_path", return_value=log_path):
            append_audit_event("test_op", "source.pdf", "target.pdf", "ok")
        content = log_path.read_text(encoding="utf-8")
        self.assertIn("test_op", content)
        self.assertIn("source.pdf", content)
        self.assertIn("target.pdf", content)

    def test_prioritize_visible_thumbnails_moves_visible_first(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        grid = window.page_grid
        workspace = window.workspaces[grid]
        workspace["pending"] = []
        workspace["pending_rest"] = [0, 1]
        with patch.object(window, "_visible_item_indexes", return_value=[1]):
            window._prioritize_visible_thumbnails(grid)
        self.assertEqual(workspace["pending"], [1])
        self.assertEqual(workspace["pending_rest"], [0])

    def test_open_current_pdf_in_workspace_switches_tab(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        window.open_current_pdf_in_workspace()
        self.assertEqual(window.main_tabs.currentIndex(), 1)
        self.assertEqual(window.document_workspace.current_path(), self.source)

    def test_workspace_save_applies_pending_markups_in_place(self):
        workspace = DocumentWorkspace()
        workspace.open_path(self.source)
        workspace.markup_items.append((0, MarkupAnnotation("rect", 10, 20, 80, 90)))
        workspace.save_pdf()
        self.assertEqual(workspace.markup_items, [])
        annots = PdfReader(str(self.source)).pages[0].get("/Annots")
        self.assertIsNotNone(annots)
        self.assertGreaterEqual(len(annots), 1)

    def test_workspace_save_copy_writes_new_file(self):
        workspace = DocumentWorkspace()
        workspace.open_path(self.source)
        target = Path(self.temp_dir.name) / "copy.pdf"
        with patch("document_workspace.QFileDialog.getSaveFileName", return_value=(str(target), "PDF files (*.pdf)")):
            workspace.save_pdf_copy()
        self.assertTrue(target.exists())
        self.assertEqual(len(PdfReader(str(target)).pages), 2)

    def test_audit_log_read_newest_first_and_dialog_rows(self):
        from audit_log import append_audit_event, read_audit_events

        log_path = Path(self.temp_dir.name) / "audit.log"
        with patch("audit_log.audit_log_path", return_value=log_path):
            append_audit_event("first", "a.pdf", "b.pdf", "ok")
            append_audit_event("second", "c.pdf", "d.pdf", "ok")
            events = read_audit_events(10)
        self.assertEqual(events[0].operation, "second")
        self.assertEqual(events[1].operation, "first")
        with patch("qt_app.read_audit_events", return_value=events):
            dialog = AuditLogDialog()
            self.assertEqual(dialog.table.rowCount(), 2)
            self.assertEqual(dialog.table.item(0, 1).text(), "second")
        dialog.close()

    def test_stamp_library_add_and_delete(self):
        from PIL import Image

        from stamp_library import add_library_stamp, delete_library_stamp, list_library_stamps

        library = Path(self.temp_dir.name) / "stamps"
        library.mkdir()
        image_path = Path(self.temp_dir.name) / "approved.png"
        Image.new("RGB", (40, 20), "red").save(image_path)
        with patch("stamp_library.stamp_library_dir", return_value=library):
            dest = add_library_stamp(image_path)
            self.assertTrue(dest.exists())
            self.assertEqual(list_library_stamps(), [dest])
            delete_library_stamp(dest)
            self.assertEqual(list_library_stamps(), [])

    def test_document_workspace_can_be_constructed(self):
        workspace = DocumentWorkspace()
        self.assertIsNone(workspace.current_path())
        workspace.open_path(self.source)
        self.assertEqual(workspace.current_path(), self.source)
        self.assertEqual(workspace.page_count, 2)

    def test_document_workspace_has_zoom_controls_and_undo(self):
        workspace = DocumentWorkspace()
        self.assertEqual(workspace.preview_zoom, 1.0)
        self.assertTrue(hasattr(workspace, "zoom_label"))
        self.assertTrue(callable(workspace.undo))
        workspace.open_path(self.source)
        workspace._change_zoom(0.25)
        self.assertAlmostEqual(workspace.preview_zoom, 1.25)
        workspace._fit_preview_zoom()
        self.assertEqual(workspace.preview_zoom, 1.0)
        workspace._push_undo_snapshot()
        workspace.markup_items.append((0, MarkupAnnotation("rect", 1, 2, 3, 4)))
        workspace.undo()
        self.assertEqual(workspace.markup_items, [])

    def test_document_workspace_modes_include_crop(self):
        workspace = DocumentWorkspace()
        mode_ids = []
        for button in workspace.mode_group.buttons():
            mode_ids.append(button.property("mode_id"))
        self.assertIn("crop", mode_ids)
        crop_index = mode_ids.index("crop")
        workspace.mode_group.button(crop_index).click()
        self.assertEqual(workspace.interaction, "crop")
        self.assertEqual(workspace.right_stack.currentIndex(), crop_index)

    def test_document_workspace_annotate_tools_include_callout_shapes(self):
        workspace = DocumentWorkspace()
        slugs = {workspace.markup_tool_combo.itemData(index) for index in range(workspace.markup_tool_combo.count())}
        self.assertTrue({"callout", "speech", "cloud", "note"}.issubset(slugs))

    def test_document_workspace_signature_stores_rect(self):
        workspace = DocumentWorkspace()
        workspace.open_path(self.source)
        workspace.preview_image = _white_image(300, 400)
        workspace.page_size = (300.0, 400.0)
        workspace.page_images[0] = workspace.preview_image
        workspace.page_sizes[0] = workspace.page_size
        workspace.signature_image_path = self.source
        workspace.interaction = "signature"
        workspace._set_signature_rect_from_drag(QPoint(60, 100), QPoint(240, 300))
        self.assertIsNotNone(workspace.signature_rect)
        x, y, width, height = workspace.signature_rect
        self.assertAlmostEqual(x, 60.0, places=1)
        self.assertAlmostEqual(width, 180.0, places=1)
        self.assertGreater(height, 0)

    def test_document_workspace_bookmark_save_applies_outline(self):
        workspace = DocumentWorkspace()
        workspace.open_path(self.source)
        workspace.bookmark_title_input.setText("總覽")
        workspace.bookmark_page_input.setText("2")
        workspace._add_bookmark_item()
        target = Path(self.temp_dir.name) / "workspace-bookmarked.pdf"

        with patch("document_workspace.QFileDialog.getSaveFileName", return_value=(str(target), "PDF files (*.pdf)")):
            with patch.object(workspace, "_offer_reload_output"):
                workspace._save_bookmark_outline()

        self.assertTrue(target.exists())
        outline = PdfReader(str(target)).outline
        self.assertEqual(len(outline), 1)
        self.assertEqual(str(outline[0].title), "總覽")

    def test_tool_operations_include_workspace_tools(self):
        slugs = {slug for slug, _title in TOOL_OPERATIONS}
        for key in (
            "insert_pages",
            "replace_pages",
            "compress_advanced",
            "compare_text",
            "compare_visual",
            "split_bookmarks",
            "stamp_image",
            "text_stamp",
            "flatten_forms",
            "search_markup",
            "secure_redact",
        ):
            self.assertIn(key, slugs)
        self.assertNotIn("office_to_pdf", slugs)

    def test_office_convert_tab_accepts_office_files(self):
        window = VictorPdfToolsQt()
        word = Path(self.temp_dir.name) / "memo.docx"
        word.write_bytes(b"fake")
        window.add_office_files_from_paths([word])
        self.assertEqual(len(window.office_file_items), 1)
        window.drop_office_files([str(word)])
        self.assertEqual(len(window.office_file_items), 2)
        self.assertEqual(window.main_tabs.tabText(window.main_tabs.indexOf(window._office_tab)), "Office 轉 PDF")
        self.assertNotIn("office_to_pdf", BATCHABLE_OPERATIONS)

    def test_office_convert_tab_writes_output(self):
        window = VictorPdfToolsQt()
        word = Path(self.temp_dir.name) / "memo.docx"
        word.write_bytes(b"fake")
        window.office_file_items = [word]
        window.refresh_office_file_list()
        window.office_output_mode.setCurrentIndex(window.office_output_mode.findData("merge"))
        target = Path(self.temp_dir.name) / "memo.pdf"
        window.office_open_pdf_tab_checkbox.setChecked(False)

        def fake_convert(paths, dest, progress=None, pump=None):
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=400)
            with dest.open("wb") as stream:
                writer.write(stream)
            return len(paths)

        with patch("qt_app.QFileDialog.getSaveFileName", return_value=(str(target), "pdf")):
            with patch("qt_app.office_files_to_pdf", side_effect=fake_convert):
                with patch.object(window, "run_pdf_job", side_effect=lambda job, *_a, **_k: job()):
                    window.run_office_convert()
        self.assertTrue(target.exists())
        self.assertIn("轉成 PDF", window._last_tool_status_message)

    def test_office_convert_uses_original_filename_and_opens_pdf(self):
        window = VictorPdfToolsQt()
        source = Path(self.temp_dir.name) / "中海宏洋2026年中期业绩简报 v.1.pptx"
        source.write_bytes(b"fake")
        window.office_file_items = [source]
        window.refresh_office_file_list()
        window.office_open_pdf_checkbox.setChecked(True)
        window.office_open_pdf_tab_checkbox.setChecked(False)
        target = Path(self.temp_dir.name) / "中海宏洋2026年中期业绩简报 v.1.pdf"

        def fake_convert(paths, dest, progress=None, pump=None):
            if progress is not None:
                progress(1, 2, "正在匯出第 1 / 1 頁")
            if pump is not None:
                pump()
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=400)
            with dest.open("wb") as stream:
                writer.write(stream)
            return len(paths)

        with patch("qt_app.QFileDialog.getSaveFileName", return_value=(str(target), "pdf")) as save_dialog:
            with patch("qt_app.office_files_to_pdf", side_effect=fake_convert):
                with patch("qt_app.open_output_file") as opener:
                    window.run_office_convert()
        self.assertIn("中海宏洋2026年中期业绩简报 v.1.pdf", save_dialog.call_args[0][2])
        opener.assert_called_once_with(target)
        self.assertEqual(window.office_progress.value(), 100)

    def test_batchable_operations_cover_common_tools(self):
        for expected in ("rotate", "compress", "watermark", "add_page_numbers", "clean_metadata"):
            self.assertIn(expected, BATCHABLE_OPERATIONS)
        self.assertNotIn("merge", BATCHABLE_OPERATIONS)

    def test_tool_batch_rotate_writes_each_pdf(self):
        window = VictorPdfToolsQt()
        window.tool_file_items = [self.source, self.second_source]
        window.refresh_tool_file_list()
        window.tool_operation.setCurrentIndex(window.tool_operation.findData("rotate"))
        window.tool_batch_checkbox.setChecked(True)
        for checkbox in (
            window.tool_open_pdf_tab_checkbox,
            window.tool_open_output_folder_checkbox,
        ):
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)
        out_dir = Path(self.temp_dir.name) / "batch_out"
        out_dir.mkdir()
        with patch("qt_app.QFileDialog.getExistingDirectory", return_value=str(out_dir)):
            with patch.object(window, "run_pdf_job", side_effect=lambda job, *_a, **_k: job()):
                window.run_tool_operation()
        self.assertTrue((out_dir / "source_rotate.pdf").exists())
        self.assertTrue((out_dir / "second_rotate.pdf").exists())
        self.assertIn("批次完成", window._last_tool_status_message)

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

    def test_annotation_tab_has_text_frame_choices(self):
        window = VictorPdfToolsQt()
        slugs = {
            window.annotation_shape_list.item(index).data(Qt.UserRole)
            for index in range(window.annotation_shape_list.count())
        }
        self.assertTrue({"box", "rect", "callout", "speech", "cloud"}.issubset(slugs))
        window.set_annotation_shape("speech")
        self.assertEqual(window.annotation_shape(), "speech")
        style = window.annotation_style_values()
        self.assertEqual(style["shape"], "speech")
        self.assertFalse(window.annotation_cover_checkbox.isEnabled())
        self.assertEqual(window.annotation_xy_label.text(), "插入點（箭咀尖端）")

    def test_annotation_callout_click_uses_arrow_as_insert_point(self):
        window = VictorPdfToolsQt()
        window.set_annotation_pdf(self.source)
        window.set_annotation_shape("cloud")
        window.annotation_width_input.setText("120")
        window.annotation_height_input.setText("40")
        window.annotation_page_size = (300.0, 400.0)
        window.annotation_preview_image = _white_image(300, 400)
        window.set_annotation_position_from_click(QPoint(150, 200))
        style = window.annotation_style_values()
        self.assertAlmostEqual(style["pointer_x"], 150.0, delta=1)
        self.assertAlmostEqual(style["pointer_y"], 200.0, delta=1)
        self.assertGreater(style["pdf_y"], style["pointer_y"])
        self.assertAlmostEqual(style["pdf_x"], 150.0 - 60.0, delta=1)
        self.assertIn("插入點", window.statusBar().currentMessage())

    def test_organize_grid_manual_reorder_setup(self):
        from PySide6.QtWidgets import QListWidget

        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        grid = window.page_grid

        # Internal reorder is manual; Qt DnD is only for external file drops.
        self.assertTrue(grid.acceptDrops())
        self.assertFalse(grid.dragEnabled())
        self.assertEqual(grid.dragDropMode(), QListWidget.DropOnly)

    def test_insertion_index_at_uses_item_position(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        grid = window.page_grid
        grid.resize(900, 700)
        grid.show()
        self.app.processEvents()

        rect0 = grid.visualItemRect(grid.item(0))
        left_point = QPoint(rect0.left() + 2, rect0.center().y())
        right_point = QPoint(rect0.right() - 2, rect0.center().y())
        self.assertEqual(grid.insertion_index_at(left_point), 0)
        self.assertEqual(grid.insertion_index_at(right_point), 1)

    def test_manual_drag_emits_reorder_request(self):
        window = VictorPdfToolsQt()
        window.add_files_from_paths([str(self.source)])
        grid = window.page_grid
        grid.resize(900, 700)
        grid.show()
        self.app.processEvents()
        before = [item.page_index for item in window.page_items]

        captured = []
        grid.reorderRequested.connect(lambda rows, target: captured.append((rows, target)))

        # Simulate a manual drag of page 0 dropped after page 1.
        grid._dragging = True
        grid._drag_rows = [0]
        rect1 = grid.visualItemRect(grid.item(1))

        from PySide6.QtCore import QPointF

        class _Evt:
            def position(self_inner):
                return QPointF(rect1.right() - 2, rect1.center().y())

        grid.mouseReleaseEvent(_Evt())

        self.assertEqual(captured, [([0], 2)])
        # The connected handler should have reordered the model.
        self.assertEqual([item.page_index for item in window.page_items], list(reversed(before)))

    def test_bookmark_add_edit_and_reorder(self):
        window = VictorPdfToolsQt()
        window.set_bookmark_pdf(self.source)

        window.bookmark_title_input.setText("第一章")
        window.bookmark_page_input.setText("1")
        window.bookmark_level_combo.setCurrentIndex(0)
        window.add_bookmark_item()

        window.bookmark_title_input.setText("第二章")
        window.bookmark_page_input.setText("2")
        window.add_bookmark_item()

        self.assertEqual(len(window.bookmark_items), 2)
        self.assertEqual(window.bookmark_items[1].title, "第二章")
        self.assertEqual(window.bookmark_items[1].page_index, 1)

        window.bookmark_list.setCurrentRow(1)
        window.move_bookmark_item(-1)
        self.assertEqual(window.bookmark_items[0].title, "第二章")

        window.bookmark_list.setCurrentRow(0)
        window.indent_bookmark_item(1)
        self.assertEqual(window.bookmark_items[0].level, 1)

        window.bookmark_list.setCurrentRow(0)
        window.delete_selected_bookmark()
        self.assertEqual(len(window.bookmark_items), 1)
        self.assertEqual(window.bookmark_items[0].title, "第一章")

    def test_bookmark_save_applies_outline(self):
        window = VictorPdfToolsQt()
        window.set_bookmark_pdf(self.source)
        window.bookmark_title_input.setText("總覽")
        window.bookmark_page_input.setText("2")
        window.add_bookmark_item()
        target = Path(self.temp_dir.name) / "bookmarked.pdf"

        with patch("qt_app.QFileDialog.getSaveFileName", return_value=(str(target), "PDF files (*.pdf)")):
            with patch.object(window, "open_pdf_as_new_tab"):
                window.save_bookmark_pdf()

        self.assertTrue(target.exists())
        outline = PdfReader(str(target)).outline
        self.assertEqual(len(outline), 1)
        self.assertEqual(str(outline[0].title), "總覽")

    def test_bookmark_load_extracts_existing_outline(self):
        bookmarked = Path(self.temp_dir.name) / "with-outline.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.add_blank_page(width=300, height=400)
        writer.add_outline_item("既有書籤", 1)
        with bookmarked.open("wb") as stream:
            writer.write(stream)

        window = VictorPdfToolsQt()
        window.set_bookmark_pdf(bookmarked)

        self.assertEqual(len(window.bookmark_items), 1)
        self.assertEqual(window.bookmark_items[0].title, "既有書籤")
        self.assertEqual(window.bookmark_items[0].page_index, 1)

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

    def test_markup_add_rect_records_item_on_current_page(self):
        window = VictorPdfToolsQt()
        window.set_markup_pdf(self.source)
        window.markup_page_size = (300.0, 400.0)
        window.markup_preview_image = _white_image(300, 400)
        window.markup_page_input.setText("1")
        window.markup_tool_combo.setCurrentIndex(0)  # highlight

        window.add_markup_from_rect(QPoint(30, 40), QPoint(150, 80))

        self.assertEqual(len(window.markup_items), 1)
        page_index, markup = window.markup_items[0]
        self.assertEqual(page_index, 0)
        self.assertEqual(markup.kind, "highlight")
        self.assertGreater(markup.x1, markup.x0)

    def test_markup_note_uses_point_click(self):
        window = VictorPdfToolsQt()
        window.set_markup_pdf(self.source)
        window.markup_page_size = (300.0, 400.0)
        window.markup_preview_image = _white_image(300, 400)
        note_index = window.markup_tool_combo.findData("note")
        window.markup_tool_combo.setCurrentIndex(note_index)
        window.markup_note_input.setText("看這裡")

        window.add_markup_from_point(QPoint(60, 60))

        self.assertEqual(len(window.markup_items), 1)
        _page_index, markup = window.markup_items[0]
        self.assertEqual(markup.kind, "note")
        self.assertEqual(markup.contents, "看這裡")

    def test_markup_callout_uses_drag_from_pointer_to_box(self):
        window = VictorPdfToolsQt()
        window.set_markup_pdf(self.source)
        window.markup_page_size = (300.0, 400.0)
        window.markup_preview_image = _white_image(300, 400)
        callout_index = window.markup_tool_combo.findData("callout")
        self.assertGreaterEqual(callout_index, 0)
        window.markup_tool_combo.setCurrentIndex(callout_index)
        window.markup_note_input.setText("請核對")

        window.add_markup_from_rect(QPoint(40, 80), QPoint(180, 40))

        self.assertEqual(len(window.markup_items), 1)
        _page_index, markup = window.markup_items[0]
        self.assertEqual(markup.kind, "callout")
        self.assertEqual(markup.contents, "請核對")
        slugs = {slug for slug, _label in window.MARKUP_TOOL_OPTIONS}
        self.assertTrue({"callout", "speech", "cloud"}.issubset(slugs))

    def test_markup_delete_and_clear(self):
        window = VictorPdfToolsQt()
        window.set_markup_pdf(self.source)
        window.markup_page_size = (300.0, 400.0)
        window.markup_preview_image = _white_image(300, 400)
        window.add_markup_from_rect(QPoint(10, 10), QPoint(80, 40))
        window.add_markup_from_rect(QPoint(10, 60), QPoint(80, 90))

        window.markup_list.setCurrentRow(0)
        window.delete_selected_markup()
        self.assertEqual(len(window.markup_items), 1)

        window.clear_markups()
        self.assertEqual(window.markup_items, [])

    def test_markup_save_applies_annotations(self):
        window = VictorPdfToolsQt()
        window.set_markup_pdf(self.source)
        window.markup_page_size = (300.0, 400.0)
        window.markup_preview_image = _white_image(300, 400)
        window.add_markup_from_rect(QPoint(10, 10), QPoint(120, 40))
        target = Path(self.temp_dir.name) / "marked.pdf"

        with patch("qt_app.QFileDialog.getSaveFileName", return_value=(str(target), "PDF files (*.pdf)")):
            with patch.object(window, "open_pdf_as_new_tab"):
                window.save_markup_pdf()

        self.assertTrue(target.exists())
        self.assertEqual(len(PdfReader(str(target)).pages[0].get("/Annots")), 1)

    def test_crop_drag_sets_rect_inputs(self):
        window = VictorPdfToolsQt()
        window.set_crop_pdf(self.source)
        window.crop_page_size = (300.0, 400.0)
        window.crop_preview_image = _white_image(300, 400)

        window.set_crop_rect_from_drag(QPoint(60, 100), QPoint(240, 300))

        self.assertIsNotNone(window.crop_rect)
        left, bottom, right, top = window.crop_rect
        self.assertAlmostEqual(left, 60.0, places=1)
        self.assertAlmostEqual(right, 240.0, places=1)
        # widget y is top-down, PDF y is bottom-up
        self.assertAlmostEqual(top, 300.0, places=1)
        self.assertAlmostEqual(bottom, 100.0, places=1)

    def test_crop_save_writes_cropbox(self):
        window = VictorPdfToolsQt()
        window.set_crop_pdf(self.source)
        window.crop_page_size = (300.0, 400.0)
        window.crop_preview_image = _white_image(300, 400)
        window.set_crop_rect((40.0, 50.0, 220.0, 320.0))
        window.crop_scope_combo.setCurrentIndex(window.crop_scope_combo.findData("all"))
        target = Path(self.temp_dir.name) / "cropped.pdf"

        with patch("qt_app.QFileDialog.getSaveFileName", return_value=(str(target), "PDF files (*.pdf)")):
            with patch.object(window, "open_pdf_as_new_tab"):
                window.save_crop_pdf()

        self.assertTrue(target.exists())
        box = PdfReader(str(target)).pages[0].cropbox
        self.assertEqual(
            [float(box.left), float(box.bottom), float(box.right), float(box.top)],
            [40.0, 50.0, 220.0, 320.0],
        )


    def test_tool_split_advanced_creates_zip(self):
        window = VictorPdfToolsQt()
        window.tool_file_items = [self.source]
        window.tool_operation.setCurrentIndex(window.tool_operation.findData("split_advanced"))
        window.tool_split_mode_combo.setCurrentIndex(window.tool_split_mode_combo.findData("every"))
        window.tool_split_value_input.setText("1")
        target = Path(self.temp_dir.name) / "advanced.zip"

        with patch("qt_app.QFileDialog.getSaveFileName", return_value=(str(target), "ZIP files (*.zip)")):
            with patch("qt_app.reveal_output"):
                window.run_tool_operation()

        self.assertTrue(target.exists())

    def test_tool_bates_numbering_writes_pdf(self):
        window = VictorPdfToolsQt()
        window.tool_file_items = [self.source]
        window.tool_operation.setCurrentIndex(window.tool_operation.findData("bates"))
        window.tool_bates_prefix_input.setText("DOC-")
        window.tool_bates_start_input.setText("5")
        window.tool_bates_digits_combo.setCurrentText("4")
        target = Path(self.temp_dir.name) / "bates.pdf"

        with patch("qt_app.QFileDialog.getSaveFileName", return_value=(str(target), "PDF files (*.pdf)")):
            with patch.object(window, "open_pdf_as_new_tab"):
                window.run_tool_operation()

        self.assertTrue(target.exists())
        first = PdfReader(str(target)).pages[0].get("/Annots")[0].get_object()
        self.assertEqual(str(first.get("/Contents")), "DOC-0005")

    def test_tool_encrypt_permissions_writes_protected_pdf(self):
        window = VictorPdfToolsQt()
        window.tool_file_items = [self.source]
        window.tool_operation.setCurrentIndex(window.tool_operation.findData("encrypt_permissions"))
        window.tool_new_password_input.setText("owner999")
        window.tool_perm_print_checkbox.setChecked(False)
        target = Path(self.temp_dir.name) / "protected.pdf"

        with patch("qt_app.QFileDialog.getSaveFileName", return_value=(str(target), "PDF files (*.pdf)")):
            with patch.object(window, "open_pdf_as_new_tab"):
                window.run_tool_operation()

        self.assertTrue(target.exists())
        self.assertTrue(PdfReader(str(target)).is_encrypted)


    def test_text_edit_save_seamless_mode_uses_seamless_replacement(self):
        window = VictorPdfToolsQt()
        window.set_text_edit_pdf(self.source)
        window.text_edit_blocks = [
            TextBlock(
                "Old",
                72,
                320,
                30,
                20,
                12,
                "Helvetica",
                bbox=(72.0, 300.0, 102.0, 325.0),
                page_font_name="helv",
            )
        ]
        window.refresh_text_edit_blocks()
        window.text_edit_block_list.setCurrentRow(0)
        window.text_edit_replacement_input.setPlainText("New")
        target = Path(self.temp_dir.name) / "seamless-edited.pdf"

        with patch("qt_app.QFileDialog.getSaveFileName", return_value=(str(target), "PDF files (*.pdf)")):
            with patch("qt_app.replace_text_block_seamless") as seamless:
                with patch.object(window, "open_pdf_as_new_tab"):
                    window.save_text_edit_pdf()

        seamless.assert_called_once()


def _white_image(width: int, height: int):
    from PIL import Image

    return Image.new("RGB", (width, height), "white")


if __name__ == "__main__":
    unittest.main()
