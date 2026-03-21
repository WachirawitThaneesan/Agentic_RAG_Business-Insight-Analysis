"""Agentic RAG Orchestrator — ReAct loop with tool selection.

Replaces the previous classify → retrieve → answer pipeline with a
Reasoning + Acting (ReAct) loop that lets the LLM decide which tools
to call and when it has enough information to answer.

Tools available:
  - sql_query     — DuckDB financial data
  - vector_search — pgvector semantic search
  - multi_hop     — decompose & synthesise complex queries
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.services.tools import (
    ALL_TOOLS,
    ToolResult,
    get_tools_description,
)

settings = get_settings()
logger = logging.getLogger(__name__)

HTTP_LIMITS = httpx.Limits(max_connections=4, max_keepalive_connections=2)
MAX_ITERATIONS = getattr(settings, "AGENT_MAX_ITERATIONS", 5)
AGENT_TEMP = getattr(settings, "AGENT_TEMPERATURE", 0.1)


# ---------------------------------------------------------------------------
# ReAct prompt template
# ---------------------------------------------------------------------------

_REACT_SYSTEM = """\
คุณคือ AI Agent ที่เชี่ยวชาญด้านการวิเคราะห์ข้อมูลการเงินภาษาไทย

คุณมี tools ดังนี้:
{tools_desc}

กฎการทำงาน (ReAct Loop):
1. **Thought**: คิดว่าต้องการข้อมูลอะไร และ tool ไหนเหมาะ
2. **Action**: เลือก tool และระบุ input
3. **Observation**: อ่านผลลัพธ์ของ tool
4. ทำซ้ำ 1-3 จนมีข้อมูลเพียงพอ (สูงสุด {max_iter} รอบ)
5. **Answer**: สรุปคำตอบสุดท้ายเป็นภาษาไทย

รูปแบบ output (ต้องใช้รูปแบบนี้เท่านั้น):
Thought: [คิดว่าต้องทำอะไร]
Action: [tool_name]
Action Input: [คำถามหรือ query สำหรับ tool]

เมื่อพร้อมตอบ:
Thought: [มีข้อมูลเพียงพอแล้ว]
Answer: [คำตอบสุดท้ายเป็นภาษาไทย]

