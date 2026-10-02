"""Agentic RAG Orchestrator — Plain LLM ReAct Loop.

Uses direct Ollama API calls with a ReAct-style prompt.
Tools available:
  - sql_query
  - vector_search
  - multi_hop
  - tavily_search
  - graph_search
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.config import get_settings, ollama_extra_fields
from backend.services.llm import generate as llm_generate
from backend.services.tools import ALL_TOOLS
from backend.services.answer_verifier import verify_answer, _focus_violation
from backend.services.query_router import route_query

settings = get_settings()
logger = logging.getLogger(__name__)

HTTP_LIMITS = httpx.Limits(max_connections=4, max_keepalive_connections=2)

SYSTEM_PROMPT = """\
คุณคือ AI Agent ที่เชี่ยวชาญด้านการวิเคราะห์ข้อมูลการเงินภาษาไทย

กฎสำคัญที่สุด:
- คุณ **ต้อง** เรียกใช้ tool อย่างน้อย 1 ตัวก่อนตอบทุกครั้ง ห้ามตอบจากความรู้ของตัวเองโดยเด็ดขาด
- ห้ามตอบว่า "ไม่มีข้อมูล" หรือ "ไม่พบข้อมูล" โดยไม่ได้ลองเรียก tool ค้นหาก่อน
- **ให้ใช้ sql_query** สำหรับคำถามที่เกี่ยวกับตารางกำไรตัวเลขเท่านั้น:
  - ตัวเลข สถิติ อัตราส่วนทางการเงิน (ROA, ROE, NPL, EPS, สินทรัพย์, กำไร, หนี้สิน ฯลฯ)
  - ข้อมูลที่ระบุเป็นปี พ.ศ. ชัดเจน
  - การเรียงลำดับ การเปรียบเทียบจัดอันดับ หาค่าสูงสุด/ต่ำสุด
  - รายชื่อบริษัทที่ลงทุน สัดส่วนผู้ถือหุ้น หรือโครงสร้างบริษัทที่เป็นข้อมูลตารางเชิงตัวเลข
- **ให้ใช้ vector_search เสมอ** สำหรับคำถามที่เกี่ยวกับข้อความ (Text) หรือบทความ:
  - โครงการ นโยบาย มาตรการช่วยเหลือ กลยุทธ์องค์กร บทบาทหน้าที่
  - ESG ความยั่งยืน วิสัยทัศน์ รางวัล หรือคำอธิบายเชิงคุณภาพต่างๆ
- **ให้ใช้ graph_search** เมื่อถามเกี่ยวกับความสัมพันธ์ระหว่างนิติบุคคล:
  - บริษัทใดเป็นเจ้าของบริษัทใด สัดส่วนการถือหุ้น โครงสร้างบริษัทในเครือ
  - ใครดำรงตำแหน่งกรรมการ ผู้บริหาร ในองค์กรใด
  - ความเชื่อมโยงระหว่าง 2 บริษัทหรือบุคคล
- ถ้าคำถามเป็นแนวผสม (Hybrid) ให้ใช้ multi_hop เพื่อดึงข้อมูลทั้งสองมารวมกัน
- ตอบเป็นภาษาไทยเสมอ
- เมื่อใช้ค่าจาก OCR ให้ระบุว่าเป็นค่าที่ถอดจากเอกสารและยังไม่ได้ตรวจยืนยันด้วยตาจาก PDF; อย่าเรียกค่าดังกล่าวว่าได้รับการยืนยันแล้ว ถ้าไม่มีหลักฐานหน้าเอกสาร ให้บอกว่าหน้าอ้างอิงยังไม่ทราบ
- **คำถามเกี่ยวกับรูปภาพตอบได้** เพราะระบบ OCR ได้อ่านและถอดคำบรรยายภาพ (`<figure>...</figure>`)
  เก็บไว้เป็นข้อความในเอกสารแล้ว ถ้าถามถึงสิ่งที่อยู่ในภาพ ให้ค้นด้วย vector_search
  แล้วอ่านคำบรรยายภาพนั้น ห้ามปฏิเสธว่า "วิเคราะห์รูปภาพไม่ได้" ถ้ายังไม่ได้ค้นดูก่อน
- **ปีทั้งหมดในเอกสารและคำถามเป็น พ.ศ. (พุทธศักราช)** เช่น 2567 = ค.ศ. 2024, 2566 = ค.ศ. 2023
  ซึ่งเป็นข้อมูลในอดีตที่มีอยู่จริงในเอกสาร ห้ามตีความว่าเป็นปีในอนาคตหรือบอกว่ายังไม่มีข้อมูลเด็ดขาด
- อ้างอิงตัวเลขและข้อเท็จจริงจากผลลัพธ์ของ tool เท่านั้น ห้ามแต่งข้อมูลเอง
- **ตัวเลขในวงเล็บคือค่าติดลบ** ตามหลักบัญชี เช่น (12,903,917) หมายถึง -12,903,917
  เวลาคำนวณต้องใช้ค่าติดลบเสมอ เช่น (12,903,917) เทียบกับ 29,946,718 ต่างกัน 42,850,635 ไม่ใช่ 17,042,801
- **เลือกแถวที่ชื่อตรงกับคำถามมากที่สุด** เมื่อ tool คืนมาหลายแถว
  เช่น ถาม "เงินสดจ่ายชำระหนี้สินตามสัญญาเช่า" ให้ใช้แถวที่ชื่อตรงกันเป๊ะ
  ไม่ใช่ "เงินสดจ่ายสำหรับหนี้สินภายใต้สัญญาเช่า" ซึ่งเป็นคนละรายการ
- **วงเล็บท้ายชื่อรายการคือ "ส่วน/แถบ" ของตาราง ไม่ใช่ส่วนหนึ่งของชื่อรายการ**
  หน้างบการเงินหนึ่งหน้าถูกแบ่งเป็นหลายแถบ และ `table_name` เก็บชื่อแถบไว้หลังขีด — เช่น
  "… — ยอดคงเหลือ" / "… — รวมมูลค่า ยุติธรรม" / "… — ระดับ 2" / "… — งบการเงินเฉพาะธนาคาร"
  **รายการชื่อเดียวกันมีอยู่ในทุกแถบ แต่ค่าไม่เท่ากัน** เช่น "สินทรัพย์อนุพันธ์ … แบบพลวัต"
  ปี 2567 = 657 ในแถบ `ยอดคงเหลือ` แต่ = 809 ในแถบ `รวมมูลค่า ยุติธรรม`
  ถ้าคำถามมีวงเล็บ ให้เลือกแถวที่ `table_name` ใน Observation ตรงกับข้อความในวงเล็บนั้น
  ถ้าไม่มีแถบที่ตรง ให้ตอบว่าไม่พบ ดีกว่าหยิบค่าจากแถบอื่นมาตอบ
