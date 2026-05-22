from pathlib import Path
import unittest

from pypdf import PdfReader, PdfWriter

from app import copy_pages, parse_pages
from desktop_app import (
    PageItem,
    add_page_numbers,
    add_text_overlay_annotation,
    add_watermark,
    clean_metadata,
    remove_blank_pages,
    write_page_items_merged,
    write_page_items_separately,
)


class PdfToolsTests(unittest.TestCase):
    def test_parse_pages_keeps_order_and_supports_ranges(self):
        self.assertEqual(parse_pages("1,3,5-7", 10), [0, 2, 4, 5, 6])

    def test_parse_pages_removes_duplicates(self):
        self.assertEqual(parse_pages("1,1,2-3,3", 4), [0, 1, 2])

    def test_copy_pages(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_blank_page(width=100, height=100)
        with source.open("wb") as stream:
            writer.write(stream)

        reader = PdfReader(str(source))
        copied = copy_pages(reader, [1])
        target = Path(self.temp_dir.name) / "target.pdf"
        with target.open("wb") as stream:
            copied.write(stream)

        self.assertEqual(len(PdfReader(str(target)).pages), 1)

    def test_add_text_overlay_annotation(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        target = Path(self.temp_dir.name) / "target.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        with source.open("wb") as stream:
            writer.write(stream)

        add_text_overlay_annotation(
            source=source,
            target=target,
            page_index=0,
            x=72,
            y=300,
            text="Reviewed FY2026",
            font_size=12,
            cover_original=True,
            cover_width=180,
            cover_height=30,
        )

        annots = PdfReader(str(target)).pages[0].get("/Annots")
        self.assertEqual(len(annots), 2)

    def test_add_page_numbers(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        target = Path(self.temp_dir.name) / "target.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.add_blank_page(width=300, height=400)
        with source.open("wb") as stream:
            writer.write(stream)

        add_page_numbers(source, target, "Page {page} of {total}")

        reader = PdfReader(str(target))
        self.assertEqual(len(reader.pages[0].get("/Annots")), 1)
        self.assertEqual(len(reader.pages[1].get("/Annots")), 1)

    def test_add_watermark(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        target = Path(self.temp_dir.name) / "target.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        with source.open("wb") as stream:
            writer.write(stream)

        add_watermark(source, target, "CONFIDENTIAL")

        self.assertEqual(len(PdfReader(str(target)).pages[0].get("/Annots")), 1)

    def test_clean_metadata(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        target = Path(self.temp_dir.name) / "target.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.add_metadata({"/Author": "Sensitive User"})
        with source.open("wb") as stream:
            writer.write(stream)

        clean_metadata(source, target)

        metadata = PdfReader(str(target)).metadata
        self.assertNotEqual(metadata.get("/Author"), "Sensitive User")

    def test_remove_blank_pages_refuses_all_blank_output(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        target = Path(self.temp_dir.name) / "target.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        with source.open("wb") as stream:
            writer.write(stream)

        with self.assertRaises(ValueError):
            remove_blank_pages(source, target)

    def test_write_page_items_merged(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        target = Path(self.temp_dir.name) / "target.pdf"
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=300, height=400)
        with source.open("wb") as stream:
            writer.write(stream)

        page_items = [PageItem(source, index, f"Page {index + 1}") for index in range(3)]
        write_page_items_merged(page_items, [0, 2], target)

        self.assertEqual(len(PdfReader(str(target)).pages), 2)

    def test_write_page_items_merged_applies_rotation(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        target = Path(self.temp_dir.name) / "target.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        with source.open("wb") as stream:
            writer.write(stream)

        page_items = [PageItem(source, 0, "Page 1", rotation=90)]
        write_page_items_merged(page_items, [0], target)

        self.assertEqual(PdfReader(str(target)).pages[0].get("/Rotate"), 90)

    def test_write_page_items_separately(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        folder = Path(self.temp_dir.name) / "out"
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=300, height=400)
        with source.open("wb") as stream:
            writer.write(stream)

        page_items = [PageItem(source, index, f"Page {index + 1}") for index in range(3)]
        count = write_page_items_separately(page_items, [0, 2], folder)

        self.assertEqual(count, 2)
        self.assertEqual(len(list(folder.glob("*.pdf"))), 2)

    def setUp(self):
        import tempfile

        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
