"""Typhoon OCR service using direct HTTP image requests.

This service standardizes OCR around a single path:
PDF page -> render page to PNG -> send PNG to Typhoon OCR

It avoids the old ``typhoon_ocr`` SDK / OpenAI client stack, which was the
source of the ``proxies`` compatibility error in this project environment.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import tempfile
import time
from typing import Any, Dict, List, Optional

import httpx
from PIL import Image
from pypdf import PdfReader

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


PROMPT_V15 = """Extract all text from the image.

Instructions:
- Only return the clean Markdown.
- Do not include any explanation or extra text.
- You must include all information on the page.

Formatting Rules:
- Tables: Render tables using <table>...</table> in clean HTML format.
- Equations: Render equations using LaTeX syntax with inline ($...$) and block ($$...$$).
- Images/Charts/Diagrams: Wrap any clearly defined visual areas in:

<figure>
Describe the image's main elements, visible text, and overall meaning in Thai.
</figure>

- Page Numbers: Wrap page numbers in <page_number>...</page_number>.
- Checkboxes: Use \u2610 for unchecked and \u2611 for checked boxes.
"""


class TyphoonOCRService:
    """Calls Typhoon OCR and normalizes the Markdown response."""

    def __init__(self) -> None:
        self.api_key = settings.TYPHOON_OCR_API_KEY or settings.TYPHOON_API_KEY
        self.model = settings.TYPHOON_OCR_MODEL
        self.figure_language = "Thai"
        self.base_url = self._derive_base_url(settings.TYPHOON_OCR_ENDPOINT)
        self.render_dpi = max(int(settings.TYPHOON_OCR_RENDER_DPI or 300), 72)
        self.timeout_seconds = max(float(settings.TYPHOON_OCR_REQUEST_TIMEOUT or 180.0), 1.0)
        self.sleep_seconds = max(float(settings.TYPHOON_OCR_SLEEP_SECONDS or 0.7), 0.0)
        self.max_tokens = int(settings.TYPHOON_OCR_MAX_TOKENS or 16384)
        self.temperature = float(settings.TYPHOON_OCR_TEMPERATURE or 0.1)
        self.top_p = float(settings.TYPHOON_OCR_TOP_P or 0.6)
        self.repetition_penalty = float(settings.TYPHOON_OCR_REPETITION_PENALTY or 1.2)

    def _derive_base_url(self, endpoint: str) -> str:
        endpoint = (endpoint or "").strip()
        if not endpoint:
            return "https://api.opentyphoon.ai/v1"
        endpoint = endpoint.rstrip("/")
        if endpoint.endswith("/ocr"):
            return endpoint[: -len("/ocr")]
        if endpoint.endswith("/chat/completions"):
            return endpoint[: -len("/chat/completions")]
        return endpoint

    async def extract_from_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        filename: str = "image.png",
    ) -> Dict[str, Any]:
        """Extract text and tables from a single image."""
        if not self.api_key:
            raise RuntimeError("Typhoon OCR API key is not configured")

        png_bytes = self._normalize_image_to_png(image_bytes, filename, mime_type)
        markdown = await asyncio.to_thread(self._ocr_png_bytes, png_bytes)
        return self._parse_markdown_pages([{"page": 1, "markdown": markdown}])

    async def extract_from_pdf(
        self,
        pdf_bytes: bytes,
        filename: str = "document.pdf",
        pages: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Extract text and tables from requested PDF pages."""
        if not self.api_key:
            raise RuntimeError("Typhoon OCR API key is not configured")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        try:
            return await self.extract_from_pdf_path(tmp_path, filename=filename, pages=pages)
        finally:
            self._safe_unlink(tmp_path)

    async def extract_from_pdf_path(
        self,
        pdf_path: str,
        filename: str = "document.pdf",
        pages: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Extract text and tables from a PDF already stored on disk."""
        if not self.api_key:
            raise RuntimeError("Typhoon OCR API key is not configured")

        page_numbers = pages or self._all_pdf_pages(pdf_path)
        outputs: List[Dict[str, Any]] = []
        for index, page_num in enumerate(page_numbers):
            markdown = await asyncio.to_thread(self._ocr_pdf_page, pdf_path, page_num)
            outputs.append({"page": page_num, "markdown": markdown})
            if index < len(page_numbers) - 1 and self.sleep_seconds > 0:
                await asyncio.sleep(self.sleep_seconds)
        return self._parse_markdown_pages(outputs)

    def get_pdf_page_count(self, pdf_path: str) -> int:
        return len(PdfReader(pdf_path).pages)

    def _ocr_single_page(self, path: str, page_num: int) -> str:
        """Compatibility hook used by table extraction helpers."""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            return self._ocr_pdf_page(path, page_num)
        with open(path, "rb") as handle:
            image_bytes = handle.read()
        png_bytes = self._normalize_image_to_png(image_bytes, path, self._mime_from_extension(ext))
        return self._ocr_png_bytes(png_bytes)

    def _ocr_pdf_page(self, pdf_path: str, page_num: int) -> str:
        png_bytes = self._render_pdf_page_to_png(pdf_path, page_num)
        return self._ocr_png_bytes(png_bytes)

    def _ocr_png_bytes(self, png_bytes: bytes) -> str:
        last_error: Optional[str] = None
        for attempt in range(1, 4):
            try:
                return self._request_markdown(png_bytes)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Typhoon OCR failed on attempt %d/3: %s",
                    attempt,
                    last_error,
                )
                if attempt < 3:
                    time.sleep(10 + (attempt - 1) * 10)
        raise RuntimeError(last_error or "Typhoon OCR request failed")

    def _request_markdown(self, png_bytes: bytes) -> str:
        payload = self._build_payload(png_bytes)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = client.post("/chat/completions", json=payload)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1000]
            raise RuntimeError(f"Typhoon OCR HTTP {exc.response.status_code}: {body}") from exc

        data = response.json()
        content = self._extract_message_content(data)
        return content.strip()

    def _build_payload(self, png_bytes: bytes) -> Dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT_V15},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii"),
                            },
                        },
                    ],
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "repetition_penalty": self.repetition_penalty,
        }

    def _extract_message_content(self, payload: Dict[str, Any]) -> str:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Typhoon OCR response shape: {json.dumps(payload)[:1200]}") from exc

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            return "\n".join(part for part in parts if part)
        return str(content or "")

    def _render_pdf_page_to_png(self, pdf_path: str, page_num: int) -> bytes:
        try:
            import pypdfium2 as pdfium

            document = pdfium.PdfDocument(pdf_path)
            page = document[page_num - 1]
            bitmap = None
            try:
                bitmap = page.render(
                    scale=self.render_dpi / 72.0,
                    rev_byteorder=True,
                    optimize_mode="print",
                )
                image = bitmap.to_pil().convert("RGB")
                return self._image_to_png_bytes(image)
            finally:
                if bitmap is not None:
                    bitmap.close()
                page.close()
                document.close()
        except Exception as primary_exc:
            logger.debug("pypdfium2 render failed for page %s: %s", page_num, primary_exc)

        try:
            import fitz

            document = fitz.open(pdf_path)
            try:
                page = document.load_page(page_num - 1)
                matrix = fitz.Matrix(self.render_dpi / 72.0, self.render_dpi / 72.0)
                pixmap = page.get_pixmap(matrix=matrix)
                return pixmap.tobytes("png")
            finally:
                document.close()
        except Exception as exc:
            raise RuntimeError(f"Failed to render PDF page {page_num}: {exc}") from exc

    def _normalize_image_to_png(self, image_bytes: bytes, filename: str, mime_type: str) -> bytes:
        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                image.load()
                rgb = image.convert("RGB")
                return self._image_to_png_bytes(rgb)
        except Exception as exc:
            raise RuntimeError(f"Failed to decode image {filename} ({mime_type}): {exc}") from exc

    def _image_to_png_bytes(self, image: Image.Image) -> bytes:
        with io.BytesIO() as buffer:
            image.save(buffer, format="PNG")
            return buffer.getvalue()

    def _all_pdf_pages(self, path: str) -> List[int]:
        reader = PdfReader(path)
        return list(range(1, len(reader.pages) + 1))

    def _mime_from_extension(self, ext: str) -> str:
        if ext in {".jpg", ".jpeg"}:
            return "image/jpeg"
        return "image/png"

    def _parse_markdown_pages(self, page_outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        text_blocks: List[str] = []
        tables: List[Dict[str, Any]] = []
        raw_tables: List[Dict[str, Any]] = []
        pages: List[Dict[str, Any]] = []

        for output in page_outputs:
            page_num = output["page"]
            markdown = output.get("markdown", "") or ""
            page_tables, text_only = self._extract_structured_tables(markdown)
            for table in page_tables:
                table["page"] = page_num
            cleaned = self._clean_layout_markup(text_only)
            page_blocks = self._split_text_blocks(cleaned)

            text_blocks.extend(page_blocks)
            tables.extend(page_tables)
            raw_tables.extend(
                {
                    "page": page_num,
                    "title": table.get("title", ""),
                    "headers": list(table.get("headers", []) or []),
                    "rows": [list(row) for row in (table.get("rows", []) or [])],
                }
                for table in page_tables
            )
            pages.append(
                {
                    "page": page_num,
                    "markdown": markdown,
                    "text_blocks": len(page_blocks),
                    "tables": len(page_tables),
                }
            )

        return {
            "text_blocks": text_blocks,
            "tables": tables,
            "raw_tables": raw_tables,
            "pages": pages,
            "raw_pages": [{"page": page["page"], "markdown": page.get("markdown", "")} for page in pages],
            "errors": [],
        }

    def _clean_layout_markup(self, markdown: str) -> str:
        if not markdown:
            return ""

        markdown = re.sub(r"</?figure[^>]*>", "", markdown, flags=re.IGNORECASE)
        markdown = re.sub(r"</?figcaption[^>]*>", "", markdown, flags=re.IGNORECASE)
        markdown = re.sub(r"<[^>]+>", "", markdown)
        markdown = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", markdown)
        markdown = re.sub(r"\n{3,}", "\n\n", markdown)
        return markdown.strip()

    def _split_text_blocks(self, content: str) -> List[str]:
        if not content:
            return []

        blocks = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
        unique_blocks: List[str] = []
        seen = set()
        for block in blocks:
            key = re.sub(r"\s+", " ", block)
            if key in seen:
                continue
            seen.add(key)
            unique_blocks.append(block)
        return unique_blocks

    def _extract_structured_tables(self, content: str) -> tuple[List[Dict[str, Any]], str]:
        html_tables, without_html = self._extract_html_tables(content)
        markdown_tables, without_markdown = self._extract_markdown_tables(without_html)
        return html_tables + markdown_tables, without_markdown

    def _extract_html_tables(self, content: str) -> tuple[List[Dict[str, Any]], str]:
        tables: List[Dict[str, Any]] = []
        content_before = content

        def repl(match: re.Match) -> str:
            table_html = match.group(0)
            prefix = content_before[:match.start()]
            title = self._infer_table_title_from_prefix(prefix)
            rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.IGNORECASE | re.DOTALL)
            parsed_rows: List[List[str]] = []

            for row_html in rows_html:
                cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row_html, flags=re.IGNORECASE | re.DOTALL)
                cleaned_cells = [self._clean_layout_markup(cell) for cell in cells]
                if any(cell.strip() for cell in cleaned_cells):
                    parsed_rows.append(cleaned_cells)

            if not parsed_rows:
                return ""

            headers = parsed_rows[0]
            data_rows = parsed_rows[1:] if len(parsed_rows) > 1 else []
            if data_rows:
                tables.append({"title": title, "headers": headers, "rows": data_rows})
            return ""

        without_tables = re.sub(
            r"<table[^>]*>.*?</table>",
            repl,
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return tables, without_tables

    def _infer_table_title_from_prefix(self, prefix: str) -> str:
        lines = [self._clean_layout_markup(line) for line in prefix.splitlines()]
        lines = [line.strip() for line in lines if line and line.strip()]

        ignored_patterns = (
            r"^\(เธซเธเนเธงเธข.*\)$",
            r"^เธ“ เธงเธฑเธเธ—เธตเน",
            r"^เธเธเธฒเธเธฒเธฃเธเธฃเธธเธเธจเธฃเธตเธญเธขเธธเธเธขเธฒ",
            r"^เนเธเธ 56-1",
            r"^เธฃเธฒเธขเธเธฒเธเธเธฃเธฐเธเธณเธเธต",
            r"^<page_number>",
        )

        for line in reversed(lines):
            if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in ignored_patterns):
                continue
            if len(line) < 4:
                continue
            return line

        return ""

    def _extract_markdown_tables(self, content: str) -> tuple[List[Dict[str, Any]], str]:
        lines = [line.strip() for line in content.splitlines()]
        tables: List[Dict[str, Any]] = []
        text_lines: List[str] = []
        i = 0

        while i < len(lines):
            if not self._looks_like_markdown_row(lines[i]):
                text_lines.append(lines[i])
                i += 1
                continue

            if i + 1 >= len(lines) or not self._is_markdown_separator(lines[i + 1]):
                text_lines.append(lines[i])
                i += 1
                continue

            headers = self._split_markdown_row(lines[i])
            i += 2
            rows: List[List[str]] = []
            title = ""

            while i < len(lines) and self._looks_like_markdown_row(lines[i]):
                row = self._split_markdown_row(lines[i])
                non_empty = [cell for cell in row if cell]

                if not rows and len(non_empty) == 1:
                    title = non_empty[0]
                    i += 1
                    continue

                if row:
                    rows.append(row)
                i += 1

            if headers and rows:
                tables.append({"title": title, "headers": headers, "rows": rows})

        text_only = "\n".join(line for line in text_lines if line).strip()
        return tables, text_only

    def _looks_like_markdown_row(self, line: str) -> bool:
        return line.count("|") >= 2

    def _is_markdown_separator(self, line: str) -> bool:
        cleaned = line.replace("|", "").replace(":", "").replace("-", "").strip()
        return not cleaned and "-" in line

    def _split_markdown_row(self, line: str) -> List[str]:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            parts = stripped[1:-1].split("|")
        else:
            parts = stripped.split("|")
        return [part.strip() for part in parts]

    def _safe_unlink(self, path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass


ocr_service = TyphoonOCRService()