- **เวลาเทียบสองปี ต้องใช้ค่าจากแถวที่ชื่อเดียวกัน (row_label เดียวกัน) เท่านั้น**
  ห้ามหยิบปีหนึ่งจากแถวหนึ่งแล้วอีกปีจากอีกแถว และถ้าผลต่างออกมาเป็น 0 ให้ตรวจว่าหยิบผิดแถวหรือไม่
- ห้ามดัดแปลง แปลงหน่วย หรือคำนวณทศนิยมเป็นเปอร์เซ็นต์ด้วยตัวเองเด็ดขาด ให้แสดงผลตัวเลขตามหน่วยเดิมที่ดึงมาได้จากระบบ
- ให้ใส่หน่วยแนบไปกับตัวเลขเลย (เช่น 1.10%) และห้ามพิมพ์สรุปแยกบรรทัดติ่งไว้ตอนท้ายว่า "หน่วยเป็น..." เด็ดขาด
- **Final Answer ต้องตอบเฉพาะสิ่งที่ถูกถามเท่านั้น** ห้ามพ่วงตัวเลข ข้อเท็จจริง หรือหัวข้ออื่น
  ที่ไม่ได้ถูกถามเข้ามาด้วย ต่อให้เห็นใน Observation ก็ตาม — คำตอบที่ถูกอยู่แล้วจะกลายเป็นผิดทันที
  ถ้าข้อมูลแถมนั้นคลาดเคลื่อน เช่น ถาม "ยอดสินเชื่อของ ก" ให้ตอบยอดของ ก จบ
  ห้ามเล่าต่อว่า "ส่วนของ ข อยู่ที่..." ถ้าเจอหลายค่าใน Observation ให้เลือกค่าเดียวที่ตรงคำถามที่สุด
  ไม่ใช่รายงานทุกค่าที่เห็น
- **คำถามที่ถามว่า "กี่..." ต้องตอบเป็นจำนวนก่อนเสมอ** (กี่กลุ่ม กี่ประการ กี่รายการ กี่ครั้ง กี่บริษัท)
  ถ้าเอกสารระบุจำนวนไว้ตรงๆ ให้ใช้ตัวเลขนั้น ถ้าไม่ระบุให้นับจากรายการที่เจอแล้วตอบเป็นตัวเลข
  เช่น ถาม "แบ่งผู้มีส่วนได้เสียออกเป็นกี่กลุ่ม" ต้องตอบ "9 กลุ่ม" — การไล่ชื่อกลุ่มโดยไม่บอกจำนวน
  ถือว่ายังไม่ได้ตอบคำถาม และถ้าไล่ได้ไม่ครบก็จะกลายเป็นคำตอบที่ผิด

Tools ที่ใช้ได้:
1. sql_query: ค้นหาข้อมูลจากฐานข้อมูล DuckDB — ห้ามใช้หาข้อมูลประเภทนโยบายหรือโครงการ ใช้เฉพาะตามหาตัวเลข จัดอันดับ สถิติงบการเงิน
2. vector_search: ค้นหาเนื้อหาจากเอกสารความเรียง — ใช้หาเนื้อหาที่เกี่ยวกับชื่อโครงการ นโยบาย กลยุทธ์ ESG ภาพรวมการทำงาน
3. multi_hop: แตกคำถามซับซ้อนเป็นคำถามย่อย — ใช้เมื่อคำถามต้องการข้อมูลจากทั้งรูปแบบงบการเงินและรูปแบบเอกสารรวมกัน
4. tavily_search: ค้นหาจากอินเทอร์เน็ต — ใช้เป็นท่าสุดท้ายเมื่อไม่พบข้อมูลในระบบเลย
5. graph_search: ค้นหากราฟความรู้เชิงความสัมพันธ์ — ใช้เมื่อถามเรื่องความสัมพันธ์ระหว่างบริษัท โครงสร้างผู้ถือหุ้น ตำแหน่งกรรมการ หรือการเชื่อมโยงระหว่างนิติบุคคล

ขั้นตอนการตอบ (ReAct):
1. Thought: คิดว่าควรใช้ tool ตัวไหน
2. Action: เรียก tool ด้วยรูปแบบ JSON
3. Observation: ผลลัพธ์จาก tool
4. ... ทำซ้ำได้ถ้าจำเป็น
5. Final Answer: คำตอบสุดท้ายเมื่อมีข้อมูลเพียงพอแล้ว

รูปแบบการเรียก tool:
Thought: <เหตุผลของคุณ>
Action: {"tool": "<tool_name>", "query": "<คำถามที่ต้องการค้นหาเป็นภาษาคน ห้ามเขียน SQL เองเด็ดขาด>"}

