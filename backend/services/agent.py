"""Agentic RAG Orchestrator — LangGraph Implementation.

Replaces the previous custom ReAct loop with a stateful LangGraph agent.
Tools available:
  - sql_query
  - vector_search
  - multi_hop
  - tavily_search
"""

import json
import logging
import operator
from typing import Any, Dict, List, Optional, TypedDict

from typing_extensions import Annotated
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langgraph.graph import StateGraph, END

from backend.config import get_settings
from backend.services.tools import ALL_TOOLS

settings = get_settings()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State Definition
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    session: AsyncSession
    sources: List[Dict[str, Any]]
    sql_info: Optional[Dict[str, Any]]
    reasoning_trace: List[Dict[str, Any]]

# ---------------------------------------------------------------------------
# LangChain Tools (Schema only for binding)
# ---------------------------------------------------------------------------

@tool
def sql_query(query: str) -> str:
    """Query structured financial data stored in DuckDB. Use for specific numbers, statistics, comparisons, rankings, year-over-year changes, or any tabular data lookup."""
    pass

@tool
def vector_search(query: str) -> str:
    """Search documents by meaning. Use for explanations, concepts, summaries, policies, strategies, or qualitative information."""
    pass

@tool
def multi_hop(query: str) -> str:
    """Break a complex question into 2-3 simpler sub-questions, gather data from SQL and/or Vector Search, then combine."""
    pass

@tool
def tavily_search(query: str) -> str:
    """Search the internet for current events, news, or general knowledge that might not be in the internal database. Use as a fallback when other tools don't have the answer."""
    pass

tools_list = [sql_query, vector_search, multi_hop, tavily_search]

SYSTEM_PROMPT = """\
คุณคือ AI Agent ที่เชี่ยวชาญด้านการวิเคราะห์ข้อมูลการเงินภาษาไทย

กฎสำคัญที่สุด:
- คุณ **ต้อง** เรียกใช้ tool อย่างน้อย 1 ตัวก่อนตอบทุกครั้ง ห้ามตอบจากความรู้ของตัวเองโดยเด็ดขาด
- ห้ามตอบว่า "ไม่มีข้อมูล" หรือ "ไม่พบข้อมูล" โดยไม่ได้ลองเรียก tool ค้นหาก่อน
- ถ้าคำถามเกี่ยวกับตัวเลข สถิติ อัตราส่วน (เช่น ROA, ROE, NPL, EPS, สินทรัพย์, กำไร, หนี้สิน) → ใช้ sql_query เสมอ
- ถ้า sql_query ไม่พบข้อมูล → ลอง vector_search เป็น fallback
- ตอบเป็นภาษาไทยเสมอ
- อ้างอิงตัวเลขและข้อเท็จจริงจากผลลัพธ์ของ tool เท่านั้น ห้ามแต่งข้อมูลเอง
- ห้ามดัดแปลง แปลงหน่วย หรือคำนวณทศนิยมเป็นเปอร์เซ็นต์ด้วยตัวเองเด็ดขาด ให้แสดงผลตัวเลขตามหน่วยเดิมที่ดึงมาได้จากระบบ
- ให้ใส่หน่วยแนบไปกับตัวเลขเลย (เช่น 1.10%) และห้ามพิมพ์สรุปแยกบรรทัดติ่งไว้ตอนท้ายว่า "หน่วยเป็น..." อีกเด็ดขาด

คุณสามารถเลือกใช้ tool เหล่านี้ได้ตามความเหมาะสม:
1. sql_query: เมื่อคำถามต้องการข้อมูลตัวเลข งบประมาณ หรือเปรียบเทียบเชิงสถิติจากฐานข้อมูล (DuckDB)
2. vector_search: เมื่อคำถามเกี่ยวกับนโยบาย แนวคิด หรือคำอธิบายจากเอกสาร (RAG)
3. multi_hop: เมื่อคำถามซับซ้อนมากและต้องการข้อมูลจากหลายแหล่ง
4. tavily_search: เมื่อไม่พบข้อมูลในฐานข้อมูลของเรา แล้วต้องการค้นหาข้อมูลจากอินเทอร์เน็ต
"""

# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def agent_node(state: AgentState) -> Dict[str, Any]:
    """Node that invokes the LLM to decide on actions or answer."""
    messages = state["messages"]
    
    llm = ChatOllama(
        model=settings.OLLAMA_LLM_MODEL,
        base_url=settings.OLLAMA_HOST,
        temperature=getattr(settings, "AGENT_TEMPERATURE", 0.1)
    )
    llm_with_tools = llm.bind_tools(tools_list)
    
    try:
        response = await llm_with_tools.ainvoke(messages)
    except Exception as e:
        logger.error("LLM invoke failed: %s", e)
        # Fallback if LLM fails
        from langchain_core.messages import AIMessage
        response = AIMessage(content="ขออภัย เกิดข้อผิดพลาดในการประมวลผลคำตอบ (LLM Error)")
        
    return {"messages": [response]}


