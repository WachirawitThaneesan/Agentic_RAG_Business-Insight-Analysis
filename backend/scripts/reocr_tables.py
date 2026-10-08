"""Re-read the annual report's broken tables with Gemini and emit clean JSON.

Why this exists
---------------
The ingest pipeline detects tables with TATR and reads their cells, but on 68
of the report's 163 tables it failed to capture the *header row*. Those tables
land in the warehouse with columns named ``column_3``, ``column_4`` ... — 4,908
cells whose meaning is lost. Two consequences:

  * the year columns of financial tables are unlabelled, so those metrics never
    reach ``fact_financial_metrics`` and cannot be queried by year at all;
  * ``unit`` picks up a number from the wrong cell on 34 of 38 rows.

The page image still contains the header. A vision model reading the whole page
at once keeps the header attached to its column, which a detect-then-OCR
pipeline loses when the two stages disagree about the grid.

This script only *reads*. It writes JSON to --out and touches no database, so it
is safe to run and inspect before anything is loaded.

Usage:
    python -m backend.scripts.reocr_tables --pages 23,86,99 --out tables.json
    python -m backend.scripts.reocr_tables --pages-file pages.txt --out tables.json
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# 200 DPI keeps Thai tone marks legible without making the request huge; the
# page is one image regardless, so this only affects clarity, not token count.
RENDER_DPI = 200

PROMPT = """\
นี่คือภาพหน้าหนึ่งจากรายงานธุรกิจหรือการเงิน (ภาษาไทยหรืออังกฤษ)

งานของคุณ: อ่าน **ตารางทุกตาราง** ในหน้านี้ออกมาเป็น JSON

กฎสำคัญ:
1. **หัวคอลัมน์ต้องอ่านให้ครบและถูกต้อง** — ถ้าหัวคอลัมน์เป็นปี (เช่น 2566, 2567,
   หรือ "31 ธ.ค. 2567") ให้ใส่ตามนั้น ห้ามตั้งชื่อเองว่า column_1 เด็ดขาด
2. ถ้าตารางมีหัวสองชั้น (เช่น "งบการเงินรวม" ครอบ "2566 | 2567") ให้รวมเป็นชื่อเดียว
   เช่น "งบการเงินรวม 2566"
3. เก็บตัวเลขตามที่เห็น รวมวงเล็บด้วย — `(1,234)` ให้เขียน `(1,234)` ห้ามแปลงเป็น -1234
4. ชื่อแถว (row_label) ต้องเป็นข้อความเต็ม ห้ามตัดกลางคำ ห้ามย่อ/สรุป/เปลี่ยนชื่อ
   เก็บวรรณยุกต์และคำขยายท้ายแถว เช่น กิจการอื่น กับ กิจการที่เกี่ยวข้องกัน ให้ตรงต้นฉบับ
5. ถ้าตารางมีหน่วยกำกับ (เช่น "หน่วย: ล้านบาท") ให้ใส่ในช่อง unit ของตารางนั้น
6. ถ้าหน้านี้ไม่มีตารางเลย ให้ตอบ {"tables": []}
7. แยกตารางตามกรอบและหัวคอลัมน์จริง โดยเฉพาะหน้าที่มีหลายกรอบหรือสองหน้าวางคู่กัน
   ตารางเล็กระยะสั้น/กลาง/ยาว กับตารางรายละเอียดด้านการเงินที่อยู่ด้านล่างเป็นคนละตาราง
   ห้ามนำหัวจากกรอบหนึ่งมาครอบค่าจากอีกกรอบ ห้ามรวมตารางข้างซ้ายและขวาที่หัวต่างกัน
8. columns ให้มีเฉพาะหัวของค่าที่อยู่ใน values ตามลำดับซ้ายไปขวา
   หัวคอลัมน์ชื่อแถวให้ใช้เป็น row_label และไม่ใส่ซ้ำใน columns หรือ values
   จำนวนหัว columns ต้องเท่ากับจำนวน values ของทุกแถว ห้ามย้ายค่าเพื่อให้จำนวนตรง
   ถ้าไม่สามารถผูกหัวและค่าได้จากภาพ ให้เว้นตารางนั้นแทนการแต่งหัวหรือเดาความหมาย
9. หัวที่วางซ้อนในแนวตั้งเหนือค่าคอลัมน์เดียวเป็นหัวเดียว เช่น วันที่/งบรวม/ตรวจสอบ
   ห้ามสร้างคอลัมน์ค่าคนละช่องสำหรับคำว่า งบรวม และ ตรวจสอบ เมื่อค่าจริงอยู่แนวเดียวกัน
