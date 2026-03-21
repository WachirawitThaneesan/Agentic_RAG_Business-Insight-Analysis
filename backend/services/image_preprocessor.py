"""Image pre-processing pipeline for table OCR.

Applies deskew, contrast enhancement, binarization, denoising, and upscaling
to maximise OCR accuracy on scanned or photographed Thai documents.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from PIL import Image


@dataclass
class PreprocessConfig:
    """Tuning knobs for the image pre-processing pipeline."""

    target_dpi: int = 300
    """Minimum effective resolution.  Images below this are upscaled."""

    assume_dpi: int = 150
    """Assumed DPI when the image metadata does not include resolution info."""

    clahe_clip_limit: float = 2.0
    """CLAHE clip limit – higher = more contrast, but may amplify noise."""

    clahe_tile_grid: tuple[int, int] = (8, 8)

    adaptive_block_size: int = 31
    """Block size for adaptive Gaussian thresholding (must be odd)."""

    adaptive_c: int = 10
    """Constant subtracted from the mean in adaptive thresholding."""

    denoise_strength: int = 10
    """h parameter for cv2.fastNlMeansDenoising – higher = stronger."""

    max_skew_degrees: float = 15.0
    """Reject detected skew angles larger than this (likely false positive)."""

    enable_deskew: bool = True
    enable_contrast: bool = True
    enable_denoise: bool = True
    enable_binarize: bool = False  # off by default – Typhoon handles colour
    enable_upscale: bool = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preprocess_for_ocr(
    image: Image.Image,
    config: Optional[PreprocessConfig] = None,
) -> Image.Image:
    """Run the full pre-processing pipeline and return a cleaned PIL Image.

    Steps (each gated by the corresponding ``config.enable_*`` flag):
    1. Convert to grayscale
    2. Upscale to ``target_dpi``
    3. Deskew (straighten rotated scans)
    4. CLAHE contrast enhancement
    5. Non-local-means denoising
    6. Adaptive binarization (optional – disabled by default)
    """
    config = config or PreprocessConfig()

    # Work in OpenCV (numpy) space
    arr = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    if config.enable_upscale:
        gray = _upscale(gray, image, config)

    if config.enable_deskew:
        gray = _deskew(gray, config)

    if config.enable_contrast:
        gray = _enhance_contrast(gray, config)

    if config.enable_denoise:
        gray = _denoise(gray, config)

    if config.enable_binarize:
        gray = _binarize(gray, config)

    return Image.fromarray(gray)


def preprocess_for_ocr_colour(
    image: Image.Image,
    config: Optional[PreprocessConfig] = None,
) -> Image.Image:
    """Like :func:`preprocess_for_ocr` but keeps the image in colour.

    Useful when the downstream OCR model benefits from colour cues
    (e.g. coloured cells / highlighted rows).  Only upscale + deskew are
    applied; contrast/denoise/binarize run on a luminance proxy and are
    blended back.
    """
    config = config or PreprocessConfig()
    arr = np.array(image.convert("RGB"))

    if config.enable_upscale:
        arr = _upscale_colour(arr, image, config)

    if config.enable_deskew:
        arr = _deskew_colour(arr, config)

    return Image.fromarray(arr)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _guess_dpi(image: Image.Image, config: PreprocessConfig) -> int:
    """Try to read DPI from image metadata; fall back to ``assume_dpi``."""
    info = image.info or {}
    dpi = info.get("dpi")
    if dpi and isinstance(dpi, (tuple, list)) and len(dpi) >= 2:
        avg = (float(dpi[0]) + float(dpi[1])) / 2
        if 50 < avg < 2400:
            return int(avg)
    return config.assume_dpi


def _upscale(gray: np.ndarray, image: Image.Image, config: PreprocessConfig) -> np.ndarray:
    current_dpi = _guess_dpi(image, config)
    if current_dpi >= config.target_dpi:
        return gray
    scale = config.target_dpi / current_dpi
    new_w = int(gray.shape[1] * scale)
    new_h = int(gray.shape[0] * scale)
    return cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def _upscale_colour(arr: np.ndarray, image: Image.Image, config: PreprocessConfig) -> np.ndarray:
    current_dpi = _guess_dpi(image, config)
    if current_dpi >= config.target_dpi:
        return arr
    scale = config.target_dpi / current_dpi
    new_w = int(arr.shape[1] * scale)
    new_h = int(arr.shape[0] * scale)
    return cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def _detect_skew_angle(gray: np.ndarray, config: PreprocessConfig) -> float:
    """Detect document skew via Hough line transform on edge image."""
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=100,
        minLineLength=gray.shape[1] // 4,
        maxLineGap=20,
    )
    if lines is None or len(lines) == 0:
        return 0.0

    angles: list[float] = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 1:
            continue
        angle = math.degrees(math.atan2(dy, dx))
        # Only consider near-horizontal lines (table gridlines)
        if abs(angle) < config.max_skew_degrees:
            angles.append(angle)

    if not angles:
        return 0.0

    median_angle = float(np.median(angles))
    if abs(median_angle) > config.max_skew_degrees:
        return 0.0
    return median_angle


def _deskew(gray: np.ndarray, config: PreprocessConfig) -> np.ndarray:
    angle = _detect_skew_angle(gray, config)
    if abs(angle) < 0.3:  # negligible
        return gray
    h, w = gray.shape[:2]
    centre = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(centre, angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _deskew_colour(arr: np.ndarray, config: PreprocessConfig) -> np.ndarray:
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    angle = _detect_skew_angle(gray, config)
    if abs(angle) < 0.3:
        return arr
    h, w = arr.shape[:2]
    centre = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(centre, angle, 1.0)
    return cv2.warpAffine(
        arr, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _enhance_contrast(gray: np.ndarray, config: PreprocessConfig) -> np.ndarray:
    clahe = cv2.createCLAHE(
        clipLimit=config.clahe_clip_limit,
        tileGridSize=config.clahe_tile_grid,
    )
    return clahe.apply(gray)


def _denoise(gray: np.ndarray, config: PreprocessConfig) -> np.ndarray:
    return cv2.fastNlMeansDenoising(gray, None, config.denoise_strength, 7, 21)


def _binarize(gray: np.ndarray, config: PreprocessConfig) -> np.ndarray:
    return cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        config.adaptive_block_size,
        config.adaptive_c,
    )
