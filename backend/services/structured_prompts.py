"""Structured prompts optimised for Typhoon OCR table extraction.

Provides system-level and user-level prompt templates that instruct Typhoon
to output strict Markdown tables (or JSON), preserving empty cells and
consistent column counts.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_MARKDOWN_TABLE = """\
คุณเป็น OCR engine เชี่ยวชาญด้านการอ่านตารางจากเอกสารภาษาไทย

กฎที่ต้องปฏิบัติตามอย่างเคร่งครัด:
1. Output เฉพาะ Markdown Table เท่านั้น ห้ามมีข้อความอื่นนอกตาราง
2. แถวแรกต้องเป็น Header Row เสมอ ตามด้วย separator row (|---|---|)
3. ทุกแถวต้องมีจำนวน Column เท่ากันกับ Header Row
4. เซลล์ที่ว่างเปล่า ให้ใส่เป็นช่องว่าง (| |) ห้ามเติมค่าใดๆ เอง
5. เซลล์ที่เป็นเครื่องหมาย "-" หรือ "–" ให้คงไว้ตามต้นฉบับ
6. ตัวเลขต้องรักษาเครื่องหมายจุลภาค (,) และจุดทศนิยม (.) ตามต้นฉบับ
7. ห้ามปัดเศษ หรือเปลี่ยนแปลงตัวเลข
8. ภาษาไทย: รักษาสระบน-ล่าง วรรณยุกต์ ตัวการันต์ ให้ครบถ้วน
9. หากตารางมีหลาย Header Row (multi-level headers) ให้รวมเป็น Header Row เดียวโดยใช้คำเต็ม
10. หากมีหลายตารางในภาพ ให้ Output แต่ละตารางแยกกัน คั่นด้วยบรรทัดว่าง 1 บรรทัด
"""

SYSTEM_PROMPT_JSON_TABLE = """\
คุณเป็น OCR engine เชี่ยวชาญด้านการอ่านตารางจากเอกสารภาษาไทย

กฎที่ต้องปฏิบัติตามอย่างเคร่งครัด:
1. Output เป็น JSON เท่านั้น ตาม schema:
   {"tables": [{"title": "...", "headers": ["col1", "col2"], "rows": [["val1", "val2"]]}]}
2. ทุกแถวต้องมีจำนวนค่าเท่ากันกับ headers
3. เซลล์ว่างให้ใส่เป็น "" (empty string) ห้ามเติมค่าใดๆ เอง
4. เซลล์ที่เป็นเครื่องหมาย "-" หรือ "–" ให้คงไว้ตามต้นฉบับ
5. ตัวเลขต้องเป็น string เสมอ เช่น "1,234.56" ห้ามแปลงเป็น number
6. ห้ามปัดเศษ หรือเปลี่ยนแปลงตัวเลข
7. ภาษาไทย: รักษาสระบน-ล่าง วรรณยุกต์ ตัวการันต์ ให้ครบถ้วน
8. หากมีหลายตารางในภาพ ให้ใส่ทั้งหมดใน array "tables"
"""


# ---------------------------------------------------------------------------
# User prompts
# ---------------------------------------------------------------------------

USER_PROMPT_EXTRACT_TABLE = """\
อ่านตารางทั้งหมดจากภาพนี้ให้ครบถ้วนและแม่นยำ\
"""

USER_PROMPT_EXTRACT_SUBREGION = """\
อ่านเฉพาะข้อมูลตารางในส่วนที่เห็นนี้ให้ครบถ้วนและแม่นยำ \
เน้นอ่านตัวเลขและข้อความภาษาไทยให้ถูกต้อง\
"""


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------

def build_table_extraction_prompt(
    output_format: str = "markdown",
    extra_instructions: Optional[str] = None,
) -> dict[str, str]:
    """Return a ``{system, user}`` prompt pair for Typhoon OCR.

    Parameters
    ----------
    output_format : str
        ``"markdown"`` or ``"json"``.
    extra_instructions : str, optional
        Additional instructions appended to the user prompt.
    """
    if output_format == "json":
        system = SYSTEM_PROMPT_JSON_TABLE
    else:
        system = SYSTEM_PROMPT_MARKDOWN_TABLE

    user = USER_PROMPT_EXTRACT_TABLE
    if extra_instructions:
        user = f"{user}\n\n{extra_instructions}"

    return {"system": system, "user": user}


def build_subregion_prompt(
    output_format: str = "markdown",
) -> dict[str, str]:
    """Prompt pair for re-OCR of a specific sub-image (row/cell retry)."""
    if output_format == "json":
        system = SYSTEM_PROMPT_JSON_TABLE
    else:
        system = SYSTEM_PROMPT_MARKDOWN_TABLE

    return {"system": system, "user": USER_PROMPT_EXTRACT_SUBREGION}
