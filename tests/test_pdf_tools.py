from pathlib import Path
import io
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app import copy_pages, parse_pages
from pdf_core import (
    PageItem,
    TextBlock,
    add_page_numbers,
    add_text_overlay_annotation,
    add_watermark,
    build_annotation_da,
    clean_metadata,
    merge_pdf_files,
    merge_text_blocks,
    ocr_pdf_to_searchable_pdf,
    ocr_pdf_to_text,
    pdf_to_images,
    replace_text_block_content_stream,
    replace_text_block_overlay,
    remove_blank_pages,
    split_pdf_to_zip,
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

    def test_build_annotation_da_supports_bold_and_color(self):
        self.assertEqual(
            build_annotation_da("helvetica", 14, True, (0.8, 0.0, 0.0)),
            "/Helv-Bold 14 Tf 0.8 0.0 0.0 rg",
        )

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

    def test_replace_text_block_overlay(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        target = Path(self.temp_dir.name) / "target.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        with source.open("wb") as stream:
            writer.write(stream)

        replace_text_block_overlay(
            source,
            target,
            0,
            TextBlock("Old", 72, 300, 80, 24, 12, "/Helvetica"),
            "New",
        )

        annots = PdfReader(str(target)).pages[0].get("/Annots")
        self.assertEqual(len(annots), 2)

    def test_replace_text_block_content_stream_rewrites_simple_text(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        target = Path(self.temp_dir.name) / "target.pdf"
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=400)
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 72 300 Td (Old123) Tj ET")
        page[NameObject("/Contents")] = stream
        page[NameObject("/Resources")] = DictionaryObject()
        with source.open("wb") as output:
            writer.write(output)

        replace_text_block_content_stream(
            source,
            target,
            0,
            TextBlock("Old123", 72, 300, 80, 24, 12, "/Helvetica"),
            "New456",
        )

        content = PdfReader(str(target)).pages[0].get_contents().get_data()
        self.assertIn(b"New456", content)
        self.assertNotIn(b"Old123", content)

    def test_replace_text_block_content_stream_requires_same_length(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        target = Path(self.temp_dir.name) / "target.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        with source.open("wb") as output:
            writer.write(output)

        with self.assertRaises(ValueError):
            replace_text_block_content_stream(
                source,
                target,
                0,
                TextBlock("Old123", 72, 300, 80, 24, 12, "/Helvetica"),
                "Longer text",
            )

    def test_merge_text_blocks_combines_same_line_fragments(self):
        blocks = [
            TextBlock("Hello", 10, 100, 30, 12, 10),
            TextBlock("World", 45, 101, 30, 12, 10),
            TextBlock("Next", 10, 70, 24, 12, 10),
        ]

        merged = merge_text_blocks(blocks)

        self.assertEqual([block.text for block in merged], ["Hello World", "Next"])

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

    def test_merge_pdf_files(self):
        first = Path(self.temp_dir.name) / "first.pdf"
        second = Path(self.temp_dir.name) / "second.pdf"
        target = Path(self.temp_dir.name) / "merged.pdf"
        for path in (first, second):
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=400)
            with path.open("wb") as stream:
                writer.write(stream)

        merge_pdf_files([first, second], target)

        self.assertEqual(len(PdfReader(str(target)).pages), 2)

    def test_pdf_to_images_writes_png_files(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        folder = Path(self.temp_dir.name) / "images"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.add_blank_page(width=300, height=400)
        with source.open("wb") as stream:
            writer.write(stream)

        count = pdf_to_images(source, folder, image_format="png", dpi=72)

        self.assertEqual(count, 2)
        self.assertEqual(len(list(folder.glob("*.png"))), 2)

    def test_pdf_to_images_supports_page_ranges(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        folder = Path(self.temp_dir.name) / "images-range"
        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=300, height=400)
        with source.open("wb") as stream:
            writer.write(stream)

        count = pdf_to_images(source, folder, image_format="jpg", dpi=72, pages_spec="1,3")

        self.assertEqual(count, 2)
        self.assertEqual(len(list(folder.glob("*.jpg"))), 2)

    def test_ocr_pdf_to_text_writes_text(self):
        target = Path(self.temp_dir.name) / "ocr.txt"
        with patch("pdf_core.ensure_ocr_available"), patch(
            "pdf_core.render_pdf_page_images",
            return_value=[(0, Image.new("RGB", (10, 10), "white"))],
        ), patch("pdf_core.pytesseract", Mock(image_to_string=Mock(return_value="Hello OCR"))):
            count = ocr_pdf_to_text(Path("source.pdf"), target, language="eng")

        self.assertEqual(count, 1)
        self.assertIn("Hello OCR", target.read_text(encoding="utf-8"))

    def test_ocr_pdf_to_searchable_pdf_merges_ocr_pages(self):
        target = Path(self.temp_dir.name) / "searchable.pdf"
        pdf_stream = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(pdf_stream)
        with patch("pdf_core.ensure_ocr_available"), patch(
            "pdf_core.render_pdf_page_images",
            return_value=[(0, Image.new("RGB", (10, 10), "white"))],
        ), patch(
            "pdf_core.pytesseract",
            Mock(image_to_pdf_or_hocr=Mock(return_value=pdf_stream.getvalue())),
        ):
            count = ocr_pdf_to_searchable_pdf(Path("source.pdf"), target, language="eng")

        self.assertEqual(count, 1)
        self.assertEqual(len(PdfReader(str(target)).pages), 1)

    def test_split_pdf_to_zip(self):
        source = Path(self.temp_dir.name) / "source.pdf"
        target = Path(self.temp_dir.name) / "split.zip"
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=400)
        writer.add_blank_page(width=300, height=400)
        with source.open("wb") as stream:
            writer.write(stream)

        page_count = split_pdf_to_zip(source, target)

        self.assertEqual(page_count, 2)
        self.assertTrue(target.exists())

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
