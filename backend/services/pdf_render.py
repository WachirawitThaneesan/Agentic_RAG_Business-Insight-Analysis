"""Local PDF page rendering shared by online and offline citation viewers."""
from __future__ import annotations
import io


def render_pdf_page(pdf_path: str, page_number: int, dpi: int = 150) -> bytes:
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(pdf_path)
    try:
        if not 1 <= page_number <= len(document):
            raise ValueError('PDF page is out of range')
        page = document[page_number - 1]
        try:
            bitmap = page.render(scale=max(72, min(int(dpi), 400)) / 72.0)
            try:
                with io.BytesIO() as output:
                    bitmap.to_pil().convert('RGB').save(output, format='PNG')
                    return output.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()
