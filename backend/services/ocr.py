"""Typhoon OCR service using the official typhoon_ocr SDK."""

import asyncio
import io
import os
import re
import tempfile
from typing import Any, Dict, List, Optional

from PIL import Image
from pypdf import PdfReader, PdfWriter
from typhoon_ocr import ocr_document

from backend.config import get_settings

settings = get_settings()


class TyphoonOCRService:
    """Calls Typhoon OCR via the official SDK and normalizes the result."""

    def __init__(self):
        self.api_key = settings.TYPHOON_OCR_API_KEY or settings.TYPHOON_API_KEY
        self.model = settings.TYPHOON_OCR_MODEL
        self.figure_language = "Thai"
        self.base_url = self._derive_base_url(settings.TYPHOON_OCR_ENDPOINT)

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

        variants = self._build_image_variants(image_bytes, filename, mime_type)
        try:
            best_result: Optional[Dict[str, Any]] = None
            best_score = float("-inf")

            for variant in variants:
                markdown = await asyncio.to_thread(self._ocr_single_page, variant["path"], 1)
                parsed = self._parse_markdown_pages([{"page": 1, "markdown": markdown}])
                score = self._score_parsed_result(parsed)
                if score > best_score:
                    best_score = score
                    best_result = parsed

            return best_result or {"text_blocks": [], "tables": [], "pages": [], "errors": []}
        finally:
            for variant in variants:
                self._safe_unlink(variant["path"])

    async def extract_from_pdf(
        self,
        pdf_bytes: bytes,
        filename: str = "document.pdf",
        pages: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Extract text and tables from all requested PDF pages."""
        if not self.api_key:
            raise RuntimeError("Typhoon OCR API key is not configured")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        try:
            page_numbers = pages or self._all_pdf_pages(tmp_path)
            outputs = []
            for page_num in page_numbers:
                page_output = await self._extract_best_pdf_page(tmp_path, page_num)
                outputs.append(page_output)
            return self._parse_markdown_pages(outputs)
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
        outputs = []
        for page_num in page_numbers:
            page_output = await self._extract_best_pdf_page(pdf_path, page_num)
            outputs.append(page_output)
        return self._parse_markdown_pages(outputs)

    def get_pdf_page_count(self, pdf_path: str) -> int:
        return len(PdfReader(pdf_path).pages)

    def _ocr_single_page(self, path: str, page_num: int) -> str:
        kwargs = {
            "pdf_or_image_path": path,
            "page_num": page_num,
            "model": self.model,
            "api_key": self.api_key,
            "figure_language": self.figure_language,
            "base_url": self.base_url,
        }
        return ocr_document(**kwargs)

    def _all_pdf_pages(self, path: str) -> List[int]:
        reader = PdfReader(path)
        return list(range(1, len(reader.pages) + 1))

    async def _extract_best_pdf_page(self, pdf_path: str, page_num: int) -> Dict[str, Any]:
        original_markdown = await asyncio.to_thread(self._ocr_single_page, pdf_path, page_num)
        original_parsed = self._parse_markdown_pages([{"page": page_num, "markdown": original_markdown}])
        best_markdown = original_markdown
        best_score = self._score_parsed_result(original_parsed)

        if not self._should_try_pdf_rotations(original_parsed, best_score):
            return {"page": page_num, "markdown": best_markdown}

        variants = self._build_pdf_page_variants(pdf_path, page_num)
        try:
            for variant in variants:
                markdown = await asyncio.to_thread(self._ocr_single_page, variant["path"], 1)
                parsed = self._parse_markdown_pages([{"page": page_num, "markdown": markdown}])
                score = self._score_parsed_result(parsed)
                if score > best_score:
                    best_score = score
                    best_markdown = markdown
        finally:
            for variant in variants:
                self._safe_unlink(variant["path"])

        return {"page": page_num, "markdown": best_markdown}

    def _build_pdf_page_variants(self, pdf_path: str, page_num: int) -> List[Dict[str, Any]]:
        reader = PdfReader(pdf_path)
        page = reader.pages[page_num - 1]
        width = float(page.mediabox.width or 0)
        height = float(page.mediabox.height or 0)
        rotations = [90, 270]
        if self._looks_like_sideways_page(width, height):
            rotations.append(180)

        variants: List[Dict[str, Any]] = []
        for rotation in rotations:
            variant_reader = PdfReader(pdf_path)
            variant_page = variant_reader.pages[page_num - 1]
            writer = PdfWriter()
            writer.add_page(variant_page)
            writer.pages[0].rotate(rotation)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                writer.write(tmp)
                variants.append({"path": tmp.name, "rotation": rotation})

        return variants

    def _build_image_variants(
        self,
        image_bytes: bytes,
        filename: str,
        mime_type: str,
    ) -> List[Dict[str, Any]]:
        suffix = self._suffix_from_filename(filename, mime_type)
        variants: List[Dict[str, Any]] = []

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(image_bytes)
            variants.append({"path": tmp.name, "rotation": 0})

        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                img.load()
                rotations = [90, 270]
                if self._looks_like_sideways_page(img.width, img.height):
                    rotations.append(180)

                for rotation in rotations:
                    rotated = img.rotate(rotation, expand=True)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        save_kwargs = {}
                        image_to_save = rotated
                        if rotated.mode not in ("RGB", "L") and suffix in (".jpg", ".jpeg"):
                            image_to_save = rotated.convert("RGB")
                        if suffix in (".jpg", ".jpeg"):
                            save_kwargs["quality"] = 95
                        image_to_save.save(tmp.name, **save_kwargs)
                        variants.append({"path": tmp.name, "rotation": rotation})
        except Exception:
            return variants

        return variants

    def _looks_like_sideways_page(self, width: int, height: int) -> bool:
        longer = max(width, height)
        shorter = min(width, height) or 1
        aspect_ratio = longer / shorter
        return aspect_ratio >= 1.2

    def _should_try_pdf_rotations(self, parsed: Dict[str, Any], score: float) -> bool:
        tables = parsed.get("tables", []) or []
        text_blocks = parsed.get("text_blocks", []) or []
        text_chars = sum(len(block) for block in text_blocks[:8])
        year_hits = sum(
            1
            for table in tables
            for header in table.get("headers", [])
            if re.fullmatch(r"(?:25|20)\d{2}", str(header or "").strip())
        )
        return (
            score < 650
            or not tables
            or year_hits == 0
            or text_chars < 300
            or self._has_suspicious_structure(parsed)
        )

    def _score_parsed_result(self, parsed: Dict[str, Any]) -> float:
        tables = parsed.get("tables", []) or []
        text_blocks = parsed.get("text_blocks", []) or []

        table_count = len(tables)
        row_count = sum(len(table.get("rows", [])) for table in tables)
        col_count = sum(len(table.get("headers", [])) for table in tables)
        year_hits = sum(
            1
            for table in tables
            for header in table.get("headers", [])
            if re.fullmatch(r"(?:25|20)\d{2}", str(header or "").strip())
        )
        unit_hits = sum(
            1
            for table in tables
            for row in table.get("rows", [])
            for cell in row
            if re.fullmatch(r"\([^)]{1,15}\)", str(cell or "").strip())
        )
        numeric_hits = sum(len(re.findall(r"\d[\d,\.]*", block)) for block in text_blocks[:8])
        text_chars = sum(len(block) for block in text_blocks[:8])

        score = (
            table_count * 400
            + row_count * 20
            + col_count * 10
            + year_hits * 80
            + unit_hits * 20
            + numeric_hits * 3
            + min(text_chars, 4000) / 20
        )

        for table in tables:
            headers = [str(header or "").strip() for header in table.get("headers", [])]
            rows = table.get("rows", []) or []
            generic_headers = sum(1 for header in headers if header.lower().startswith("column_"))
            score -= generic_headers * 45

            if year_hits >= 2:
                score += 120

            if rows:
                first_row = [str(cell or "").strip() for cell in rows[0]]
                score -= self._header_overlap_penalty(headers, first_row)

            for row in rows[:12]:
                score += self._score_table_row(row)

        if self._has_suspicious_structure(parsed):
            score -= 250

        return score

    def _score_table_row(self, row: List[Any]) -> float:
        cells = [str(cell or "").strip() for cell in row]
        nonempty = [cell for cell in cells if cell]
        if not nonempty:
            return -10

        numeric_count = sum(1 for cell in nonempty if self._is_numeric_like(cell))
        placeholder_count = sum(1 for cell in nonempty if self._is_placeholder(cell))
        text_count = sum(
            1
            for cell in nonempty
            if not self._is_numeric_like(cell)
            and not self._is_placeholder(cell)
            and not self._is_unit_token(cell)
        )
        long_text_count = sum(
            1
            for cell in nonempty
            if len(cell) >= 14
            and not self._is_numeric_like(cell)
            and not self._is_placeholder(cell)
        )

        score = 0.0
        if numeric_count >= 2:
            score += 18
        if numeric_count >= 4:
            score += 12
        if placeholder_count >= 2 and numeric_count >= 1:
            score += 4
        if long_text_count >= 3 and numeric_count == 0:
            score -= 70
        if text_count > max(3, numeric_count + 2):
            score -= 35
        return score

    def _header_overlap_penalty(self, headers: List[str], row: List[str]) -> float:
        header_tokens = {self._normalize_cell_text(header) for header in headers if self._normalize_cell_text(header)}
        row_tokens = [self._normalize_cell_text(cell) for cell in row if self._normalize_cell_text(cell)]
        overlap = sum(1 for token in row_tokens if token in header_tokens)
        if overlap >= 3:
            return 160
        if overlap == 2:
            return 90
        return 0

    def _has_suspicious_structure(self, parsed: Dict[str, Any]) -> bool:
        for table in parsed.get("tables", []) or []:
            headers = [str(header or "").strip() for header in table.get("headers", [])]
            rows = table.get("rows", []) or []
            generic_headers = sum(1 for header in headers if header.lower().startswith("column_"))
            if generic_headers >= max(3, len(headers) // 4):
                return True
            if rows:
                first_row = [str(cell or "").strip() for cell in rows[0]]
                if self._header_overlap_penalty(headers, first_row) >= 90:
                    return True
        return False

    def _normalize_cell_text(self, text: str) -> str:
        value = str(text or "").strip().lower()
        value = re.sub(r"\s+", "", value)
        value = re.sub(r"[^\w\u0E00-\u0E7F]", "", value)
        return value

    def _is_placeholder(self, text: str) -> bool:
        return str(text or "").strip() in {"-", "–", "—", ".", "..", "..."}

    def _is_unit_token(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        if re.fullmatch(r"\([^)]{1,15}\)", value):
            return True
        return value in {"%", "บาท", "ล้านบาท"}

    def _is_numeric_like(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value or self._is_unit_token(value) or self._is_placeholder(value):
            return False
        return bool(re.fullmatch(r"[+-]?\d[\d,\.]*", value))

    def _parse_markdown_pages(self, page_outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        text_blocks: List[str] = []
        tables: List[Dict[str, Any]] = []
        pages: List[Dict[str, Any]] = []

        for output in page_outputs:
            page_num = output["page"]
            markdown = output.get("markdown", "") or ""
            page_tables, text_only = self._extract_structured_tables(markdown)
            cleaned = self._clean_layout_markup(text_only)
            page_blocks = self._split_text_blocks(cleaned)

            text_blocks.extend(page_blocks)
            tables.extend(page_tables)
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

        def repl(match: re.Match) -> str:
            table_html = match.group(0)
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
                tables.append({"headers": headers, "rows": data_rows})
            return ""

        without_tables = re.sub(
            r"<table[^>]*>.*?</table>",
            repl,
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return tables, without_tables

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

    def _suffix_from_filename(self, filename: str, mime_type: str) -> str:
        ext = os.path.splitext(filename or "")[1].lower()
        if ext:
            return ext
        if mime_type == "image/jpeg":
            return ".jpg"
        return ".png"

    def _safe_unlink(self, path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass


# Singleton
ocr_service = TyphoonOCRService()
