"""Cheap PDF-page layout hints. Embedded text supplies direction, never values."""

from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image


def _rotation_from_pdf_lines(page) -> int:
    """Return a PIL clockwise-equivalent correction from line geometry alone."""
    directions = {"right": 0, "up": 0, "left": 0, "down": 0}
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            x, y = line.get("dir", (1, 0))
            if abs(x) >= abs(y):
                directions["right" if x >= 0 else "left"] += 1
            else:
                directions["down" if y >= 0 else "up"] += 1
    total = sum(directions.values())
    dominant = max(directions, key=directions.get)
    if total < 10 or directions[dominant] / total < 0.65:
        return 0
    return {"right": 0, "up": 270, "left": 180, "down": 90}[dominant]


def _two_up_seam(png_bytes: bytes) -> float | None:
    """Find a broad, light vertical gutter on a landscape page."""
    with Image.open(BytesIO(png_bytes)) as source:
        gray = np.asarray(source.convert("L"))
    height, width = gray.shape
    if width / max(height, 1) < 1.45 or width < 300:
        return None
    ink = (gray[int(height * 0.10):int(height * 0.90)] < 185).mean(axis=0)
    window = max(7, int(width * 0.018))
    smoothed = np.convolve(ink, np.ones(window) / window, mode="same")
    lo, hi = int(width * 0.40), int(width * 0.68)
    quiet = smoothed[lo:hi] < 0.012
    edges = np.diff(np.concatenate(([False], quiet, [False])).astype(int))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    gaps = [(start, end) for start, end in zip(starts, ends) if end - start >= width * 0.035]
    if not gaps:
        return None
    start, end = max(gaps, key=lambda gap: gap[1] - gap[0])
    seam = lo + (start + end) // 2
    left = ink[int(width * 0.20):int(width * 0.40)].mean()
    right = ink[int(width * 0.72):int(width * 0.92)].mean()
    if min(left, right) < 0.018:
        return None
    return float(seam / width)


def _colored_left_sidebar(png_bytes: bytes) -> bool:
    """The bank report has a green contents strip beside the first real page."""
    with Image.open(BytesIO(png_bytes)) as source:
        rgb = np.asarray(source.convert("RGB"), dtype=np.int16)
    width = rgb.shape[1]
    strip = rgb[:, :int(width * 0.17)]
    green = (strip[:, :, 1] > strip[:, :, 0] + 6) & (strip[:, :, 1] > strip[:, :, 2] + 2)
    return float(green.mean()) > 0.45


def _left_crop_start(preview_png: bytes) -> float:
    """Trim the bank contents strip on any two-up page, rotated or upright."""
    return 0.18 if _colored_left_sidebar(preview_png) else 0.0


def plan_pdf_regions(pdf_path: str, page_number: int, preview_png: bytes) -> list[dict]:
    """Return normalized crop boxes and rotations; fail open to one full page."""
    full = [{"region": "full", "crop_box": [0.0, 0.0, 1.0, 1.0], "rotation": 0}]
    try:
        import pymupdf

        with pymupdf.open(pdf_path) as document:
            page = document[page_number - 1]
            rotation = _rotation_from_pdf_lines(page) if page.rect.width / max(page.rect.height, 1) >= 1.4 else 0
        seam = _two_up_seam(preview_png)
        if seam is None:
            full[0]["rotation"] = rotation
            return full
        left_edge = _left_crop_start(preview_png)
        return [
            {"region": "left", "crop_box": [left_edge, 0.0, seam, 1.0], "rotation": rotation},
            {"region": "right", "crop_box": [seam, 0.0, 1.0, 1.0], "rotation": rotation},
        ]
    except Exception:
        return full


def crop_and_rotate_png(png_bytes: bytes, region: dict) -> bytes:
    with Image.open(BytesIO(png_bytes)) as source:
        image = source.convert("RGB")
        left, top, right, bottom = region["crop_box"]
        box = (
            int(left * image.width), int(top * image.height),
            int(right * image.width), int(bottom * image.height),
        )
        cropped = image.crop(box)
        rotated = cropped.rotate(region["rotation"], expand=True)
        with BytesIO() as output:
            rotated.save(output, format="PNG")
            return output.getvalue()