เมื่อพร้อมตอบ:
Thought: <สรุปข้อมูลที่ได้>
Final Answer: <คำตอบภาษาไทย>
"""

# ---------------------------------------------------------------------------
# ReAct parsing helpers
# ---------------------------------------------------------------------------

_FINAL_ANSWER_RE = re.compile(
    r'Final Answer:\s*(.*)',
    re.DOTALL,
)

# Phrases an internal tool returns when it found nothing — a "success" with no
# data must NOT count as "internal sources exhausted" (else the agent escapes to
# web search prematurely).
_NO_DATA_MARKERS = ("ไม่พบข้อมูล", "ไม่พบเอกสาร", "ไม่มีข้อมูล", "ไม่พบข้อมูลในกราฟ")


def _has_real_data(observation: str) -> bool:
    obs = (observation or "").strip()
    if not obs:
        return False
    return not any(obs.startswith(m) or obs == m for m in _NO_DATA_MARKERS)


def _is_non_answer(answer: str) -> bool:
    text = (answer or "").strip()
    return any(marker in text for marker in (
        "ไม่พบข้อมูล", "ไม่มีข้อมูล", "ไม่ปรากฏข้อมูล", "ไม่สามารถหาข้อมูล",
        "ไม่พบหลักฐาน", "หลักฐานไม่พอ", "หลักฐานไม่เพียงพอ",
        "หลักฐานยังไม่เพียงพอ", "หน่วยในคำตอบไม่ตรง",
    ))


def _parse_action(text: str) -> Optional[Dict[str, str]]:
    """Extract the first Action JSON from LLM output.
    
    Handles nested braces by finding `Action:` and then extracting
    the first balanced JSON object after it.
    """
    # Find where "Action:" appears
    action_match = re.search(r'Action:\s*', text)
    if not action_match:
        return None
    
    start = action_match.end()
    # Find the opening brace
    brace_start = text.find('{', start)
    if brace_start == -1:
        return None
    
    # Find matching closing brace
    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                json_str = text[brace_start:i+1]
                for candidate in (json_str, _undouble_braces(json_str)):
                    try:
                        action = json.loads(candidate)
                    except json.JSONDecodeError:
                        continue
                    if "tool" in action and "query" in action:
                        return action
                logger.warning("Failed to parse Action JSON: %s", json_str[:200])
                return None
    return None


def _undouble_braces(text: str) -> str:
    """Collapse ``{{...}}`` to ``{...}``.

    Models sometimes echo the doubled braces used for ``str.format`` escaping,
    which is not valid JSON. Accepting both spellings means a formatting slip
    costs a retry at worst instead of the whole question.
    """
    return text.replace("{{", "{").replace("}}", "}")


def _parse_final_answer(text: str) -> Optional[str]:
    """Extract Final Answer from LLM output."""
    match = _FINAL_ANSWER_RE.search(text)
    if match:
        return match.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def _call_llm(prompt: str) -> str:
    """Generate with the configured provider (Ollama local or Gemini)."""
    return await llm_generate(prompt, max_tokens=1024)


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

async def _execute_tool(
    tool_name: str,
    query: str,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Execute a tool by name and return structured result info."""
    tool_obj = ALL_TOOLS.get(tool_name)
    if not tool_obj:
        return {"observation": f"Error: Tool '{tool_name}' not found.", "success": False}

    logger.info("Agent using tool: %s(%s)", tool_name, query[:80])

    try:
        if tool_name in ["vector_search", "multi_hop", "graph_search"]:
            res = await tool_obj.execute(query, session=session)
        else:
            res = await tool_obj.execute(query)

        obs = res.summary if res.success else f"Error: {res.error}"
        return {
            "observation": obs,
            "success": res.success,
            "data": res.data,
            "tool_name": tool_name,
        }
    except Exception as e:
        logger.error("Tool %s failed: %s", tool_name, e)
        return {"observation": f"Error executing tool {tool_name}: {e}", "success": False}


# ---------------------------------------------------------------------------
# Source extraction helpers
# ---------------------------------------------------------------------------