10. เก็บหน่วยที่พิมพ์เฉพาะแถวไว้ท้าย row_label เช่น (ล้านบาท) แม้หัวใหญ่ระบุ บาท (THB)
    ตารางที่มีคอลัมน์ หน่วย ต้องรักษาคอลัมน์นั้น และห้ามใช้หน่วยเงินครอบแถวร้อยละ
    คอลัมน์ หน่วย ที่พิมพ์แยกเป็นคอลัมน์ค่าใน columns และ values เสมอ แม้ไม่ใช่ตัวเลข
    เช่น columns=["หน่วย", "ปีแรก", "ปีถัดมา"] โดยใช้ปีที่พิมพ์จริง ห้ามย้ายหน่วยลง row_label
11. ห้ามแปลง comma เป็นจุดทศนิยม ตรวจเครื่องหมายตัวเลขตามภาพ โดยไม่คำนวณแก้ค่าเอง
12. ชื่อโรงไฟฟ้า/บริษัท/ส่วนตารางที่กำกับค่าต้องอยู่ใน title หรือชื่อแถว ไม่ตัดทิ้ง
    เก็บคอลัมน์ตัวตนอื่นที่พิมพ์จริงด้วย เช่น บริษัทที่อาจมีความขัดแย้งและลักษณะรายการ
    row_label คือข้อความของคอลัมน์ซ้ายสุดจริงเท่านั้น ห้ามย้ายคอลัมน์รายละเอียดมาแทนตัวตน
    เก็บข้อความเซลล์รวมและ line breaks โดยไม่แจกตัวเลขให้ subitem ที่ตำแหน่งไม่ตรงกัน
    ตัวเลข subtotal ต้องผูกกับ subtotal ไม่ใช่รายการอธิบายก่อนหน้า
13. สารบัญหรือ navigation sidebar ไม่ใช่ตารางข้อมูล ห้ามแปลงเป็น financial cells
    รายการ bullet หรือ numbered list ที่ไม่มีหัวคอลัมน์/แถวแบบตาราง ไม่ให้สร้างเป็นตารางเอง
    key/value disclosure ที่ไม่มีหัวพิมพ์ให้ใช้หัวกลางว่า ค่า ห้ามใช้ชื่อ field JSON เป็นหัว
14. ถ้าไม่มีหลักฐานหัวคอลัมน์ในภาพ ให้เว้นตารางนั้น ห้ามเดาปีจากปีรายงาน
    หรือรูปแบบที่คุ้นเคย