async def tool_node(state: AgentState) -> Dict[str, Any]:
    """Node that executes chosen tools and updates context."""
    messages = state["messages"]
    session = state.get("session")
    sources = list(state.get("sources", []))
    sql_info = state.get("sql_info")
    reasoning_trace = list(state.get("reasoning_trace", []))
    
    last_message = messages[-1]
    new_messages = []
    
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            query = tool_args.get("query", "")
            
            tool_obj = ALL_TOOLS.get(tool_name)
            if not tool_obj:
                new_messages.append(ToolMessage(
                    tool_call_id=tool_call["id"],
                    content=f"Error: Tool {tool_name} not found.",
                    name=tool_name
                ))
                continue
                
            logger.info("LangGraph agent using tool: %s(%s)", tool_name, query[:80])
            
            try:
                # Execute
                if tool_name in ["vector_search", "multi_hop"]:
                    res = await tool_obj.execute(query, session=session)
                else:
                    res = await tool_obj.execute(query)
                    
                obs = res.summary if res.success else f"Error: {res.error}"
                
                # Record reasoning trace
                reasoning_trace.append({
                    "action": tool_name,
                    "action_input": query,
                    "observation": obs[:500]
                })
                
                # Extract specific state data for sources
                if tool_name == "sql_query" and res.success:
                    if not sql_info:
                        sql_info = res.data
                    sources.append({
                        "type": "sql",
                        "sql": res.data.get("sql", ""),
                        "row_count": res.data.get("row_count", 0),
                    })
                elif tool_name == "vector_search" and res.success:
                    for chunk in res.data.get("chunks", []):
                        sources.append({
                            "type": "vector",
                            "filename": chunk.get("filename"),
                            "chunk_index": chunk.get("chunk_index"),
                            "similarity": chunk.get("similarity"),
                            "source_kind": chunk.get("source_kind"),
                        })
                elif tool_name == "multi_hop" and res.success:
                    for sr in res.data.get("sub_results", []):
                        sources.append({
                            "type": "multi_hop",
                            "sub_question": sr.get("question"),
                            "tool": sr.get("tool"),
                        })
                elif tool_name == "tavily_search" and res.success:
                    for r in res.data.get("results", []):
                        sources.append({
                            "type": "web",
                            "url": r.get("url"),
                            "title": r.get("title")
                        })
                        
                new_messages.append(ToolMessage(
                    tool_call_id=tool_call["id"],
                    content=str(obs),
                    name=tool_name
                ))
            except Exception as e:
                logger.error("Tool %s failed: %s", tool_name, e)
                new_messages.append(ToolMessage(
                    tool_call_id=tool_call["id"],
                    content=f"Error executing tool {tool_name}: {e}",
                    name=tool_name
                ))
            
    return {
        "messages": new_messages,
        "sources": sources,
        "sql_info": sql_info,
        "reasoning_trace": reasoning_trace
    }


def should_continue(state: AgentState):
    """Router function to decide whether to call tools or end."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END

# ---------------------------------------------------------------------------
# Graph Compilation
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tool_node)
    
    builder.set_entry_point("agent")
    builder.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    
    return builder.compile()

# ---------------------------------------------------------------------------
# Public API — main agent entry point
# ---------------------------------------------------------------------------

async def agent_query(
    question: str,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Main agent entry point using LangGraph.

    Returns
    -------
    dict
        ``{"answer": str, "method": str, "sources": list, "sql_info": dict|None,
           "reasoning_trace": list}``
    """
    # ------------------------------------------------------------------
    # Fast-path: try direct structured answer before invoking LangGraph.
    # This catches simple numeric look-ups (e.g. ROA ปี 2567) instantly
    # without relying on the LLM to pick the right tool.
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

    graph = build_graph()
    
    initial_state = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=question)
        ],
        "session": session,
        "sources": [],
        "sql_info": None,
        "reasoning_trace": []
    }
    
    # Run the graph
    max_iter = getattr(settings, "AGENT_MAX_ITERATIONS", 5)
    try:
        final_state = await graph.ainvoke(initial_state, config={"recursion_limit": max_iter * 2})
    except Exception as e:
        logger.error("LangGraph execution failed: %s", e)
        return {
            "answer": f"ขออภัย เกิดข้อผิดพลาดในการทำงานของระบบ (Graph Error: {e})",
            "method": "error",
            "sources": [],
            "sql_info": None,
            "reasoning_trace": []
        }
    
    final_message = final_state["messages"][-1].content
    method = _infer_method(final_state["reasoning_trace"])
    
    return {
        "answer": final_message,
        "method": method,
        "sources": final_state["sources"],
        "sql_info": final_state["sql_info"],
        "reasoning_trace": final_state["reasoning_trace"],
    }

def _infer_method(trace: List[Dict[str, Any]]) -> str:
    """Infer the primary method used from the reasoning trace."""
    tools_used = set()
    for entry in trace:
        action = entry.get("action")
        if action:
            tools_used.add(action)

    if "tavily_search" in tools_used:
        return "web_search"
    if "multi_hop" in tools_used:
        return "multi_hop"
    if "sql_query" in tools_used and "vector_search" in tools_used:
        return "hybrid"
    if "sql_query" in tools_used:
        return "sql"
    if "vector_search" in tools_used:
        return "vector"
    return "langgraph"
