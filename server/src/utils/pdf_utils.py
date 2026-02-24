import fitz  # PyMuPDF


class PdfUtils:

    @staticmethod
    def extract_page_as_png(pdf_bytes: bytes, page: int) -> bytes:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pdf_page = doc.load_page(page)
        pix = pdf_page.get_pixmap(dpi=300)
        png_bytes = pix.tobytes("png")
        doc.close()
        return png_bytes
