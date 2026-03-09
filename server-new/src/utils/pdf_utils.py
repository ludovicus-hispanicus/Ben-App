"""
PDF utilities using PyMuPDF (fitz) - fast, standalone, no external dependencies.
"""
import logging
from typing import List

import fitz  # PyMuPDF

logger = logging.getLogger()

DEFAULT_DPI = 300  # Good quality for OCR


class PdfUtils:

    @staticmethod
    def extract_page_as_png(pdf_bytes: bytes, page: int, dpi: int = None) -> bytes:
        """
        Extract a single page from a PDF as PNG bytes.

        Args:
            pdf_bytes: The PDF file as bytes
            page: Page number (1-indexed)
            dpi: Resolution for rendering (default 150)

        Returns:
            PNG image bytes
        """
        render_dpi = dpi or DEFAULT_DPI
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        page_idx = page - 1 if page > 0 else 0
        if page_idx >= doc.page_count:
            doc.close()
            raise ValueError(f"Page {page} does not exist. PDF has {doc.page_count} pages.")

        pdf_page = doc.load_page(page_idx)
        pix = pdf_page.get_pixmap(dpi=render_dpi)
        png_bytes = pix.tobytes("png")
        doc.close()

        logger.info(f"Extracted page {page} from PDF at {render_dpi} DPI ({len(png_bytes)} bytes)")
        return png_bytes

    @staticmethod
    def extract_all_pages(pdf_bytes: bytes, page_from: int = None, page_to: int = None, dpi: int = None) -> List[bytes]:
        """
        Extract pages from a PDF as a list of PNG bytes.
        Opens the PDF once and iterates pages (efficient for bulk conversion).

        Args:
            pdf_bytes: The PDF file as bytes
            page_from: First page to extract (1-indexed, inclusive). None = start from page 1.
            page_to: Last page to extract (1-indexed, inclusive). None = extract to last page.
            dpi: Resolution for rendering (default 150)

        Returns:
            List of PNG image bytes, one per page
        """
        render_dpi = dpi or DEFAULT_DPI
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total = doc.page_count

        start = (page_from - 1) if page_from and page_from > 0 else 0
        end = page_to if page_to and page_to <= total else total
        start = min(start, total)
        end = max(end, start)

        pages = []
        for page_idx in range(start, end):
            pdf_page = doc.load_page(page_idx)
            pix = pdf_page.get_pixmap(dpi=render_dpi)
            pages.append(pix.tobytes("png"))
        doc.close()

        logger.info(f"Extracted {len(pages)} pages from PDF at {render_dpi} DPI (range {start+1}-{end} of {total})")
        return pages

    @staticmethod
    def get_page_count(pdf_bytes: bytes) -> int:
        """Get the number of pages in a PDF."""
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        count = doc.page_count
        doc.close()
        return count
