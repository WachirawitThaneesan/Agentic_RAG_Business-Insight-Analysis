"""Table detection and cropping from document images.

Provides two backends:
* **opencv** – lightweight contour-based detection (no ML model)
* **tatr**   – Microsoft Table Transformer (requires ``torch`` + ``transformers``)

The active backend is selected via ``Settings.TABLE_DETECTOR_BACKEND``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class BoundingBox:
    """Axis-aligned bounding box in pixel coordinates (x0, y0 = top-left)."""

    x0: int
    y0: int
    x1: int
    y1: int
    confidence: float = 1.0
    label: str = "table"

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def area(self) -> int:
        return self.width * self.height

    def pad(self, px: int, img_w: int, img_h: int) -> "BoundingBox":
        """Return a new box expanded by *px* pixels, clamped to image bounds."""
        return BoundingBox(
            x0=max(0, self.x0 - px),
            y0=max(0, self.y0 - px),
            x1=min(img_w, self.x1 + px),
            y1=min(img_h, self.y1 + px),
            confidence=self.confidence,
            label=self.label,
        )


@dataclass
class DetectionResult:
    """Container returned by :func:`detect_tables`."""

    bboxes: List[BoundingBox] = field(default_factory=list)
    backend: str = "opencv"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_tables(
    image: Image.Image,
    backend: str = "opencv",
    confidence_threshold: float = 0.7,
    padding_px: int = 10,
) -> DetectionResult:
    """Detect table regions in *image* and return their bounding boxes.

    Parameters
    ----------
    image : PIL.Image
        Full-page document image (RGB or grayscale).
    backend : str
        ``"opencv"`` for contour-based detection, ``"tatr"`` for the
        Table Transformer model.
    confidence_threshold : float
        Minimum confidence to accept a detection (TATR only).
    padding_px : int
        Extra pixels to add around each detected table for safety margin.
    """
    if backend == "tatr":
        bboxes = _detect_tatr(image, confidence_threshold)
    else:
        bboxes = _detect_opencv(image)

    img_w, img_h = image.size
    padded = [bbox.pad(padding_px, img_w, img_h) for bbox in bboxes]
    return DetectionResult(bboxes=padded, backend=backend)


def crop_tables(
    image: Image.Image,
    result: DetectionResult,
) -> List[Image.Image]:
    """Crop each detected table region from *image*."""
    crops: List[Image.Image] = []
    for bbox in result.bboxes:
        cropped = image.crop((bbox.x0, bbox.y0, bbox.x1, bbox.y1))
        crops.append(cropped)
    return crops


# ---------------------------------------------------------------------------
# OpenCV contour-based backend
# ---------------------------------------------------------------------------

def _detect_opencv(image: Image.Image) -> List[BoundingBox]:
    """Find rectangular grid structures using morphological operations.

    Strategy:
    1. Convert to grayscale + binary (inverted).
    2. Detect horizontal and vertical lines via long morphological kernels.
    3. Combine the two masks → contiguous table grid regions.
    4. Find external contours → bounding rectangles.
    5. Filter by minimum area and aspect ratio.
    """
    arr = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # Adaptive threshold (inverted so lines are white)
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        15, 5,
    )

    img_h, img_w = binary.shape

    # --- Detect horizontal lines ---
    h_kernel_len = max(img_w // 15, 30)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_kernel_len, 1))
    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel, iterations=1)

    # --- Detect vertical lines ---
    v_kernel_len = max(img_h // 15, 30)
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_kernel_len))
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel, iterations=1)

    # Combine
    table_mask = cv2.add(h_lines, v_lines)

    # Dilate to connect nearby line fragments
    join_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    table_mask = cv2.dilate(table_mask, join_kernel, iterations=3)

    # Find contours
    contours, _ = cv2.findContours(
        table_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
    )

    min_area = img_h * img_w * 0.005  # at least 0.5 % of the page
    bboxes: List[BoundingBox] = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < min_area:
            continue
        # Reject very thin / very tall slices (likely not tables)
        aspect = w / max(h, 1)
        if aspect < 0.15 or aspect > 20:
            continue
        bboxes.append(BoundingBox(x0=x, y0=y, x1=x + w, y1=y + h))

    # Sort top-to-bottom
    bboxes.sort(key=lambda b: b.y0)
    return bboxes


# ---------------------------------------------------------------------------
# Table Transformer (TATR) backend
# ---------------------------------------------------------------------------

_tatr_model = None
_tatr_processor = None


def _load_tatr():
    """Lazy-load the TATR model (downloads on first call)."""
    global _tatr_model, _tatr_processor
    if _tatr_model is not None:
        return

    try:
        from transformers import AutoImageProcessor, TableTransformerForObjectDetection
        import torch  # noqa: F401 – just checking availability
    except ImportError as exc:
        raise ImportError(
            "Table Transformer backend requires `transformers` and `torch`. "
            "Install them with: pip install transformers torch"
        ) from exc

    model_name = "microsoft/table-transformer-detection"
    _tatr_processor = AutoImageProcessor.from_pretrained(model_name)
    _tatr_model = TableTransformerForObjectDetection.from_pretrained(model_name)
    _tatr_model.eval()
    logger.info("Loaded Table Transformer model: %s", model_name)


def _detect_tatr(
    image: Image.Image,
    confidence_threshold: float = 0.7,
) -> List[BoundingBox]:
    """Detect tables using the Microsoft Table Transformer model."""
    _load_tatr()

    import torch

    rgb = image.convert("RGB")
    inputs = _tatr_processor(images=rgb, return_tensors="pt")

    with torch.no_grad():
        outputs = _tatr_model(**inputs)

    target_sizes = torch.tensor([rgb.size[::-1]])
    results = _tatr_processor.post_process_object_detection(
        outputs, threshold=confidence_threshold, target_sizes=target_sizes,
    )[0]

    bboxes: List[BoundingBox] = []
    for score, label_id, box in zip(
        results["scores"], results["labels"], results["boxes"],
    ):
        x0, y0, x1, y1 = box.tolist()
        label = _tatr_model.config.id2label.get(int(label_id), "table")
        if label != "table":
            continue
        bboxes.append(BoundingBox(
            x0=int(x0), y0=int(y0),
            x1=int(x1), y1=int(y1),
            confidence=float(score),
            label=label,
        ))

    bboxes.sort(key=lambda b: b.y0)
    return bboxes