กฎสำคัญ:
- ตอบเป็นภาษาไทยเสมอ
- อ้างอิงตัวเลขและข้อเท็จจริงจากผลลัพธ์ของ tool เท่านั้น
- ถ้า SQL ไม่พบข้อมูล ให้ลอง vector_search
- ถ้าคำถามซับซ้อน (เปรียบเทียบหลายตัว, สรุปภาพรวม) ให้ใช้ multi_hop
"""


def _build_system_prompt() -> str:
    return _REACT_SYSTEM.format(
        tools_desc=get_tools_description(),
        max_iter=MAX_ITERATIONS,
    )


# ---------------------------------------------------------------------------
# ReAct parser
# ---------------------------------------------------------------------------

_RE_THOUGHT = re.compile(r"Thought:\s*(.+?)(?=\n(?:Action|Answer):|\Z)", re.DOTALL)
_RE_ACTION = re.compile(r"Action:\s*(\S+)")
_RE_ACTION_INPUT = re.compile(r"Action Input:\s*(.+?)(?=\n(?:Thought|Action|Answer):|\Z)", re.DOTALL)
_RE_ANSWER = re.compile(r"Answer:\s*(.+)", re.DOTALL)


def _parse_react_step(text: str) -> Dict[str, Optional[str]]:
    """Parse a ReAct-formatted LLM response."""
    thought_m = _RE_THOUGHT.search(text)
    action_m = _RE_ACTION.search(text)
    input_m = _RE_ACTION_INPUT.search(text)
    answer_m = _RE_ANSWER.search(text)

    return {
        "thought": thought_m.group(1).strip() if thought_m else None,
        "action": action_m.group(1).strip() if action_m else None,
        "action_input": input_m.group(1).strip() if input_m else None,
        "answer": answer_m.group(1).strip() if answer_m else None,
    }


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def _llm_generate(prompt: str, system: str = "") -> str:
    """Call Ollama LLM and return the generated text."""
    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    try:
        async with httpx.AsyncClient(timeout=600.0, limits=HTTP_LIMITS) as client:
            resp = await client.post(
                f"{settings.OLLAMA_HOST}/api/generate",
                json={
                    "model": settings.OLLAMA_LLM_MODEL,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {
                        "temperature": AGENT_TEMP,
                        "num_predict": 2000,
                    },
                },
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Public API — main agent entry point
# ---------------------------------------------------------------------------

async def agent_query(
    question: str,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Main agent entry point: runs a ReAct loop to answer the question.

    Returns
    -------
    dict
        ``{"answer": str, "method": str, "sources": list, "sql_info": dict|None,
           "reasoning_trace": list}``
    """
    system_prompt = _build_system_prompt()
    conversation = f"Question: {question}\n\n"
    reasoning_trace: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []
    sql_info: Optional[Dict[str, Any]] = None

    for iteration in range(MAX_ITERATIONS):
        # Ask LLM for the next step
        llm_output = await _llm_generate(conversation, system=system_prompt)
        step = _parse_react_step(llm_output)

        trace_entry = {
            "iteration": iteration + 1,
            "thought": step["thought"],
            "action": step["action"],
            "action_input": step["action_input"],
            "raw_output": llm_output[:500],
        }

        # --- Final Answer ---
        if step["answer"]:
            trace_entry["answer"] = step["answer"]
            reasoning_trace.append(trace_entry)

            method = _infer_method(reasoning_trace)
            return {
                "answer": step["answer"],
                "method": method,
                "sources": sources,
                "sql_info": sql_info,
                "reasoning_trace": reasoning_trace,
            }

        # --- Tool call ---
        action = step["action"]
        action_input = step["action_input"] or question

        if not action or action not in ALL_TOOLS:
            # LLM didn't produce a valid action — try to force an answer
            conversation += f"{llm_output}\n\nPlease respond with either a valid Action or a final Answer.\n\n"
            reasoning_trace.append(trace_entry)
            continue

        # Execute the tool
        tool = ALL_TOOLS[action]
        logger.info("Agent iter %d: %s(%s)", iteration + 1, action, action_input[:80])

        if action == "vector_search":
            tool_result: ToolResult = await tool.execute(action_input, session=session)
        elif action == "multi_hop":
            tool_result = await tool.execute(action_input, session=session)
        else:
            tool_result = await tool.execute(action_input)

        # Collect sources
        if action == "sql_query" and tool_result.success:
            sql_info = tool_result.data
            sources.append({
                "type": "sql",
                "sql": tool_result.data.get("sql", ""),
                "row_count": tool_result.data.get("row_count", 0),
            })
        elif action == "vector_search" and tool_result.success:
            for chunk in tool_result.data.get("chunks", []):
                sources.append({
                    "type": "vector",
                    "filename": chunk.get("filename"),
                    "chunk_index": chunk.get("chunk_index"),
                    "similarity": chunk.get("similarity"),
                    "source_kind": chunk.get("source_kind"),
                })
        elif action == "multi_hop" and tool_result.success:
            for sr in tool_result.data.get("sub_results", []):
                sources.append({
                    "type": "multi_hop",
                    "sub_question": sr.get("question"),
                    "tool": sr.get("tool"),
                })

        # Append observation to conversation
        observation = tool_result.summary if tool_result.success else f"Error: {tool_result.error}"
        trace_entry["observation"] = observation[:500]
        reasoning_trace.append(trace_entry)

        conversation += (
            f"{llm_output}\n"
            f"Observation: {observation}\n\n"
        )

    # Max iterations reached — generate final answer from what we have
    logger.warning("Agent reached max iterations for question: %s", question[:80])
    fallback_answer = await _generate_fallback_answer(question, reasoning_trace)

    return {
        "answer": fallback_answer,
        "method": "react_fallback",
        "sources": sources,
        "sql_info": sql_info,
        "reasoning_trace": reasoning_trace,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_method(trace: List[Dict[str, Any]]) -> str:
    """Infer the primary method used from the reasoning trace."""
    tools_used = set()
    for entry in trace:
        action = entry.get("action")
        if action:
            tools_used.add(action)

    if "multi_hop" in tools_used:
        return "multi_hop"
    if "sql_query" in tools_used and "vector_search" in tools_used:
        return "hybrid"
    if "sql_query" in tools_used:
        return "sql"
    if "vector_search" in tools_used:
        return "vector"
    return "react"


async def _generate_fallback_answer(
    question: str,
    trace: List[Dict[str, Any]],
) -> str:
    """Generate a final answer from accumulated observations when loop maxed out."""
    context_parts = []
    for entry in trace:
        obs = entry.get("observation", "")
        if obs:
            context_parts.append(obs)

    if not context_parts:
        return "ไม่พบข้อมูลที่เกี่ยวข้อง กรุณาลองถามคำถามอื่นหรืออัปโหลดเอกสารเพิ่มเติม"

    context = "\n\n".join(context_parts)
    prompt = (
        "คุณคือผู้ช่วย AI ที่เชี่ยวชาญในการวิเคราะห์เอกสารทางการเงินภาษาไทย\n\n"
        "กฎ:\n"
        "1. ตอบเป็นภาษาไทย\n"
        "2. อ้างอิงตัวเลขจากข้อมูลที่ให้มาเท่านั้น\n"
        "3. ห้ามแต่งข้อมูลเอง\n\n"
        f"=== ข้อมูลที่รวบรวมได้ ===\n{context[:6000]}\n=== จบข้อมูล ===\n\n"
        f"คำถาม: {question}\n\n"
        "คำตอบ:"
    )
    return await _llm_generate(prompt)
