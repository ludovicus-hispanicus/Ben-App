from pdf2image import convert_from_bytes
import platform
from io import BytesIO


class PdfUtils:

    def __init__(self):
        pass

    @staticmethod
    def extract_page_as_png(pdf_bytes: bytes, page: int) -> bytes:
        pdf_page = PdfUtils._extract_page_bytes(pdf_bytes=pdf_bytes, page=page)
        page_png_bytes = BytesIO()
        pdf_page.save(page_png_bytes, format="png")
        return page_png_bytes.getvalue()

    @staticmethod
    def _extract_page_bytes(pdf_bytes, page: int = 0):
        popler_path = None
        if platform.system() == 'Windows':
            popler_path = r"C:\Program Files\ForPython\poppler-22.01.0\Library\bin"

        result = convert_from_bytes(pdf_bytes, first_page=page, last_page=page, poppler_path=popler_path)
        return result[0]