ตอบเป็น JSON เท่านั้น รูปแบบ:
{
  "tables": [
    {
      "title": "<ชื่อ/คำบรรยายตาราง ถ้ามี>",
      "unit": "<หน่วย ถ้ามี เช่น ล้านบาท>",
      "columns": ["<หัวคอลัมน์แรก>", "<หัวคอลัมน์ที่สอง>", "..."],
      "rows": [
        {"row_label": "<ชื่อแถว>", "values": ["<ค่า1>", "<ค่า2>", "..."]}
      ]
    }
  ]
}"""

TABLE_RESPONSE_SCHEMA = {
    'type': 'OBJECT', 'required': ['tables'], 'properties': {
        'tables': {'type': 'ARRAY', 'items': {'type': 'OBJECT',
            'required': ['title', 'unit', 'columns', 'rows'],
            'properties': {'title': {'type': 'STRING'}, 'unit': {'type': 'STRING'},
                'columns': {'type': 'ARRAY', 'items': {'type': 'STRING'}},
                'rows': {'type': 'ARRAY', 'items': {'type': 'OBJECT',
                    'required': ['row_label', 'values'], 'properties': {
                        'row_label': {'type': 'STRING'},
                        'values': {'type': 'ARRAY', 'items': {'type': 'STRING'}}}}}}}}}}


def _render_page(pdf_path: Path, page_no: int) -> bytes:
    """Render 1-based *page_no* of the PDF to PNG bytes."""
    import fitz

    with fitz.open(pdf_path) as doc:
        page = doc[page_no - 1]
        pix = page.get_pixmap(dpi=RENDER_DPI)
        return pix.tobytes("png")


def _read_page(client, model: str, png: bytes) -> Dict[str, Any]:
    """Ask the model for this page's tables, retrying past the shared quota.

    Vertex meters generation from a pool shared across the project, so a burst
    of page reads draws 429s that mean "slow down", not "this page is bad".
    """
    import random
    import time

    from backend.services.llm import _is_retryable

    last: Exception | None = None
    for attempt in range(settings.GEMINI_MAX_RETRIES):
        try:
            return _read_page_once(client, model, png)
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            last = exc
            delay = settings.GEMINI_RETRY_BASE_DELAY * (2 ** attempt) * (0.5 + random.random())
            logger.info("    429/5xx — retry %d in %.1fs", attempt + 1, delay)
            time.sleep(delay)
    raise last if last else RuntimeError("retries exhausted")


def _read_page_once(client, model: str, png: bytes) -> Dict[str, Any]:
    """One request: ask the model for this page's tables and parse the reply."""
    from google.genai import types

    contents = [types.Part.from_bytes(data=png, mime_type="image/png"), PROMPT]
    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=32768,
            response_mime_type="application/json",
            response_schema=TABLE_RESPONSE_SCHEMA,
            thinking_config=types.ThinkingConfig(
                thinking_budget=settings.GEMINI_THINKING_BUDGET
            ),
        ),
    )
    text = (resp.text or "").strip()
    usage = getattr(resp, "usage_metadata", None)
    tokens = (
        getattr(usage, "prompt_token_count", 0) or 0,
        getattr(usage, "candidates_token_count", 0) or 0,
    )
    if not text:
        return {"tables": [], "_tokens": tokens, "_error": "empty response", "_raw_response_text": text}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return {"tables": [], "_tokens": tokens, "_error": "unparsable", "_raw_response_text": text}
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return {"tables": [], "_tokens": tokens, "_error": "unparsable", "_raw_response_text": text}
    if not isinstance(data, dict):
        return {"tables": [], "_tokens": tokens, "_error": "response is not an object", "_raw_response_text": text}
    data["_tokens"] = tokens
    data["_raw_response_text"] = text
    return data


def _parse_pages(spec: str) -> List[int]:
    """Accept '1,2,5-9' and return a sorted unique page list."""
    out: set[int] = set()
    for part in re.split(r"[,\s]+", spec.strip()):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return sorted(out)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default="backend/uploads/annual-report-2024-th.pdf")
    ap.add_argument("--pages", help="e.g. 23,86,99-102")
    ap.add_argument("--pages-file", help="file holding the same comma-separated list")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=settings.GEMINI_MODEL)
    args = ap.parse_args()

    if not (args.pages or args.pages_file):
        ap.error("need --pages or --pages-file")
    spec = args.pages or Path(args.pages_file).read_text(encoding="utf-8")
    pages = _parse_pages(spec)

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        logger.error("PDF not found: %s", pdf_path)
        return 1

    from backend.services.llm import _get_genai_client  # reuse credentials setup

    client = _get_genai_client()
    if client is None:
        logger.error("Gemini client unavailable — check Vertex settings in .env")
        return 1

    logger.info("Re-reading %d pages from %s with %s", len(pages), pdf_path.name, args.model)
    results, tin, tout, failed = [], 0, 0, []
    for n, page_no in enumerate(pages, 1):
        try:
            png = _render_page(pdf_path, page_no)
            data = _read_page(client, args.model, png)
        except Exception as exc:  # one bad page must not lose the other 47
            logger.warning("[%d/%d] page %d FAILED: %s", n, len(pages), page_no, exc)
            failed.append(page_no)
            continue
        ti, to = data.pop("_tokens", (0, 0))
        tin += ti
        tout += to
        err = data.pop("_error", None)
        tables = data.get("tables") or []
        if err:
            failed.append(page_no)
        results.append({"page": page_no, "tables": tables, "error": err})
        logger.info(
            "[%d/%d] page %-4d %d ตาราง %s",
            n, len(pages), page_no, len(tables), f"({err})" if err else "",
        )

    Path(args.out).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cost = tin / 1e6 * 0.30 + tout / 1e6 * 2.50
    logger.info("")
    logger.info("wrote %s", args.out)
    logger.info("pages ok      : %d / %d", len(pages) - len(failed), len(pages))
    if failed:
        logger.info("pages failed  : %s", failed)
    logger.info("tables read   : %d", sum(len(r["tables"]) for r in results))
    logger.info("tokens        : in %s / out %s", f"{tin:,}", f"{tout:,}")
    logger.info("cost          : $%.4f  (~%.2f THB)", cost, cost * 35.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
