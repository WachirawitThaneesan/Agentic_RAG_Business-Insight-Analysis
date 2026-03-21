"""Thai-specific post-processing normaliser for OCR table output.

Fixes common OCR errors in Thai text such as garbled vowels, missing
tone marks, digit/letter confusion (O→0, l→1), and inconsistent
number formatting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    from pythainlp.util import normalize as thai_normalize
    HAS_PYTHAINLP = True
except ImportError:
    HAS_PYTHAINLP = False


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class NormalizedTable:
    """Table data after Thai normalisation."""

    headers: List[str]
    rows: List[List[str]]
    corrections_applied: int = 0


# ---------------------------------------------------------------------------
# Common OCR confusion pairs for Thai characters
# ---------------------------------------------------------------------------

# Characters that OCR frequently confuses.  The map is applied only when
# the surrounding context strongly suggests the replacement.
_THAI_CONFUSION_CONTEXT: List[Tuple[re.Pattern, str]] = [
    # Missing สระอำ  → sometimes OCR splits it into สระอะ + ม
    (re.compile(r"(\u0E30)(\u0E21)"), "\u0E33"),  # ะม → ำ

    # Garbled นิคหิต (อํ) → should be อำ in modern Thai
    (re.compile(r"\u0E4D"), "\u0E33"),  # ํ → ำ

    # Double วรรณยุกต์ — keep only the last one
    (re.compile(r"([\u0E48\u0E49\u0E4A\u0E4B]){2,}"), r"\1"),

    # Stray combining marks at start of cell
    (re.compile(r"^[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]+"), ""),
]

# Latin/digit confusion in numeric context
_DIGIT_CONFUSION: Dict[str, str] = {
    "O": "0",
    "o": "0",
    "l": "1",
    "I": "1",
    "S": "5",
    "B": "8",
    "Z": "2",
    "G": "6",
}

# Thai digit → Arabic digit
_THAI_DIGIT_MAP: Dict[str, str] = {
    "๐": "0", "๑": "1", "๒": "2", "๓": "3", "๔": "4",
    "๕": "5", "๖": "6", "๗": "7", "๘": "8", "๙": "9",
}

# Unit normalisation
_UNIT_NORMALISATION: Dict[str, str] = {
    "ลบ.": "ล้านบาท",
    "ล.บ.": "ล้านบาท",
    "ลบ": "ล้านบาท",
    "พบ.": "พันบาท",
    "พ.บ.": "พันบาท",
}

# Regex for cells that look almost-numeric but have stray characters
_ALMOST_NUMERIC = re.compile(
    r"^[+-]?[\dOolISBZG][\dOolISBZG,]*\.?[\dOolISBZG]*$"
)

# Strict numeric
_STRICT_NUMERIC = re.compile(r"^[+-]?\d[\d,]*\.?\d*$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_thai_table(
    headers: List[str],
    rows: List[List[str]],
) -> NormalizedTable:
    """Apply Thai-specific cleaning to every cell in the table.

    Steps:
    1. PyThaiNLP unicode normalisation
    2. Thai confusion-pair fixes
    3. Thai digit → Arabic digit conversion
    4. Digit/letter confusion fix for numeric cells
    5. Unit normalisation
    6. Whitespace cleanup
    """
    corrections = 0

    cleaned_headers = []
    for header in headers:
        cleaned, n = _clean_cell(header, is_header=True)
        cleaned_headers.append(cleaned)
        corrections += n

    cleaned_rows = []
    for row in rows:
        cleaned_row = []
        for cell in row:
            cleaned, n = _clean_cell(cell, is_header=False)
            cleaned_row.append(cleaned)
            corrections += n
        cleaned_rows.append(cleaned_row)

    return NormalizedTable(
        headers=cleaned_headers,
        rows=cleaned_rows,
        corrections_applied=corrections,
    )


def normalize_thai_text(text: str) -> str:
    """Normalise a single Thai text string (non-table context)."""
    cleaned, _ = _clean_cell(text, is_header=False)
    return cleaned


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clean_cell(value: str, is_header: bool = False) -> Tuple[str, int]:
    """Clean a single cell value.  Returns (cleaned, corrections_count)."""
    text = str(value or "").strip()
    if not text:
        return "", 0

    original = text
    corrections = 0

    # 1) PyThaiNLP unicode normalisation
    if HAS_PYTHAINLP:
        text = thai_normalize(text)

    # 2) Thai confusion-pair context fixes
    for pattern, replacement in _THAI_CONFUSION_CONTEXT:
        text, n = pattern.subn(replacement, text)
        corrections += n

    # 3) Thai digits → Arabic
    text, n = _convert_thai_digits(text)
    corrections += n

    # 4) Digit/letter confusion (only for numeric-looking cells)
    if not is_header and _looks_almost_numeric(text):
        text, n = _fix_digit_confusion(text)
        corrections += n

    # 5) Unit normalisation (for header cells)
    if is_header:
        for abbrev, full in _UNIT_NORMALISATION.items():
            if abbrev in text:
                text = text.replace(abbrev, full)
                corrections += 1

    # 6) Whitespace cleanup
    text = _clean_whitespace(text)

    if text != original:
        corrections = max(corrections, 1)

    return text, corrections


def _convert_thai_digits(text: str) -> Tuple[str, int]:
    """Replace Thai numerals with Arabic digits."""
    result = []
    count = 0
    for char in text:
        if char in _THAI_DIGIT_MAP:
            result.append(_THAI_DIGIT_MAP[char])
            count += 1
        else:
            result.append(char)
    return "".join(result), count


def _looks_almost_numeric(text: str) -> bool:
    """Check if a cell looks like it should be numeric but has OCR errors."""
    stripped = text.strip().lstrip("(").rstrip(")").strip()
    if not stripped:
        return False
    return bool(_ALMOST_NUMERIC.match(stripped))


def _fix_digit_confusion(text: str) -> Tuple[str, int]:
    """Replace common letter→digit confusions in numeric cells."""
    # Preserve parentheses (accounting negative)
    inner = text
    prefix = ""
    suffix = ""
    if text.startswith("(") and text.endswith(")"):
        prefix = "("
        suffix = ")"
        inner = text[1:-1]

    result = []
    count = 0
    for char in inner:
        if char in _DIGIT_CONFUSION:
            result.append(_DIGIT_CONFUSION[char])
            count += 1
        else:
            result.append(char)

    return prefix + "".join(result) + suffix, count


def _clean_whitespace(text: str) -> str:
    """Collapse whitespace, remove ZWNJ/ZWJ, trim."""
    # Remove zero-width characters
    text = text.replace("\u200B", "")  # ZWSP
    text = text.replace("\u200C", "")  # ZWNJ
    text = text.replace("\u200D", "")  # ZWJ
    text = text.replace("\uFEFF", "")  # BOM

    # Collapse multiple spaces
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