def _extract_sources(tool_name: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract source metadata from tool result data."""
    sources = []
    if tool_name == "sql_query":
        for item in data.get("evidence", []):
            sources.append({"type": "sql", "sql": data.get("sql", ""), **item})
        if not sources:
            sources.append({
                "type": "sql", "sql": data.get("sql", ""),
                "row_count": data.get("row_count", 0),
                "evidence_status": "page_unresolved",
            })
    elif tool_name == "vector_search":
        for chunk in data.get("chunks", []):
            sources.append({
                "type": "vector",
                "filename": chunk.get("filename"),
                "document_id": chunk.get("document_id"),
                "page": chunk.get("page"),
                "table_name": chunk.get("table_name"),
                "quality_status": chunk.get("quality_status"),
                "excerpt": (chunk.get("text") or "")[:12000 if chunk.get("context_kind") == "page" else 2500],
                "context_kind": chunk.get("context_kind"),
                "evidence_status": chunk.get("evidence_status") or "source_not_verified",
                "chunk_index": chunk.get("chunk_index"),
                "similarity": chunk.get("similarity"),
                "source_kind": chunk.get("source_kind"),
            })
    elif tool_name == "multi_hop":
        for sr in data.get("sub_results", []):
            if sr.get("data"):
                sources.extend(_extract_sources(sr.get("tool", ""), sr["data"]))
    elif tool_name == "graph_search":
        for item in data.get("results", []):
            sources.append({
                "type": "graph", "document_id": item.get("doc_id"),
                "page": None, "evidence_status": "page_unresolved",
            })
    elif tool_name == "tavily_search":
        for r in data.get("results", []):
            sources.append({
                "type": "web",
                "url": r.get("url"),
                "title": r.get("title"),
            })
    return sources


async def _available_tools(session: AsyncSession, web_requested: bool = False) -> set[str]:
    """Expose only tools backed by currently indexed data or configured services."""
    available: set[str] = set()
    try:
        from backend.models import Chunk, DocumentPage
        from backend.services.rag import (
            _indexed_page_filter, _indexed_page_join, _searchable_chunk_filter,
        )
        searchable = (select(Chunk.id)
                      .outerjoin(DocumentPage, _indexed_page_join())
                      .where(Chunk.embedding.is_not(None), _searchable_chunk_filter(),
                             _indexed_page_filter()).limit(1))
        if (await session.execute(searchable)).first():
            available.add("vector_search")
    except Exception as exc:
        logger.debug("Vector index availability check failed: %s", exc)
    try:
        from backend.services.duckdb_warehouse import warehouse_capabilities
        caps = warehouse_capabilities()
        if caps["year_cells"] or caps["lookup_cells"]:
            available.add("sql_query")
    except Exception as exc:
        logger.debug("Warehouse availability check failed: %s", exc)
    if {"sql_query", "vector_search"} <= available:
        available.add("multi_hop")
    if not settings.OFFLINE_MODE:
        try:
            from backend.services.graph_service import list_all_graphs
            if any(graph.get("status") == "ready" for graph in list_all_graphs()):
                available.add("graph_search")
        except Exception as exc:
            logger.debug("Graph availability check failed: %s", exc)
        if web_requested and settings.TAVILY_API_KEY:
            available.add("tavily_search")
    return available


_ANSWER_NUMBER = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")
_ANSWER_UNIT = re.compile(r"ล้านบาท|พันบาท|เมกะวัตต์|เปอร์เซ็นต์|บาท|หุ้น|คัน|%")


def _numbers(text: str) -> set[float]:
    values = set()
    for token in _ANSWER_NUMBER.findall(text or ""):
        negative = token.startswith("(") and token.endswith(")")
        try:
            number = float(token.strip("()").replace(",", ""))
            values.add(-number if negative else number)
        except ValueError:
            continue
    return values


def _measure_key(text: str) -> str:
    """Normalize typography and unit footnotes, never merge distinct measures."""
    text = re.sub(r"\(\s*(?:บาท|ล้านบาท|%|\d+)\s*\)", "", text or "")
    return re.sub(r"[\s()]+", "", text).casefold()


def _grounded_answer(answer: str, question: str, sources: List[Dict[str, Any]]) -> str:
    """Refuse an unsupported number, including an opposite sign or changed scale."""
    if not (answer or "").strip():
        return "โมเดลไม่ส่งคำตอบกลับมาในครั้งนี้ กรุณาลองใหม่ โดยหลักฐานที่ค้นพบยังแสดงด้านล่าง"
    if _focus_violation(question, answer):
        return "หลักฐานยังไม่เพียงพอสำหรับเลือกค่าที่ตรงกับคำถามเพียงค่าเดียว"
    located = [source for source in sources
               if source.get("page") is not None or source.get("url")]
    if not located:
        return "ไม่พบหลักฐานพร้อมหน้าเอกสารที่เพียงพอสำหรับคำตอบนี้"
    metric_question = re.sub(r"^\s*(?:จาก)?(?:ไฟล์|เอกสาร|รายงาน)\s+\S+\.pdf\s*", "", question, flags=re.IGNORECASE)
    question_key = _measure_key(metric_question)
    exact_cells = [source for source in located
                   if source.get("type") == "sql" and source.get("row_label")
                   and len(_measure_key(str(source["row_label"]))) >= 5
                   and question_key.startswith(_measure_key(str(source["row_label"])))
                   and re.match(r"^(?:ปี|ณ|มีค่า|เท่ากับ|เท่าไร|กี่|คือ|จำนวน|เป็น)",
                                question_key[len(_measure_key(str(source["row_label"]))):])]
    if exact_cells:
        # A value from a different, similarly named SQL row cannot override a
        # cell whose complete measure label appears in the user's question.
        longest = max(len(_measure_key(str(s["row_label"]))) for s in exact_cells)
        located = [s for s in exact_cells if len(_measure_key(str(s["row_label"]))) == longest]
        asked_years = set(re.findall(r"(?<!\d)(?:25|20)\d{2}(?!\d)", question))
        if len(asked_years) == 1:
            located = [s for s in located if asked_years.intersection(
                re.findall(r"(?<!\d)(?:25|20)\d{2}(?!\d)", str(s.get("column") or "")))]
            if not located:
                return "ไม่พบหลักฐานในหน้าเอกสารที่รองรับตัวเลขในปีที่ถาม"
    allowed = {number for number in _numbers(question)
               if number.is_integer() and (2000 <= number <= 2099 or 2500 <= number <= 2599)}
    for source in located:
        allowed.update(_numbers(str(source.get("value") or "")))
        allowed.update(_numbers(str(source.get("excerpt") or "")))
        allowed.update(_numbers(str(source.get("column") or "")))
    cited_pages = {float(page) for group in re.findall(
        r"(?:PDF\s*)?(?:pages?|หน้า(?:เอกสาร)?(?:ที่)?)\s*(\d+(?:\s*[,、]\s+\d+)*)", answer,
        flags=re.IGNORECASE) for page in re.findall(r"\d+", group)}
    allowed.update(cited_pages & {float(source["page"]) for source in located
                                  if source.get("page") is not None})
    if re.search(r"เปลี่ยน|ต่าง|เพิ่ม|ลด|เทียบ", question):
        # A derived difference is defensible only across two cells of the
        # same stored measure, document, table and unit in different years.
        for i, left in enumerate(located):
            for right in located[i + 1:]:
                identity = ("document_id", "table_name", "row_label", "unit")
                if not all(left.get(key) == right.get(key) for key in identity):
                    continue
                if not left.get("column") or left.get("column") == right.get("column"):
                    continue
                lhs, rhs = _numbers(str(left.get("value") or "")), _numbers(str(right.get("value") or ""))
                if len(lhs) == len(rhs) == 1:
                    difference = next(iter(lhs)) - next(iter(rhs))
                    allowed.update((difference, -difference, abs(difference)))
    if not _numbers(answer) <= allowed:
        return "ไม่พบหลักฐานในหน้าเอกสารที่รองรับตัวเลขในคำตอบ"
    stated_units = set(_ANSWER_UNIT.findall(answer))
    if stated_units:
        answer_values = _numbers(answer) - allowed.intersection(_numbers(question)) - cited_pages
        matching_cells = [source for source in located if source.get("value") is not None
                          and _numbers(str(source["value"])) & answer_values]
        cell_units = {str(source["unit"]).strip() for source in (matching_cells or located) if source.get("unit")}
        if cell_units:
            normalized_units = {"%" if unit == "เปอร์เซ็นต์" else unit for unit in stated_units}
            if not normalized_units <= cell_units:
                return "หน่วยในคำตอบไม่ตรงกับหน่วยของหลักฐานในหน้าเอกสาร"
    if _numbers(answer) and any(source.get("evidence_status") == "ocr_extracted_unverified"
                                for source in located) and "OCR" not in answer and "ยังไม่ตรวจ" not in answer:
        answer += " (ค่าถอดจาก OCR; ยังไม่ตรวจเทียบ PDF)"
    return answer


def _prompt_with_available_tools(available: set[str]) -> str:
    before, _, rest = SYSTEM_PROMPT.partition("Tools ที่ใช้ได้:")
    _, _, after = rest.partition("ขั้นตอนการตอบ (ReAct):")
    if "sql_query" not in available:
        before = re.sub(r"- \*\*ให้ใช้ sql_query\*\*.*?(?=- \*\*ให้ใช้ vector_search)",
                        "", before, flags=re.DOTALL)
    if "vector_search" not in available:
        before = re.sub(r"- \*\*ให้ใช้ vector_search เสมอ\*\*.*?(?=- \*\*ให้ใช้ graph_search)",
                        "", before, flags=re.DOTALL)
    if "graph_search" not in available:
        before = re.sub(r"- \*\*ให้ใช้ graph_search\*\*.*?(?=- ถ้าคำถามเป็นแนวผสม)",
                        "", before, flags=re.DOTALL)
    if "multi_hop" not in available:
        before = re.sub(r"^- ถ้าคำถามเป็นแนวผสม.*\n", "", before, flags=re.MULTILINE)
    descriptions = "\n".join(
        f"- {name}: {ALL_TOOLS[name].description}" for name in sorted(available)
    )
    return (before + "Tools ที่ใช้ได้จริงสำหรับคำถามนี้:\n" + descriptions
            + "\nห้ามเรียกเครื่องมืออื่นนอกเหนือจากรายการนี้\n\nขั้นตอนการตอบ (ReAct):" + after)


def _answer_context(sources: List[Dict[str, Any]], observations: List[str]) -> str:
    """Keep source diversity: duplicate uploads must not crowd out later tables."""
    blocks = []
    seen = set()
    for source in sources:
        if source.get('page') is None and not source.get('url'):
            continue
        if source.get('value') is not None:
            payload = {k:source.get(k) for k in ('filename','page','table_name','row_label','column','value','unit','quality_status')}
            block = json.dumps(payload, ensure_ascii=False)
        else:
            excerpt = str(source.get('excerpt') or '')
            if not excerpt:
                continue
            block = f"[{source.get('filename')} PDF page {source.get('page')}]\n{excerpt[:12000]}"
        if block in seen:
            continue
        seen.add(block); blocks.append(block)
    if not blocks:
        return '\n\n'.join(observations)[:16000]
    if any(source.get('context_kind') == 'page' for source in sources):
        # Pages are already ranked and quality-gated. Preserve their row/year
        # context instead of truncating every page to a short equal prefix.
        return '\n\n'.join(blocks)[:16000]
    # Allocate a fair share to every distinct source, not an arbitrary prefix
    # of combined SQL and vector observations.
    per_source = min(12000, max(800, 16000 // len(blocks)))
    return '\n\n'.join(b[:per_source] for b in blocks)[:16000]


def _exact_cell_answer(data: Dict[str, Any], question: str) -> Optional[str]:
    """An unambiguous exact lookup needs no generative model to restate a cell."""
    if data.get('lookup_kind') != 'exact_measure' or not data.get('evidence'):
        return None
    cell = sorted(data['evidence'], key=lambda s:(s.get('page') or 10**9, s.get('document_id') or 0))[0]
    value, unit = str(cell['value']), str(cell.get('unit') or '')
    shown = value if unit and value.endswith(unit) else f'{value} {unit}'.strip()
    years = re.findall(r'(?<!\d)(?:25|20)\d{2}(?!\d)', str(cell['column']))
    year = f'ปี {years[0]} ' if len(years)==1 else ''
    sources = _extract_sources('sql_query', data)
    return _grounded_answer(f'{year}{shown} (PDF หน้า {cell["page"]})', question, sources)


async def _answer_from_observations(question: str, observations: List[str],
                                    sources: List[Dict[str, Any]]) -> str:
    if not observations or not any(source.get("page") is not None or source.get("url")
                                   for source in sources):
        return "ไม่พบหลักฐานเพียงพอในเอกสารที่ประมวลผลแล้ว"
    prompt = (
        "ตอบคำถามจากหลักฐานต่อไปนี้เท่านั้น เลือกแถว ปี และหน่วยให้ตรงกับคำถาม "
        "เลือกบริษัทและหัวข้อที่ผู้ใช้ระบุ ห้ามแทนด้วยตัวเลขจากคนละส่วนของรายงาน "
        "ถ้าถามเงินบาทและมีเงินบาทในหลักฐานให้ตอบเงินบาท ไม่ตอบดอลลาร์แทน "
        "สำหรับกราฟ ต้องผูกชื่อชุดข้อมูลกับปีและค่าด้วย ถ้าข้อความไม่รักษาความสัมพันธ์นั้นให้บอกว่าหลักฐานไม่พอ "
        "คำนวณผลต่างได้เฉพาะค่าจากแถวและหน่วยเดียวกันสองปี ห้ามแปลงหน่วยเอง แสดงหน้า PDF ที่ใช้ "
        "ตอบสั้นเฉพาะรายการที่ถาม ระบุค่า หน่วย ปี และหน้า ไม่ต้องพิมพ์ตารางหลักฐานซ้ำ "
        "หน่วยของเซลล์มีลำดับเหนือหน่วยในชื่อตาราง เมื่อมีเซลล์ SQL ตรงรายการและปี ให้ใช้เซลล์นั้น "
        "หากข้อความ OCR ขัดกับเซลล์ตรงรายการ ห้ามนำค่าจากข้อความมาแทน และระบุว่าข้อความ OCR ขัดกับตาราง "
        "หากไม่แน่ใจ ให้ตอบว่าหลักฐานไม่พอ ค่าจาก OCR ยังไม่ผ่านการตรวจเทียบ PDF ด้วยตา\n\n"
        f"คำถาม: {question}\n\nหลักฐาน:\n{_answer_context(sources, observations)}\n\nคำตอบ:"
    )
    answer = (await llm_generate(prompt, temperature=0.0, max_tokens=350)).strip()
    critique = _focus_violation(question, answer)
    if critique:
        answer = (await llm_generate(
            prompt + "\nตรวจคำตอบ: " + critique,
            temperature=0.0, max_tokens=350)).strip()
    return _grounded_answer(answer, question, sources)


# ---------------------------------------------------------------------------
# Public API — main agent entry point
# ---------------------------------------------------------------------------

async def _offline_query(question: str, session: AsyncSession) -> Dict[str, Any]:
    """Local-only retrieval and generation without hosted tool planning."""
    route = route_query(question)
    available = await _available_tools(session)
    tool_name = ("sql_query" if route.suggested_tool == "sql_query" and "sql_query" in available
                 else "vector_search" if "vector_search" in available
                 else "sql_query" if "sql_query" in available else "")
    trace: List[Dict[str, Any]] = []
    sql_info = None
    if not tool_name:
        return {"answer": "ยังไม่มีข้อมูลเอกสารที่ค้นหาได้", "method": "offline",
                "sources": [], "sql_info": None, "reasoning_trace": trace}

    async def run(name: str):
        tool = ALL_TOOLS[name]
        result = (
            await tool.execute(question, session=session, top_k=3)
            if name == "vector_search" else await tool.execute(question)
        )
        has_data = bool(result.data.get("chunks")) if name == "vector_search" else result.data.get("row_count", 0) > 0
        trace.append({"action": name, "action_input": question,
                      "observation": (result.summary or result.error or "")[:500],
                      "success": result.success and has_data})
        return result, has_data

    result, has_data = await run(tool_name)
    if not has_data and tool_name == "sql_query" and "vector_search" in available:
        tool_name = "vector_search"
        result, has_data = await run(tool_name)
    if not has_data:
        return {"answer": "ไม่พบหลักฐานเพียงพอในเอกสารที่ประมวลผลแล้ว", "method": "offline",
                "sources": [], "sql_info": None, "reasoning_trace": trace}

    sources = _extract_sources(tool_name, result.data)
    if tool_name == "sql_query":
        sql_info = result.data
        direct = _exact_cell_answer(result.data, question)
        if direct:
            return {"answer":direct,"method":"offline_exact_cell","sources":sources,
                    "sql_info":sql_info,"reasoning_trace":trace}
    if not any(source.get("page") is not None for source in sources):
        return {"answer": "ไม่พบหลักฐานพร้อมหน้าเอกสารที่เพียงพอสำหรับคำตอบนี้",
                "method": "offline", "sources": sources, "sql_info": sql_info,
                "reasoning_trace": trace}
    prompt = (
        "ตอบคำถามจากหลักฐานด้านล่างเท่านั้น ตอบเป็นภาษาเดียวกับคำถาม "
        "ห้ามเติมตัวเลขหรือข้อเท็จจริงที่ไม่มีในหลักฐาน ถ้าหลักฐานไม่พอให้บอกว่าไม่พอ "
        "ค่าจาก OCR ยังไม่ได้ตรวจด้วยตากับ PDF.\n\n"
        f"คำถาม: {question}\n\nหลักฐาน:\n{_answer_context(sources, [result.summary])}\n\nคำตอบสั้นๆ:"
    )
    answer = (await llm_generate(prompt, temperature=0.0, max_tokens=350)).strip()
    if not answer:
        answer = "โมเดลท้องถิ่นไม่สามารถสร้างคำตอบได้ในขณะนี้"
    answer = _grounded_answer(answer, question, sources)
    return {"answer": answer, "method": _infer_method(trace), "sources": sources,
            "sql_info": sql_info, "reasoning_trace": trace}

async def agent_query(
    question: str,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Main agent entry point using a plain LLM ReAct loop.

    Returns
    -------
    dict
        ``{"answer": str, "method": str, "sources": list, "sql_info": dict|None,
           "reasoning_trace": list}``
    """
    if settings.OFFLINE_MODE:
        return await _offline_query(question, session)
    # ------------------------------------------------------------------
    # Fast-path: try direct structured answer before invoking the LLM.
    # ------------------------------------------------------------------
    try:
        from backend.services.rag import try_direct_structured_answer
        direct = await try_direct_structured_answer(question, session)
        if direct:
            logger.info("Fast-path direct answer for: %s", question[:80])
            return {
                "answer": _grounded_answer(direct["answer"], question, direct.get("sources", [])),
                "method": direct.get("method", "direct_structured_fact"),
                "sources": direct.get("sources", []),
                "sql_info": direct.get("sql_info"),
                "reasoning_trace": [{
                    "action": "direct_structured",
                    "action_input": question,
                    "observation": direct["answer"][:500],
                }],
            }
    except Exception as e:
        logger.warning("Direct structured answer failed, falling back to agent: %s", e)

    # ------------------------------------------------------------------
    # Deterministic tool routing hint (biases the first tool choice)
    # ------------------------------------------------------------------
    route = route_query(question)
    web_requested = route.scores.get("tavily_search", 0) > 0
    available_tools = await _available_tools(session, web_requested=web_requested)
    if not available_tools:
        return {"answer": "ยังไม่มีข้อมูลเอกสารที่ค้นหาได้", "method": "agent",
                "sources": [], "sql_info": None, "reasoning_trace": []}
    routing_hint = ""
    if route.suggested_tool in available_tools and route.confidence in ("medium", "high"):
        logger.info(
            "Router suggests '%s' (confidence=%s, scores=%s)",
            route.suggested_tool, route.confidence, route.scores,
        )
        routing_hint = (
            f"\nคำแนะนำการเลือกเครื่องมือ (สำคัญมาก): จากการวิเคราะห์คำถามนี้ "
            f"tool ที่เหมาะสมที่สุดคือ \"{route.suggested_tool}\" — "
            f"ให้เรียกใช้ tool นี้เป็นอันดับแรกเสมอ เว้นแต่ผลลัพธ์ไม่เพียงพอจริงๆ "
            f"จึงค่อยลอง tool อื่น\n"
        )

    # ------------------------------------------------------------------
    # Build initial prompt
    # ------------------------------------------------------------------
    conversation = f"{_prompt_with_available_tools(available_tools)}\n{routing_hint}\nQuestion: {question}\n"

    max_iterations = min(3, getattr(settings, "AGENT_MAX_ITERATIONS", 5))
    max_tool_calls = 2
    reasoning_trace: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    sql_info: Optional[Dict[str, Any]] = None
    full_observations: List[str] = []  # untruncated tool output for verification
    internal_tool_succeeded = False    # gate web search until internal tools tried
    attempted_calls: set = set()       # (tool, query) already run — blocks ReAct loops
    # This corpus is entirely internal (annual report + docs). Only allow web
    # search when the question itself carries an explicit web/news signal;
    # otherwise the agent escapes to Tavily and hallucinates external results.
    web_requested = "tavily_search" in available_tools

    self_correction_on = getattr(settings, "AGENT_SELF_CORRECTION", True)
    verify_retries_left = getattr(settings, "AGENT_VERIFY_MAX_RETRIES", 1)
    _INTERNAL_TOOLS = {"sql_query", "vector_search", "multi_hop", "graph_search"}

    async def sweep_before_refusal(answer: str) -> str:
        """One evidence sweep within the existing two-call budget, then redraft."""
        if (not _is_non_answer(answer) or "vector_search" not in available_tools
                or len(attempted_calls) >= max_tool_calls
                or any(name == "vector_search" for name, _ in attempted_calls)):
            return answer
        attempted_calls.add(("vector_search", question.strip()))
        fb = await _execute_tool("vector_search", question, session)
        found = bool(fb.get("success")) and _has_real_data(fb.get("observation", ""))
        reasoning_trace.append({"action": "vector_search", "action_input": question,
                                "observation": fb.get("observation", "")[:500],
                                "success": found, "reason": "draft_refused"})
        if not found:
            return answer
        full_observations.append("[vector_search] " + fb["observation"])
        sources.extend(_extract_sources("vector_search", fb.get("data") or {}))
        return await _answer_from_observations(question, full_observations, sources)

    # ------------------------------------------------------------------
    # Forced first action: when the router is highly confident, run the
    # suggested tool deterministically instead of trusting the LLM to pick it
    # (a soft prompt hint is not reliable with a local model). The ReAct loop
    # then reasons over the result and can still branch to other tools.
    # ------------------------------------------------------------------
    forced = (next(iter(available_tools)) if len(available_tools) == 1 else
              route.suggested_tool if route.confidence == "high" and route.suggested_tool in available_tools else None)
    if forced:
        logger.info("Forcing first tool (high-confidence route): %s", forced)
        result = await _execute_tool(forced, question, session)
        # The conversation shows this call as a literal Action example — the one
        # the model is most likely to echo verbatim. Register it, or the repeat
        # guard lets the identical call run again for a burned iteration.
        attempted_calls.add((forced, question.strip()))
        obs = result["observation"]
        success = bool(result.get("success"))
        if success and obs:
            full_observations.append(f"[{forced}] {obs}")
        if success and forced in _INTERNAL_TOOLS and _has_real_data(obs):
            internal_tool_succeeded = True
        reasoning_trace.append({
            "action": forced, "action_input": question,
            "observation": obs[:500], "success": success,
        })
        if success and result.get("data"):
            sources.extend(_extract_sources(forced, result["data"]))
            if forced == "sql_query" and sql_info is None:
                sql_info = result["data"]
                direct = _exact_cell_answer(sql_info, question)
                if direct:
                    return {"answer":direct,"method":"exact_cell","sources":sources,
                            "sql_info":sql_info,"reasoning_trace":reasoning_trace}
        conversation += (
            f"Thought: เริ่มด้วยเครื่องมือที่เหมาะสมที่สุดสำหรับคำถามนี้ ({forced})\n"
            f'Action: {{"tool": "{forced}", "query": "{question}"}}\n'
            f"Observation: {obs}\n"
        )

        # The router is keyword-based, so a prose question worded like a metric
        # ("อัตราส่วน…เท่าใด") gets sent to SQL and comes back empty even though
        # the answer sits in a chunk at rank 1. Rather than tune those keywords —
        # brittle, and it risks the many questions routed correctly — sweep the
        # document index before the agent is allowed to conclude "not found".
        if not internal_tool_succeeded and forced != "vector_search" and "vector_search" in available_tools:
            logger.info("Forced tool '%s' found nothing; falling back to vector_search", forced)
            fb = await _execute_tool("vector_search", question, session)
            fb_obs = fb["observation"]
            fb_found = bool(fb.get("success")) and _has_real_data(fb_obs)
            attempted_calls.add(("vector_search", question.strip()))
            if fb_found:
                internal_tool_succeeded = True
                full_observations.append(f"[vector_search] {fb_obs}")
                if fb.get("data"):
                    sources.extend(_extract_sources("vector_search", fb["data"]))
            reasoning_trace.append({
                "action": "vector_search", "action_input": question,
                "observation": fb_obs[:500], "success": fb_found,
            })
            conversation += (
                f"Thought: {forced} ไม่พบข้อมูล ลองค้นจากเอกสารด้วย vector_search\n"
                f'Action: {{"tool": "vector_search", "query": "{question}"}}\n'
                f"Observation: {fb_obs}\n"
            )

        if internal_tool_succeeded and sources:
            answer = await _answer_from_observations(question, full_observations, sources)
            answer = await sweep_before_refusal(answer)
            return {"answer": answer, "method": _infer_method(reasoning_trace),
                    "sources": sources, "sql_info": sql_info,
                    "reasoning_trace": reasoning_trace}

    if len(attempted_calls) >= max_tool_calls and not sources:
        return {"answer": "ไม่พบหลักฐานเพียงพอในเอกสารที่ประมวลผลแล้ว",
                "method": _infer_method(reasoning_trace), "sources": [],
                "sql_info": sql_info, "reasoning_trace": reasoning_trace}

    llm_output = ""
    for iteration in range(max_iterations):
        logger.info("ReAct iteration %d/%d", iteration + 1, max_iterations)
        llm_output = await _call_llm(conversation)

        if not llm_output:
            logger.warning("LLM returned empty response at iteration %d", iteration + 1)
            break

        # Check for tool call first (prioritise action over final answer)
        action = _parse_action(llm_output)
        if action:
            tool_name = action["tool"]
            query = action["query"]
            logger.info("ReAct action: %s(%s)", tool_name, query[:80])

            if tool_name not in available_tools:
                conversation += (f"{llm_output}\nObservation: เครื่องมือ {tool_name} "
                                 "ไม่มีข้อมูลหรือไม่ได้ตั้งค่า ห้ามเรียกอีก ให้ใช้หลักฐานที่มี\n")
                continue

            if len(attempted_calls) >= max_tool_calls:
                answer = await _answer_from_observations(question, full_observations, sources)
                return {"answer": answer, "method": _infer_method(reasoning_trace),
                        "sources": sources, "sql_info": sql_info,
                        "reasoning_trace": reasoning_trace}

            # Guard: this corpus is internal-only. Block web search entirely
            # unless the question explicitly asked for web/news info — escaping
            # to Tavily on internal questions just produces hallucinated results.
            if tool_name == "tavily_search" and not web_requested:
                nudge = (
                    "คำถามนี้ตอบได้จากข้อมูลภายในทั้งหมด ห้ามค้นอินเทอร์เน็ต "
                    "ให้ใช้ vector_search สำหรับเนื้อหา/คำอธิบาย, sql_query สำหรับตัวเลข/ตาราง, "
                    "graph_search สำหรับความสัมพันธ์ ถ้าไม่พบจริงๆ ให้ตอบว่าไม่พบข้อมูลในเอกสาร"
                )
                logger.info("Blocked premature tavily_search; nudging to internal tools")
                reasoning_trace.append({
                    "action": tool_name, "action_input": query,
                    "observation": nudge, "success": False,
                })
                conversation += f"{llm_output}\nObservation: {nudge}\n"
                continue

            # Re-issuing a call already made returns the same observation, so the
            # agent can sit in that loop until it runs out of iterations and the
            # answer it already found never becomes a Final Answer. Refuse the
            # repeat and ask it to conclude from what it has.
            call_key = (tool_name, query.strip())
            if call_key in attempted_calls:
                nudge = (
                    "คุณเรียก tool นี้ด้วยคำค้นเดิมไปแล้ว และได้ผลลัพธ์เดิม "
                    "ห้ามค้นซ้ำอีก ให้สรุปคำตอบจากข้อมูลที่มีอยู่แล้วด้วย Final Answer: ทันที "
                    "ถ้าข้อมูลที่มีตอบได้ให้ตอบเลย ถ้าไม่พบจริงๆ จึงบอกว่าไม่พบข้อมูลในเอกสาร"
                )
                logger.info("Blocked repeated call %s(%s); nudging to conclude", tool_name, query[:50])
                reasoning_trace.append({
                    "action": tool_name, "action_input": query,
                    "observation": nudge, "success": False,
                })
                conversation += f"{llm_output}\nObservation: {nudge}\n"
                continue
            attempted_calls.add(call_key)

            result = await _execute_tool(tool_name, query, session)
            obs = result["observation"]
            success = bool(result.get("success"))
            if success and obs:
                full_observations.append(f"[{tool_name}] {obs}")
            if success and tool_name in _INTERNAL_TOOLS and _has_real_data(obs):
                internal_tool_succeeded = True

            # Record trace
            reasoning_trace.append({
                "action": tool_name,
                "action_input": query,
                "observation": obs[:500],
                "success": success,
            })

            # Collect sources & sql_info
            if success and result.get("data"):
                sources.extend(_extract_sources(tool_name, result["data"]))
                if tool_name == "sql_query" and sql_info is None:
                    sql_info = result["data"]

            # Append to conversation for next iteration
            conversation += f"{llm_output}\nObservation: {obs}\n"

            # Same rescue as the forced-tool path above, which only covered the
            # *first* call. A prose question worded like a metric ("CAGR เท่าใด",
            # "มูลค่าสุทธิต่อหุ้น…") reaches sql_query on the agent's own choice
            # too; SQL comes back empty, the repeat guard then blocks the retry,
            # and the agent concludes "ไม่พบข้อมูล" while the answer sits in a
            # chunk at rank 1. Sweep the document index once before letting it
            # reach that conclusion.
            if (
                tool_name in _INTERNAL_TOOLS
                and tool_name != "vector_search"
                and "vector_search" in available_tools
                and not internal_tool_succeeded  # a safety net for the found-
                # nothing-anywhere case, like its forced-path twin — not a tax
                # on every empty exploratory call after data is already in hand
                and not _has_real_data(obs)
                and ("vector_search", query.strip()) not in attempted_calls
                and len(attempted_calls) < max_tool_calls
            ):
                logger.info("'%s' returned no data; sweeping vector_search", tool_name)
                fb = await _execute_tool("vector_search", query, session)
                fb_obs = fb["observation"]
                fb_found = bool(fb.get("success")) and _has_real_data(fb_obs)
                # Failed attempts consume the same bounded tool budget.
                attempted_calls.add(("vector_search", query.strip()))
                if fb_found:
                    internal_tool_succeeded = True
                    full_observations.append(f"[vector_search] {fb_obs}")
                    if fb.get("data"):
                        sources.extend(_extract_sources("vector_search", fb["data"]))
                reasoning_trace.append({
                    "action": "vector_search", "action_input": query,
                    # Data-success, not call-success: VectorSearchTool reports
                    # success=True for "no documents found", and _infer_method
                    # counts successful entries — an empty sweep must not
                    # relabel a pure-SQL answer as "hybrid".
                    "observation": fb_obs[:500], "success": fb_found,
                })
                # A fruitless sweep must not balloon the prompt: the full dump
                # is up to top_k x 2,500 chars, re-sent every iteration.
                conv_obs = fb_obs if fb_found else "ไม่พบข้อมูลจากเอกสารเช่นกัน"
                conversation += (
                    f"Thought: {tool_name} ไม่พบข้อมูล ลองค้นจากเอกสารด้วย vector_search\n"
                    f'Action: {{"tool": "vector_search", "query": "{query}"}}\n'
                    f"Observation: {conv_obs}\n"
                )
            continue

        # Check for Final Answer
        final_answer = _parse_final_answer(llm_output)
        if final_answer:
            logger.info("ReAct final answer at iteration %d", iteration + 1)

            final_answer = await sweep_before_refusal(final_answer)

            # --- Self-correction: verify the draft is grounded & on-topic ---
            if self_correction_on and verify_retries_left > 0:
                verification = await verify_answer(
                    question, final_answer, "\n\n".join(full_observations)
                )
                if not verification.passed:
                    verify_retries_left -= 1
                    logger.info(
                        "Self-correction triggered (retries left=%d): %s",
                        verify_retries_left, verification.issues,
                    )
                    reasoning_trace.append({
                        "action": "self_correction",
                        "action_input": verification.critique,
                        "observation": "; ".join(verification.issues)[:500],
                    })
                    # Feed the critique back and let the agent redraft.
                    conversation += (
                        f"{llm_output}\n"
                        f"Observation: คำตอบยังไม่ผ่านการตรวจสอบ — "
                        f"{verification.critique or 'คำตอบต้องอ้างอิงจากข้อมูลที่ค้นมาได้เท่านั้น'} "
                        f"กรุณาแก้ไขและตอบใหม่ด้วย Final Answer โดยอ้างอิงเฉพาะข้อมูลจาก Observation ข้างต้น\n"
                    )
                    continue

            return {
                "answer": _grounded_answer(final_answer, question, sources),
                "method": _infer_method(reasoning_trace),
                "sources": sources,
                "sql_info": sql_info,
                "reasoning_trace": reasoning_trace,
            }

        # Neither an Action nor a Final Answer parsed. If the model clearly *meant*
        # to call a tool (it wrote "Action:") the reply is reasoning, not an answer —
        # returning it verbatim leaks scaffolding like 'Thought: ... Action: {...}'
        # to the user. Restate the format and let it try again instead.
        if "Action:" in llm_output and iteration < max_iterations - 1:
            logger.info("ReAct: malformed Action, re-prompting with the exact format")
            conversation += (
                f"{llm_output}\n"
                "Observation: รูปแบบ Action ไม่ถูกต้อง ให้เขียนใหม่เป็น JSON บรรทัดเดียว "
                'ด้วยวงเล็บปีกกาชั้นเดียว เช่น Action: {"tool": "vector_search", "query": "..."} '
                "หรือถ้ามีข้อมูลพอแล้วให้ตอบด้วย Final Answer:\n"
            )
            continue

        logger.info("ReAct: no action/final answer parsed, using raw output")
        answer = llm_output.strip()
        # Try to clean up any Thought: prefix
        if "Thought:" in answer:
            parts = answer.split("Thought:")
            answer = parts[-1].strip()
        return {
            "answer": _grounded_answer(answer, question, sources),
            "method": _infer_method(reasoning_trace),
            "sources": sources,
            "sql_info": sql_info,
            "reasoning_trace": reasoning_trace,
        }

    # Exhausted iterations — use last LLM output
    final_answer = _parse_final_answer(llm_output) if llm_output else None
    answer = final_answer or llm_output or "ขออภัย ระบบไม่สามารถหาคำตอบได้ในขณะนี้"

    return {
        "answer": _grounded_answer(answer, question, sources),
        "method": _infer_method(reasoning_trace),
        "sources": sources,
        "sql_info": sql_info,
        "reasoning_trace": reasoning_trace,
    }


def _infer_method(trace: List[Dict[str, Any]]) -> str:
    """Infer the primary method used from the reasoning trace."""
    tools_used = set()
    for entry in trace:
        action = entry.get("action")
        # Only count tools that actually returned useful data. A failed call
        # (e.g. tavily timing out) must not dictate the reported method.
        if action and entry.get("success", True) and action != "self_correction":
            tools_used.add(action)

    if "tavily_search" in tools_used:
        return "web_search"
    if "multi_hop" in tools_used:
        return "multi_hop"
    if "graph_search" in tools_used and "sql_query" in tools_used:
        return "graph_sql_hybrid"
    if "graph_search" in tools_used:
        return "graph"
    if "sql_query" in tools_used and "vector_search" in tools_used:
        return "hybrid"
    if "sql_query" in tools_used:
        return "sql"
    if "vector_search" in tools_used:
        return "vector"
    return "agent"
