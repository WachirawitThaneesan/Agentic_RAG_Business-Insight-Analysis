"""One bounded Typhoon OCR probe on a crop of a previously audited PNG.

Example:
    python scripts/probe_typhoon_region.py tmp/pdfs/ocr_input_audit/report_p46_300dpi_left.png 835 1250

This is a diagnostic, not the production ingestion path. It makes exactly
one API request (no retry), and writes the response under git-ignored tmp/.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.ocr import TyphoonOCRService  # noqa: E402


SPARSE_PROMPT = """Read the visible table excerpt. Return ONLY a compact JSON array.
For each visible numbered row, use keys row_number, name, bank_position, and marks.
marks is a list of only clearly visible nonempty matrix cells, each with group,
column_number, and symbol. Never output blank cells. Never repeat a symbol to
fill an empty cell. Use null when a column number is not legible. Do not guess.
"""


async def probe(
    image_path: Path, top: int, bottom: int, max_tokens: int, timeout: float,
    output: Path, sparse: bool = False, left: int = 0, right: int | None = None,
) -> dict:
    service = TyphoonOCRService()
    if not service.api_key:
        raise RuntimeError("Typhoon OCR API key is not configured")
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    with Image.open(image_path) as source:
        if not 0 <= top < bottom <= source.height:
            raise ValueError("Crop must be within the image and have positive height")
        right = source.width if right is None else right
        if not 0 <= left < right <= source.width:
            raise ValueError("Horizontal crop must be within the image and have positive width")
        region = source.convert("RGB").crop((left, top, right, bottom))
        width, height = region.size
        with BytesIO() as buffer:
            region.save(buffer, format="PNG")
            png_bytes = buffer.getvalue()

    service.max_tokens = max_tokens
    service.timeout_seconds = timeout
    if sparse:
        original_build_payload = service._build_payload

        def sparse_payload(image_bytes: bytes) -> dict:
            payload = original_build_payload(image_bytes)
            payload["messages"][0]["content"][0]["text"] = SPARSE_PROMPT
            return payload

        service._build_payload = sparse_payload
    started = time.perf_counter()
    result = {
        "source": str(image_path), "crop_pixels": [left, top, right, bottom],
        "region_pixels": [width, height], "png_bytes": len(png_bytes),
        "sha256": hashlib.sha256(png_bytes).hexdigest(), "model": service.model,
        "max_tokens": max_tokens, "timeout_seconds": timeout,
        "prompt_mode": "sparse" if sparse else "project_default",
    }
    try:
        async with asyncio.timeout(timeout + 5):
            markdown = await service._request_markdown_async(png_bytes)
        result.update(status="ok", markdown=markdown, markdown_characters=len(markdown))
    except Exception as exc:
        result.update(status="error", error_type=type(exc).__name__, error=str(exc)[:500])
    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return {key: value for key, value in result.items() if key != "markdown"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("top", type=int, help="First included pixel row")
    parser.add_argument("bottom", type=int, help="First excluded pixel row")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--left", type=int, default=0, help="First included pixel column")
    parser.add_argument("--right", type=int, help="First excluded pixel column; defaults to image width")
    parser.add_argument("--sparse", action="store_true", help="Probe a sparse-matrix-specific prompt")
    parser.add_argument("--output", type=Path, default=ROOT / "tmp" / "pdfs" / "typhoon_region_probe.json")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(probe(
        args.image, args.top, args.bottom, args.max_tokens, args.timeout,
        args.output, args.sparse, args.left, args.right,
    )), indent=2))
