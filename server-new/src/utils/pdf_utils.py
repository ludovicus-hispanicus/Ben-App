"""
PDF utilities using PyMuPDF (fitz) - fast, standalone, no external dependencies.
"""
import logging
from typing import List

import fitz  # PyMuPDF

logger = logging.getLogger()

DPI = 150  # Good balance of quality and speed


class PdfUtils:

    @staticmethod
    def extract_page_as_png(pdf_bytes: bytes, page: int) -> bytes:
        """
        Extract a single page from a PDF as PNG bytes.

        Args:
            pdf_bytes: The PDF file as bytes
            page: Page number (1-indexed)

        Returns:
            PNG image bytes
        """
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        page_idx = page - 1 if page > 0 else 0
        if page_idx >= doc.page_count:
            doc.close()
            raise ValueError(f"Page {page} does not exist. PDF has {doc.page_count} pages.")

        pdf_page = doc.load_page(page_idx)
        pix = pdf_page.get_pixmap(dpi=DPI)
        png_bytes = pix.tobytes("png")
        doc.close()

        logger.info(f"Extracted page {page} from PDF ({len(png_bytes)} bytes)")
        return png_bytes

    @staticmethod
    def extract_all_pages(pdf_bytes: bytes) -> List[bytes]:
        """
        Extract ALL pages from a PDF as a list of PNG bytes.
        Opens the PDF once and iterates all pages (efficient for bulk conversion).

        Args:
            pdf_bytes: The PDF file as bytes

        Returns:
            List of PNG image bytes, one per page
        """
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for page_idx in range(doc.page_count):
            pdf_page = doc.load_page(page_idx)
            pix = pdf_page.get_pixmap(dpi=DPI)
            pages.append(pix.tobytes("png"))
        doc.close()

        logger.info(f"Extracted {len(pages)} pages from PDF")
        return pages

    @staticmethod
    def get_page_count(pdf_bytes: bytes) -> int:
        """Get the number of pages in a PDF."""
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        count = doc.page_count
        doc.close()
        return count
