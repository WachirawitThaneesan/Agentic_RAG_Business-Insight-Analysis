#!/usr/bin/env python3
"""PDF -> PNG -> Typhoon OCR.

This script does exactly one workflow:
1. Render one PDF page to a PNG file.
2. Send that PNG file directly to Typhoon OCR.
3. Save per-page markdown output, error logs, and a JSON summary.

It intentionally does not do any image preprocessing.

Recommended setup in this repo:

    .\\.venv\\Scripts\\Activate.ps1
    python .\\typhoon_pdf_png_direct.py

If you do not pass an input PDF, the script defaults to:
    ..\\annual-report-2024-th.pdf
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import pypdfium2 as pdfium
from dotenv import load_dotenv
from pypdf import PdfReader


DEFAULT_DPI = 300
DEFAULT_SLEEP_SECONDS = 0.7
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_MODEL = "typhoon-ocr"
DEFAULT_BASE_URL = "https://api.opentyphoon.ai/v1"
DEFAULT_INPUT_PDF = (Path(__file__).resolve().parent.parent / "annual-report-2024-th.pdf").resolve()
MAX_RETRIES = 3


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


@dataclass(frozen=True)
class OutputPaths:
    image_path: Path
    markdown_path: Path
    error_path: Path


@dataclass
class PageResult:
    page_number: int
    status: str
    attempts: int
    image_path: Optional[str]
    markdown_path: Optional[str]
    error_path: Optional[str]
    text_length: int
    duration_seconds: float
    error: Optional[str]
    skipped: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render PDF pages to PNG and send each PNG directly to Typhoon OCR.",
    )
    parser.add_argument(
        "input_pdf",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT_PDF,
        help=f"Input PDF path. Default: {DEFAULT_INPUT_PDF}",
    )
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"Rendering DPI. Default: {DEFAULT_DPI}.")
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help=f"Delay between OCR requests in seconds. Default: {DEFAULT_SLEEP_SECONDS}.",
    )
    parser.add_argument("--start-page", type=int, default=1, help="1-based start page. Default: 1.")
    parser.add_argument("--end-page", type=int, default=None, help="1-based end page. Default: last page.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output instead of resume mode.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Base output directory. Default: ./output_annual_report_2024_th for the default PDF, otherwise <pdf-dir>/output",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Typhoon API key. Falls back to TYPHOON_OCR_API_KEY or TYPHOON_API_KEY.",
    )
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"Typhoon model. Default: {DEFAULT_MODEL}.")
    parser.add_argument(
        "--base-url",
        type=str,
        default=DEFAULT_BASE_URL,
        help=f"Typhoon base URL. Default: {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout per page request in seconds. Default: {DEFAULT_TIMEOUT_SECONDS}.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level. Default: INFO.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.input_pdf.exists():
        raise FileNotFoundError(f"Input PDF not found: {args.input_pdf}")
    if args.input_pdf.suffix.lower() != ".pdf":
        raise ValueError(f"Input file must be a PDF: {args.input_pdf}")
    if args.dpi <= 0:
        raise ValueError("--dpi must be greater than 0.")
    if args.sleep < 0:
        raise ValueError("--sleep must be 0 or greater.")
    if args.start_page <= 0:
        raise ValueError("--start-page must be 1 or greater.")
    if args.end_page is not None and args.end_page <= 0:
        raise ValueError("--end-page must be 1 or greater.")
    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than 0.")


def resolve_api_key(cli_api_key: Optional[str]) -> str:
    api_key = cli_api_key or os.environ.get("TYPHOON_OCR_API_KEY") or os.environ.get("TYPHOON_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing API key. Set TYPHOON_OCR_API_KEY or TYPHOON_API_KEY in the environment or .env, or pass --api-key.",
        )
    return api_key


def normalize_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if value.endswith("/ocr"):
        return value[: -len("/ocr")]
    if value.endswith("/chat/completions"):
        return value[: -len("/chat/completions")]
    return value


def default_output_dir(input_pdf: Path) -> Path:
    if input_pdf.resolve() == DEFAULT_INPUT_PDF:
        return (Path.cwd() / "output_annual_report_2024_th").resolve()
    return (input_pdf.parent / "output").resolve()


def prepare_output_dirs(output_dir: Path) -> None:
    for child in ("images", "pages", "errors", "logs"):
        (output_dir / child).mkdir(parents=True, exist_ok=True)


def configure_logging(output_dir: Path, level_name: str) -> Path:
    log_path = output_dir / "logs" / "run.log"
    root = logging.getLogger()
    root.setLevel(getattr(logging, level_name.upper()))
    root.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    return log_path


def get_total_pages(pdf_path: Path) -> int:
    with pdf_path.open("rb") as handle:
        return len(PdfReader(handle).pages)


def resolve_page_range(start_page: int, end_page: Optional[int], total_pages: int) -> tuple[int, int]:
    resolved_end = end_page or total_pages
    if start_page > total_pages:
        raise ValueError(f"--start-page ({start_page}) exceeds total pages ({total_pages}).")
    if resolved_end > total_pages:
        raise ValueError(f"--end-page ({resolved_end}) exceeds total pages ({total_pages}).")
    if start_page > resolved_end:
        raise ValueError("--start-page cannot be greater than --end-page.")
    return start_page, resolved_end


def build_output_paths(output_dir: Path, page_number: int) -> OutputPaths:
    page_stub = f"page_{page_number:03d}"
    return OutputPaths(
        image_path=output_dir / "images" / f"{page_stub}.png",
        markdown_path=output_dir / "pages" / f"{page_stub}.md",
        error_path=output_dir / "errors" / f"{page_stub}.txt",
    )


def remove_existing_artifacts(paths: OutputPaths) -> None:
    for path in (paths.image_path, paths.markdown_path, paths.error_path):
        if path.exists():
            path.unlink()


def should_skip_page(paths: OutputPaths, force: bool) -> bool:
    if force:
        return False
    return paths.image_path.exists() and paths.markdown_path.exists()


def render_page_to_png(document: pdfium.PdfDocument, page_number: int, dpi: int, target_path: Path) -> None:
    page = document[page_number - 1]
    bitmap = None
    try:
        bitmap = page.render(
            scale=dpi / 72.0,
            rev_byteorder=True,
            optimize_mode="print",
        )
        image = bitmap.to_pil().convert("RGB")
        image.save(target_path, format="PNG")
    finally:
        if bitmap is not None:
            bitmap.close()
        page.close()


def png_to_data_url(image_path: Path) -> str:
    image_bytes = image_path.read_bytes()
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_payload(image_path: Path, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT_V15},
                    {"type": "image_url", "image_url": {"url": png_to_data_url(image_path)}},
                ],
            }
        ],
        "max_tokens": 16384,
        "temperature": 0.1,
        "top_p": 0.6,
        "repetition_penalty": 1.1,
    }


def call_typhoon_ocr(client: httpx.Client, image_path: Path, model: str) -> str:
    response = client.post("/chat/completions", json=build_payload(image_path, model))
    response.raise_for_status()
    payload = response.json()
    try:
        return str(payload["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OCR response: {payload}") from exc


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def process_single_page(
    document: pdfium.PdfDocument,
    client: httpx.Client,
    page_number: int,
    dpi: int,
    model: str,
    output_paths: OutputPaths,
    force: bool,
    sleep_seconds: float,
) -> PageResult:
    logger = logging.getLogger(__name__)
    started = time.perf_counter()

    if force:
        remove_existing_artifacts(output_paths)

    if should_skip_page(output_paths, force):
        logger.info("Skipping page %03d because output already exists.", page_number)
        return PageResult(
            page_number=page_number,
            status="skipped",
            attempts=0,
            image_path=str(output_paths.image_path),
            markdown_path=str(output_paths.markdown_path),
            error_path=None,
            text_length=0,
            duration_seconds=round(time.perf_counter() - started, 3),
            error=None,
            skipped=True,
        )

    try:
        render_page_to_png(document, page_number, dpi, output_paths.image_path)
    except Exception as exc:
        error_message = f"Render failed for page {page_number:03d}: {type(exc).__name__}: {exc}"
        logger.exception(error_message)
        write_text_file(output_paths.error_path, error_message + "\n")
        return PageResult(
            page_number=page_number,
            status="failed",
            attempts=0,
            image_path=None,
            markdown_path=None,
            error_path=str(output_paths.error_path),
            text_length=0,
            duration_seconds=round(time.perf_counter() - started, 3),
            error=error_message,
            skipped=False,
        )

    if output_paths.error_path.exists():
        output_paths.error_path.unlink()

    markdown = ""
    last_error: Optional[str] = None
    attempts = 0
    for attempts in range(1, MAX_RETRIES + 1):
        try:
            logger.info("OCR page %03d attempt %d/%d", page_number, attempts, MAX_RETRIES)
            markdown = call_typhoon_ocr(client, output_paths.image_path, model)
            last_error = None
            break
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "OCR failed for page %03d on attempt %d/%d: %s",
                page_number,
                attempts,
                MAX_RETRIES,
                last_error,
            )
            if attempts < MAX_RETRIES:
                time.sleep(sleep_seconds)

    if last_error is not None:
        write_text_file(output_paths.error_path, last_error + "\n")
        return PageResult(
            page_number=page_number,
            status="failed",
            attempts=attempts,
            image_path=str(output_paths.image_path),
            markdown_path=None,
            error_path=str(output_paths.error_path),
            text_length=0,
            duration_seconds=round(time.perf_counter() - started, 3),
            error=last_error,
            skipped=False,
        )

    markdown_text = markdown.rstrip() + "\n" if markdown.strip() else ""
    write_text_file(output_paths.markdown_path, markdown_text)
    return PageResult(
        page_number=page_number,
        status="success",
        attempts=attempts,
        image_path=str(output_paths.image_path),
        markdown_path=str(output_paths.markdown_path),
        error_path=None,
        text_length=len(markdown_text),
        duration_seconds=round(time.perf_counter() - started, 3),
        error=None,
        skipped=False,
    )


def build_summary(
    pdf_path: Path,
    output_dir: Path,
    log_path: Path,
    total_pages: int,
    start_page: int,
    end_page: int,
    dpi: int,
    sleep_seconds: float,
    timeout_seconds: float,
    model: str,
    base_url: str,
    page_results: list[PageResult],
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    return {
        "input_pdf": str(pdf_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "log_file": str(log_path.resolve()),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
        "total_pages_in_pdf": total_pages,
        "requested_page_range": {"start_page": start_page, "end_page": end_page},
        "settings": {
            "dpi": dpi,
            "sleep_seconds": sleep_seconds,
            "timeout_seconds": timeout_seconds,
            "max_retries": MAX_RETRIES,
            "base_url": base_url,
            "model": model,
        },
        "counts": {
            "success": sum(1 for item in page_results if item.status == "success"),
            "failed": sum(1 for item in page_results if item.status == "failed"),
            "skipped": sum(1 for item in page_results if item.status == "skipped"),
        },
        "pages": [asdict(item) for item in page_results],
    }


def main() -> int:
    load_dotenv()
    args = parse_args()
    validate_args(args)

    pdf_path = args.input_pdf.resolve()
    output_dir = (args.output_dir.resolve() if args.output_dir else default_output_dir(pdf_path))
    prepare_output_dirs(output_dir)
    log_path = configure_logging(output_dir, args.log_level)
    logger = logging.getLogger(__name__)

    api_key = resolve_api_key(args.api_key)
    base_url = normalize_base_url(args.base_url)
    total_pages = get_total_pages(pdf_path)
    start_page, end_page = resolve_page_range(args.start_page, args.end_page, total_pages)
    started_at = datetime.now(timezone.utc)
    page_results: list[PageResult] = []

    logger.info("Input PDF: %s", pdf_path)
    logger.info("Output directory: %s", output_dir)
    logger.info("Processing pages %d to %d of %d", start_page, end_page, total_pages)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    document = None
    try:
        document = pdfium.PdfDocument(str(pdf_path))
        with httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(args.timeout),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            for page_number in range(start_page, end_page + 1):
                output_paths = build_output_paths(output_dir, page_number)
                result = process_single_page(
                    document=document,
                    client=client,
                    page_number=page_number,
                    dpi=args.dpi,
                    model=args.model,
                    output_paths=output_paths,
                    force=args.force,
                    sleep_seconds=args.sleep,
                )
                page_results.append(result)
                if page_number < end_page:
                    time.sleep(args.sleep)
    finally:
        if document is not None:
            document.close()
        completed_at = datetime.now(timezone.utc)
        summary = build_summary(
            pdf_path=pdf_path,
            output_dir=output_dir,
            log_path=log_path,
            total_pages=total_pages,
            start_page=start_page,
            end_page=end_page,
            dpi=args.dpi,
            sleep_seconds=args.sleep,
            timeout_seconds=args.timeout,
            model=args.model,
            base_url=base_url,
            page_results=page_results,
            started_at=started_at,
            completed_at=completed_at,
        )
        write_text_file(output_dir / "logs" / "summary.json", json.dumps(summary, indent=2, ensure_ascii=False))

    failed_pages = [item.page_number for item in page_results if item.status == "failed"]
    if failed_pages:
        logger.warning("Completed with failed pages: %s", ", ".join(map(str, failed_pages)))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
