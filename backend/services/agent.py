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

from backend.config import get_settings, ollama_extra_fields
from backend.services.llm import generate as llm_generate
from backend.services.tools import ALL_TOOLS
from backend.services.answer_verifier import verify_answer
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
- **เวลาเทียบสองปี ต้องใช้ค่าจากแถวที่ชื่อเดียวกัน (row_label เดียวกัน) เท่านั้น**
  ห้ามหยิบปีหนึ่งจากแถวหนึ่งแล้วอีกปีจากอีกแถว และถ้าผลต่างออกมาเป็น 0 ให้ตรวจว่าหยิบผิดแถวหรือไม่
- ห้ามดัดแปลง แปลงหน่วย หรือคำนวณทศนิยมเป็นเปอร์เซ็นต์ด้วยตัวเองเด็ดขาด ให้แสดงผลตัวเลขตามหน่วยเดิมที่ดึงมาได้จากระบบ
- ให้ใส่หน่วยแนบไปกับตัวเลขเลย (เช่น 1.10%) และห้ามพิมพ์สรุปแยกบรรทัดติ่งไว้ตอนท้ายว่า "หน่วยเป็น..." เด็ดขาด
- **Final Answer ต้องตอบเฉพาะสิ่งที่ถูกถามเท่านั้น** ห้ามพ่วงตัวเลข ข้อเท็จจริง หรือหัวข้ออื่น
  ที่ไม่ได้ถูกถามเข้ามาด้วย ต่อให้เห็นใน Observation ก็ตาม — คำตอบที่ถูกอยู่แล้วจะกลายเป็นผิดทันที
  ถ้าข้อมูลแถมนั้นคลาดเคลื่อน เช่น ถาม "ยอดสินเชื่อของ ก" ให้ตอบยอดของ ก จบ
  ห้ามเล่าต่อว่า "ส่วนของ ข อยู่ที่..." ถ้าเจอหลายค่าใน Observation ให้เลือกค่าเดียวที่ตรงคำถามที่สุด
  ไม่ใช่รายงานทุกค่าที่เห็น

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
        sources.append({
            "type": "sql",
            "sql": data.get("sql", ""),
            "row_count": data.get("row_count", 0),
        })
    elif tool_name == "vector_search":
        for chunk in data.get("chunks", []):
            sources.append({
                "type": "vector",
                "filename": chunk.get("filename"),
                "chunk_index": chunk.get("chunk_index"),
                "similarity": chunk.get("similarity"),
                "source_kind": chunk.get("source_kind"),
            })
    elif tool_name == "multi_hop":
        for sr in data.get("sub_results", []):
            sources.append({
                "type": "multi_hop",
                "sub_question": sr.get("question"),
                "tool": sr.get("tool"),
            })
    elif tool_name == "tavily_search":
        for r in data.get("results", []):
            sources.append({
                "type": "web",
                "url": r.get("url"),
                "title": r.get("title"),
            })
    return sources


# ---------------------------------------------------------------------------
# Public API — main agent entry point
# ---------------------------------------------------------------------------

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
    # ------------------------------------------------------------------
    # Fast-path: try direct structured answer before invoking the LLM.
    # ------------------------------------------------------------------
    try:
        from backend.services.rag import try_direct_structured_answer
        direct = await try_direct_structured_answer(question, session)
        if direct:
            logger.info("Fast-path direct answer for: %s", question[:80])
            return {
                "answer": direct["answer"],
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
    routing_hint = ""
    if route.suggested_tool and route.confidence in ("medium", "high"):
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
    conversation = f"{SYSTEM_PROMPT}\n{routing_hint}\nQuestion: {question}\n"

    max_iterations = getattr(settings, "AGENT_MAX_ITERATIONS", 5)
    reasoning_trace: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    sql_info: Optional[Dict[str, Any]] = None
    full_observations: List[str] = []  # untruncated tool output for verification
    internal_tool_succeeded = False    # gate web search until internal tools tried
    attempted_calls: set = set()       # (tool, query) already run — blocks ReAct loops
    # This corpus is entirely internal (annual report + docs). Only allow web
    # search when the question itself carries an explicit web/news signal;
    # otherwise the agent escapes to Tavily and hallucinates external results.
    web_requested = route.scores.get("tavily_search", 0) > 0

    self_correction_on = getattr(settings, "AGENT_SELF_CORRECTION", True)
    verify_retries_left = getattr(settings, "AGENT_VERIFY_MAX_RETRIES", 1)
    _INTERNAL_TOOLS = {"sql_query", "vector_search", "multi_hop", "graph_search"}

    # ------------------------------------------------------------------
    # Forced first action: when the router is highly confident, run the
    # suggested tool deterministically instead of trusting the LLM to pick it
    # (a soft prompt hint is not reliable with a local model). The ReAct loop
    # then reasons over the result and can still branch to other tools.
    # ------------------------------------------------------------------
    if (
        route.suggested_tool
        and route.confidence == "high"
        and route.suggested_tool in ALL_TOOLS
    ):
        forced = route.suggested_tool
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
        if not internal_tool_succeeded and forced != "vector_search":
            logger.info("Forced tool '%s' found nothing; falling back to vector_search", forced)
            fb = await _execute_tool("vector_search", question, session)
            fb_obs = fb["observation"]
            fb_found = bool(fb.get("success")) and _has_real_data(fb_obs)
            if fb.get("success"):
                # Register only a completed call: a transient error must not
                # lock the agent out of deliberately retrying this search.
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
                and not internal_tool_succeeded  # a safety net for the found-
                # nothing-anywhere case, like its forced-path twin — not a tax
                # on every empty exploratory call after data is already in hand
                and not _has_real_data(obs)
                and ("vector_search", query.strip()) not in attempted_calls
            ):
                logger.info("'%s' returned no data; sweeping vector_search", tool_name)
                fb = await _execute_tool("vector_search", query, session)
                fb_obs = fb["observation"]
                fb_found = bool(fb.get("success")) and _has_real_data(fb_obs)
                if fb.get("success"):
                    # Register only a completed call — recording it up front let
                    # a transient embedding error permanently block the agent's
                    # own vector_search retry, with a nudge falsely claiming it
                    # had "already got this result".
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
                "answer": final_answer,
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
            "answer": answer,
            "method": _infer_method(reasoning_trace),
            "sources": sources,
            "sql_info": sql_info,
            "reasoning_trace": reasoning_trace,
        }

    # Exhausted iterations — use last LLM output
    final_answer = _parse_final_answer(llm_output) if llm_output else None
    answer = final_answer or llm_output or "ขออภัย ระบบไม่สามารถหาคำตอบได้ในขณะนี้"

    return {
        "answer": answer,
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
