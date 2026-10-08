"""Document OCR service using Typhoon for text and optional Gemini tables.

PDF pages are rendered once per region. Typhoon reads prose; when a table is
detected, Gemini reads its cells and replaces Typhoon's table interpretation.

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
from backend.services.pdf_layout import crop_and_rotate_png, plan_pdf_regions

settings = get_settings()
logger = logging.getLogger(__name__)


def _unconfirmed_na_text(tables: List[Dict[str, Any]]) -> str:
    """Retain explicit missing-value relations without rescuing numeric cells.

    Gemini may correctly return no matrix for a key/value layout. Preserve only
    literal N/A cells from Typhoon's parsed source, with their row/header/title.
    Never interpret N/A as zero or restore other cells from an unconfirmed table.
    """
    lines = []
    for table in tables:
        headers = table.get('headers') or []
        for row in [headers, *(table.get('rows') or [])]:
            if not row:
                continue
            for index, value in enumerate(row[1:], start=1):
                if str(value).strip().upper() != 'N/A':
                    continue
                # Key/value HTML often starts with an empty indentation cell.
                # A numeric cell cannot become a recovered textual row label.
                row_label = next((str(c).strip().rstrip(':： ') for c in row[:index]
                                  if str(c).strip() and not re.search(r'\d',str(c))), '')
                if not row_label:
                    continue
                header = str(headers[index]) if row is not headers and index < len(headers) else ''
                if header.upper() == 'N/A': header = ''
                label = ' / '.join(x for x in [str(table.get('title') or ''), row_label, header] if x)
                lines.append(f'{label}: N/A')
    return '\n'.join(dict.fromkeys(lines))


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
        if settings.OFFLINE_MODE:
            raise RuntimeError("Typhoon OCR is disabled in OFFLINE_MODE")
        self.api_key = settings.TYPHOON_OCR_API_KEY or settings.TYPHOON_API_KEY
        self.model = settings.TYPHOON_OCR_MODEL
        self.figure_language = "Thai"
        self.base_url = self._derive_base_url(settings.TYPHOON_OCR_ENDPOINT)
        self.render_dpi = max(int(settings.TYPHOON_OCR_RENDER_DPI or 300), 72)
        self.timeout_seconds = max(float(settings.TYPHOON_OCR_REQUEST_TIMEOUT or 180.0), 1.0)
        self.page_timeout_seconds = max(float(settings.TYPHOON_OCR_PAGE_TIMEOUT_SECONDS or 240.0), 1.0)
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
        page_number: int = 1,
    ) -> Dict[str, Any]:
        """Extract text and tables from a single image."""
        if not self.api_key:
            raise RuntimeError("Typhoon OCR API key is not configured")

        png_bytes = self._normalize_image_to_png(image_bytes, filename, mime_type)
        use_gemini_tables = settings.PDF_TABLE_OCR_PROVIDER.lower() == "gemini"
        visual_hint = False
        if use_gemini_tables:
            from backend.services.gemini_tables import image_has_table_hint
            visual_hint = await asyncio.to_thread(image_has_table_hint, png_bytes)
        typhoon_error = None
        try:
            text_deadline = min(self.page_timeout_seconds, 90.0) if visual_hint else self.page_timeout_seconds
            async with asyncio.timeout(text_deadline):
                markdown = await self._ocr_png_bytes_async(png_bytes)
        except Exception as exc:
            if not (use_gemini_tables and visual_hint):
                raise RuntimeError(f"Typhoon OCR image failed: {exc}") from exc
            typhoon_error = f"{type(exc).__name__}: {exc}"
            markdown = ""
        tables = []
        usage = None
        table_warnings = []
        if use_gemini_tables:
            typhoon_tables, text_only = self._extract_structured_tables(markdown)
            if typhoon_tables or visual_hint:
                from backend.services.gemini_tables import extract_tables_from_png
                tables, usage = await extract_tables_from_png(
                    png_bytes, page=page_number, region={"region": "full"},
                )
                if typhoon_error and not tables:
                    raise RuntimeError("Typhoon text failed and Gemini found no table")
                if tables:
                    markdown = text_only
                elif typhoon_tables:
                    markdown = text_only
                    table_warnings.append({
                        "page": page_number, "region": "full",
                        "warning": "Typhoon detected a table but Gemini returned no confirmed cells",
                    })
        result = self._parse_markdown_pages([{"page": page_number, "markdown": markdown}])
        if use_gemini_tables:
            result["tables"] = tables
            result["raw_tables"] = [dict(table) for table in tables]
            result["gemini_table_usage"] = ([{"page": page_number, "region": "full", **usage}] if usage else [])
            result["typhoon_text_errors"] = ([{"page": page_number, "region": "full", "error": typhoon_error}] if typhoon_error else [])
            result["table_extraction_warnings"] = table_warnings
            result["pages"][0]["tables"] = len(tables)
        return result

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
        render_dpi: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Extract text and tables from a PDF already stored on disk."""
        if not self.api_key:
            raise RuntimeError("Typhoon OCR API key is not configured")

        page_numbers = pages or self._all_pdf_pages(pdf_path)
        outputs: List[Dict[str, Any]] = []
        use_gemini_tables = settings.PDF_TABLE_OCR_PROVIDER.lower() == "gemini"
        gemini_tables: List[Dict[str, Any]] = []
        gemini_usage: List[Dict[str, Any]] = []
        typhoon_errors: List[Dict[str, Any]] = []
        table_warnings: List[Dict[str, Any]] = []
        for index, page_num in enumerate(page_numbers):
            regions = [{"region": "full", "crop_box": [0.0, 0.0, 1.0, 1.0], "rotation": 0}]
            try:
                preview = await asyncio.to_thread(self._render_pdf_page_to_png, pdf_path, page_num, 96)
                regions = plan_pdf_regions(pdf_path, page_num, preview)
                # Gemini table reads need their own time after the Typhoon text
                # request; do not consume the entire page budget before rescue.
                async with asyncio.timeout((self.page_timeout_seconds + 180) * len(regions)):
                    png_bytes = await asyncio.to_thread(self._render_pdf_page_to_png, pdf_path, page_num, render_dpi)
                    for region in regions:
                        image_bytes = (
                            png_bytes if region["region"] == "full" and region["rotation"] == 0
                            else await asyncio.to_thread(crop_and_rotate_png, png_bytes, region)
                        )
                        visual_hint = False
                        if use_gemini_tables:
                            from backend.services.gemini_tables import image_has_table_hint
                            visual_hint = await asyncio.to_thread(image_has_table_hint, image_bytes)
                        typhoon_error = None
                        try:
                            text_deadline = min(self.page_timeout_seconds, 90.0) if visual_hint else self.page_timeout_seconds
                            async with asyncio.timeout(text_deadline):
                                markdown = await self._ocr_png_bytes_async(image_bytes)
                        except Exception as exc:
                            if not (use_gemini_tables and visual_hint):
                                if isinstance(exc, TimeoutError):
                                    raise TimeoutError(
                                        f"Typhoon OCR PDF page {page_num} exceeded {text_deadline:g} seconds"
                                    ) from exc
                                raise RuntimeError(
                                    f"PDF page {page_num} region {region['region']} Typhoon OCR failed: {exc}"
                                ) from exc
                            typhoon_error = f"{type(exc).__name__}: {exc}"
                            markdown = ""
                            logger.warning("Typhoon text failed on table page %d %s: %s", page_num, region['region'], typhoon_error)
                        provider_markdown = markdown
                        if use_gemini_tables:
                            typhoon_tables, text_only = self._extract_structured_tables(markdown)
                            if typhoon_tables or visual_hint:
                                from backend.services.gemini_tables import extract_tables_from_png
                                tables, usage = await extract_tables_from_png(
                                    image_bytes, page=page_num, region=region,
                                )
                                if typhoon_error and not tables:
                                    raise RuntimeError(
                                        f"Typhoon text failed and Gemini found no table on PDF page {page_num}"
                                    )
                                if tables:
                                    markdown = text_only
                                    gemini_tables.extend(tables)
                                elif typhoon_tables:
                                    na_text = _unconfirmed_na_text(typhoon_tables)
                                    markdown = text_only + ('\n\n' + na_text if na_text else '')
                                    table_warnings.append({
                                        "page": page_num, "region": region["region"],
                                        "warning": "Typhoon detected a table but Gemini returned no confirmed cells",
                                    })
                                gemini_usage.append({"page": page_num, "region": region["region"], **usage})
                        if typhoon_error:
                            typhoon_errors.append({"page": page_num, "region": region["region"], "error": typhoon_error})
                        outputs.append({"page": page_num, "markdown": markdown,
                                        "provider_markdown": provider_markdown, **region})
            except TimeoutError as exc:
                raise TimeoutError(f"PDF page {page_num} OCR exceeded its deadline") from exc
            if index < len(page_numbers) - 1 and self.sleep_seconds > 0:
                await asyncio.sleep(self.sleep_seconds)
        result = self._parse_markdown_pages(outputs)
        if use_gemini_tables:
            result["tables"] = gemini_tables
            result["raw_tables"] = [dict(table) for table in gemini_tables]
            result["gemini_table_usage"] = gemini_usage
            result["typhoon_text_errors"] = typhoon_errors
            result["table_extraction_warnings"] = table_warnings
            for page in result["pages"]:
                page["tables"] = sum(
                    table["page"] == page["page"] and table.get("region") == page.get("region")
                    for table in gemini_tables
                )
        return result

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

    def _ocr_pdf_page(self, pdf_path: str, page_num: int, render_dpi: Optional[int] = None) -> str:
        png_bytes = self._render_pdf_page_to_png(pdf_path, page_num, render_dpi)
        return self._ocr_png_bytes(png_bytes)

    def _ocr_png_bytes(self, png_bytes: bytes) -> str:
        last_error: Optional[str] = None
        for attempt in range(1, 4):
            try:
                return self._request_markdown(png_bytes)
            except Exception as exc:
                if any(marker in str(exc) for marker in (
                    "echoed the instruction prompt", "degenerate repeated slash sequence",
                )):
                    raise
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Typhoon OCR failed on attempt %d/3: %s",
                    attempt,
                    last_error,
                )
                if attempt < 3:
                    time.sleep(10 + (attempt - 1) * 10)
        raise RuntimeError(last_error or "Typhoon OCR request failed")

    async def _ocr_png_bytes_async(self, png_bytes: bytes) -> str:
        """Cancelable OCR path used by uploads, bounded by a page deadline."""
        last_error: Optional[str] = None
        for attempt in range(1, 4):
            try:
                return await self._request_markdown_async(png_bytes)
            except Exception as exc:
                if any(marker in str(exc) for marker in (
                    "echoed the instruction prompt", "degenerate repeated slash sequence",
                )):
                    raise
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Typhoon OCR failed on attempt %d/3: %s", attempt, last_error)
                if attempt < 3:
                    await asyncio.sleep(10 + (attempt - 1) * 10)
        raise RuntimeError(last_error or "Typhoon OCR request failed")

    async def _request_markdown_async(self, png_bytes: bytes) -> str:
        payload = self._build_payload(png_bytes)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            response = await client.post("/chat/completions", json=payload)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1000]
            raise RuntimeError(f"Typhoon OCR HTTP {exc.response.status_code}: {body}") from exc
        return self._validate_markdown(self._extract_message_content(response.json()))

    def _validate_markdown(self, markdown: str) -> str:
        result = (markdown or "").strip()
        if result.startswith("Extract all text from the image.") and "Formatting Rules:" in result[:1200]:
            raise RuntimeError("Typhoon OCR echoed the instruction prompt instead of transcribing the page")
        # A real sparse matrix may contain many marks, but hundreds of slash
        # tokens with no cell boundaries are the observed p46 generation loop.
        # Never store that completion as document text or repeat the same call.
        if re.search(r"(?:\s*/){200,}", result):
            raise RuntimeError("Typhoon OCR produced a degenerate repeated slash sequence")
        return result

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
        return self._validate_markdown(content)

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

    def _render_pdf_page_to_png(self, pdf_path: str, page_num: int, render_dpi: Optional[int] = None) -> bytes:
        dpi = max(int(render_dpi or self.render_dpi), 72)
        try:
            import pypdfium2 as pdfium

            document = pdfium.PdfDocument(pdf_path)
            page = document[page_num - 1]
            bitmap = None
            try:
                bitmap = page.render(
                    scale=dpi / 72.0,
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
                matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
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
                for key in ("region", "crop_box", "rotation"):
                    if key in output:
                        table[key] = output[key]
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
                    **{key: table[key] for key in ("region", "crop_box", "rotation") if key in table},
                }
                for table in page_tables
            )
            pages.append(
                {
                    "page": page_num,
                    "markdown": markdown,
                    "text_blocks": len(page_blocks),
                    "tables": len(page_tables),
                    **{key: output[key] for key in ("region", "crop_box", "rotation", "provider_markdown") if key in output},
                }
            )

        return {
            "text_blocks": text_blocks,
            "tables": tables,
            "raw_tables": raw_tables,
            "pages": pages,
            "raw_pages": [
                {"page": page["page"], "markdown": page.get("markdown", ""),
                 **{key: page[key] for key in ("region", "crop_box", "rotation", "provider_markdown") if key in page}}
                for page in pages
            ],
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
            rows_html = re.findall(r"<tr\b[^>]*>(.*?)</tr\s*>", table_html, flags=re.IGNORECASE | re.DOTALL)
            parsed_rows: List[List[str]] = []

            for row_html in rows_html:
                # OCR often omits </th> in multi-row headers. Split at the next
                # opening cell tag rather than requiring a matching closing tag.
                cell_tags = list(re.finditer(r"<t[hd]\b[^>]*>", row_html, flags=re.IGNORECASE))
                cleaned_cells = []
                for index, tag in enumerate(cell_tags):
                    end = cell_tags[index + 1].start() if index + 1 < len(cell_tags) else len(row_html)
                    cell_html = re.sub(r"</?t[hd]\b[^>]*>", "", row_html[tag.end():end], flags=re.IGNORECASE)
                    cleaned_cells.append(self._clean_layout_markup(cell_html))
                if any(cell.strip() for cell in cleaned_cells):
                    parsed_rows.append(cleaned_cells)

            if not parsed_rows:
                return ""

            headers = parsed_rows[0]
            data_rows = parsed_rows[1:]
            width = max((len(row) for row in data_rows), default=len(headers))
            if len(data_rows) > 1 and width > len(headers):
                subheaders = data_rows[0]
                if len(subheaders) == width - 1:
                    headers = [headers[0] or "รายการ", *subheaders]
                    data_rows = data_rows[1:]
                elif self._is_financial_comparison_header(headers, subheaders, width):
                    years_in_header = re.findall(r"(?<!\d)(?:25|20)\d{2}(?!\d)", " ".join(headers))
                    years_in_prefix = re.findall(
                        r"(?<!\d)(?:25|20)\d{2}(?!\d)",
                        self._clean_layout_markup(prefix[-500:]),
                    )
                    printed_year = int(years_in_header[0])
                    current_year = printed_year + 1 if str(printed_year + 1) in years_in_prefix else printed_year
                    headers = [
                        headers[0] or "รายการ", str(current_year), str(current_year - 1),
                        "การเปลี่ยนแปลง (จำนวน)", "การเปลี่ยนแปลง (%)",
                    ]
                    data_rows = data_rows[1:]
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

    def _is_financial_comparison_header(self, headers: List[str], subheaders: List[str], width: int) -> bool:
        return (
            width == 5
            and len(headers) == 3
            and len(subheaders) == 3
            and len(re.findall(r"(?<!\d)(?:25|20)\d{2}(?!\d)", " ".join(headers))) == 1
            and any("เปลี่ยนแปลง" in cell for cell in headers)
            and any("ร้อยละ" in cell or "%" in cell for cell in subheaders)
        )

    def _infer_table_title_from_prefix(self, prefix: str) -> str:
        lines = [self._clean_layout_markup(line) for line in prefix.splitlines()]
        lines = [line.strip() for line in lines if line and line.strip()]

        ignored_patterns = (
            r"^\(?\s*หน่วย\s*[:：]",
            r"^ณ\s+วันที่",
            r"^แบบ\s*56-1",
            r"^รายงานประจำปี",
            r"^<page_number>",
        )

        for line in reversed(lines):
            if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in ignored_patterns):
                continue
            if len(line) < 4:
                continue
            if len(line) > 160:
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


if settings.OFFLINE_MODE:
    from backend.services.local_ocr import ocr_service
else:
    ocr_service = TyphoonOCRService()
