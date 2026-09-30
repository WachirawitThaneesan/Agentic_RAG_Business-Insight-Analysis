"""Save the exact PNG(s) this project would send to Typhoon for one PDF page.

This is a local rendering audit only: it makes no Typhoon API calls.

Example:
    python scripts/audit_ocr_render.py TestFile/report.pdf 24 --dpi 300
"""

from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.ocr import ocr_service  # noqa: E402
from backend.services.pdf_layout import crop_and_rotate_png, plan_pdf_regions  # noqa: E402


def audit(pdf: Path, page: int, dpi: int, output_dir: Path) -> list[dict]:
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    if page < 1 or page > ocr_service.get_pdf_page_count(str(pdf)):
        raise ValueError(f"Page {page} is outside the PDF")
    if dpi < 72:
        raise ValueError("DPI must be at least 72")

    output_dir.mkdir(parents=True, exist_ok=True)
    preview = ocr_service._render_pdf_page_to_png(str(pdf), page, 96)
    regions = plan_pdf_regions(str(pdf), page, preview)
    full_png = ocr_service._render_pdf_page_to_png(str(pdf), page, dpi)
    prefix = f"{pdf.stem}_p{page}_{dpi}dpi"
    report = []

    for region in regions:
        image_png = (
            full_png if region["region"] == "full" and region["rotation"] == 0
            else crop_and_rotate_png(full_png, region)
        )
        target = output_dir / f"{prefix}_{region['region']}.png"
        target.write_bytes(image_png)
        with Image.open(BytesIO(image_png)) as image:
            width, height = image.size
        report.append({
            "pdf": str(pdf), "page": page, "dpi": dpi,
            "region": region["region"], "crop_box": region["crop_box"],
            "rotation": region["rotation"], "width": width, "height": height,
            "png_bytes": len(image_png), "path": str(target),
        })
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("page", type=int, help="1-based physical PDF page")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "tmp" / "pdfs" / "ocr_input_audit")
    args = parser.parse_args()
    print(json.dumps(audit(args.pdf, args.page, args.dpi, args.output_dir), indent=2, ensure_ascii=False))
