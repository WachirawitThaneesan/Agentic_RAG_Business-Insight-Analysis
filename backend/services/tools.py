"""Agent Tools for the Agentic RAG system.

Three tools the ReAct agent can invoke:
1. **SQLTool**           – queries DuckDB ``fact_financial_metrics``
2. **VectorSearchTool**  – semantic search via pgvector
3. **MultiHopTool**      – decomposes complex questions into sub-queries
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from backend.config import get_settings
from backend.services.duckdb_warehouse import execute_sql, get_schema_description

settings = get_settings()
logger = logging.getLogger(__name__)

HTTP_LIMITS = httpx.Limits(max_connections=4, max_keepalive_connections=2)


# ---------------------------------------------------------------------------
# Tool result container
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    """Standardised output from any tool."""

    tool_name: str
    success: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""  # concise text the agent sees in observation
    error: str = ""


# ---------------------------------------------------------------------------
# 1. SQL Tool — queries DuckDB
# ---------------------------------------------------------------------------

class SQLTool:
    """Generate and execute SQL against the DuckDB data warehouse."""

    name = "sql_query"
    description = (
        "Query structured financial data stored in DuckDB. "
        "Use for specific numbers, statistics, comparisons, "
        "rankings, year-over-year changes, or any tabular data lookup."
    )

    async def execute(self, question: str) -> ToolResult:
        """Generate SQL via LLM, execute on DuckDB, return results."""

        schema_desc = get_schema_description()
        sql = await self._generate_sql(question, schema_desc)

        if not sql:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="ไม่สามารถสร้าง SQL ได้",
            )

        result = execute_sql(sql)
        if result.get("error"):
            # Retry once with the error feedback
            sql2 = await self._generate_sql(
                question, schema_desc,
                error_feedback=f"SQL error: {result['error']}\nFailed SQL: {sql}",
            )
            if sql2:
                result = execute_sql(sql2)
                sql = sql2

        if result.get("error"):
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=result["error"],
                data={"sql": sql},
            )

        summary = self._format_results(result)
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"sql": sql, **result},
            summary=summary,
        )

    async def _generate_sql(
        self,
        question: str,
        schema_desc: str,
        error_feedback: str = "",
    ) -> str:
        prompt = (
            "You are a DuckDB SQL expert. Generate a DuckDB-compatible SELECT query "
            "to answer the user's question.\n\n"
            f"{schema_desc}\n"
        )
        if error_feedback:
            prompt += f"\nPrevious attempt failed:\n{error_feedback}\nPlease fix the query.\n\n"

        prompt += (
            "CRITICAL RULES:\n"
            "1. NEVER JOIN fact_financial_metrics with dim_table_rows. They are independent tables.\n"
            "2. For listing companies, investments, or shareholdings → use dim_table_rows ONLY.\n"
            "3. For financial figures with years (สินทรัพย์, กำไร, ROA, etc.) → use fact_financial_metrics ONLY.\n"
            "4. ALWAYS include WHERE table_name LIKE '%keyword%' when querying either table.\n"
            "5. 'อันดับแรก' or 'แรก' = first by row_index ASC. 'มากที่สุด' or 'สูงสุด' = sort by value DESC.\n"
            "6. For row_label and col_name, NEVER use strict '='. ALWAYS use LIKE '%keyword%' because data often has prefixes like '15. '.\n"
            "7. Return ONLY the SQL query, no explanation.\n"
            "8. For Thai text matching, ALWAYS break long sentences into keywords and join them with `AND` (e.g., `col_value LIKE '%บัตรเครดิต%' AND col_value LIKE '%สินเชื่อ%'`). NEVER use `OR` for phrase chunking, as it will match wrong tables.\n"
            "9. NEVER use `ORDER BY CAST(REPLACE(col_value...` unless you ALSO filter by `col_name` that contains a numeric value (e.g., `col_name LIKE '%จำนวนหุ้น%'`).\n"
            "10. EAV DATA RULE: To find the share count ('จำนวนหุ้น') of companies matching a specific string like 'บัตรเครดิต', YOU MUST USE A SUBQUERY: `col_name LIKE '%จำนวนหุ้น%' AND row_label IN (SELECT row_label FROM dim_table_rows WHERE col_value LIKE '%บัตรเครดิต%')`.\n"
            "11. NEVER use aggregate functions like COUNT(), MAX() or DISTINCT if the query also asks for names/details (e.g. 'มีกี่บริษัท และบริษัทใดบ้าง'). Just SELECT the raw rows (e.g. `SELECT row_label, col_name, col_value`) and let the Python Agent count them.\n"
            "12. NEVER cast strings to `INT` (e.g. `CAST(val AS INT)`). Financial numbers easily exceed 2 billion and will crash the database. ALWAYS cast to `DOUBLE`.\n\n"
            "EXAMPLES:\n\n"
            "Q: จำนวนหุ้นสามัญที่ธนาคารถือใน บริษัทหลักทรัพย์จัดการกองทุน มีกี่หุ้น?\n"
            "SQL: SELECT row_label, col_name, col_value FROM dim_table_rows WHERE table_name LIKE '%ลงทุน%' AND row_label LIKE '%บริษัทหลักทรัพย์จัดการกองทุน%' AND col_name LIKE '%จำนวนหุ้น%';\n\n"
            "Q: บริษัทที่ทำธุรกิจ บัตรเครดิตและสินเชื่อส่วนบุคคล มีกี่บริษัท บริษัทใดบ้าง และบริษัทใดมีหุ้นเยอะสุด?\n"
            "SQL: SELECT row_label, col_name, col_value FROM dim_table_rows WHERE table_name LIKE '%ลงทุน%' AND col_name LIKE '%จำนวนหุ้น%' AND row_label IN (SELECT row_label FROM dim_table_rows WHERE col_value LIKE '%บัตรเครดิต%' AND col_value LIKE '%สินเชื่อ%') ORDER BY CAST(REPLACE(col_value, ',', '') AS DOUBLE) DESC;\n\n"
            "Q: บริษัทที่บจก. (ธนาคาร) ถือหุ้นไม่ถึง 100% มีอะไรบ้าง?\n"
            "SQL: SELECT row_label, col_name, col_value FROM dim_table_rows WHERE table_name LIKE '%ลงทุน%' AND (col_name LIKE '%สัดส่วน%' OR col_name LIKE '%ร้อยละ%') AND CAST(REPLACE(REPLACE(col_value, ',', ''), '%', '') AS DOUBLE) < 100 ORDER BY row_index;\n\n"
            "Q: การลงทุนของธนาคารในบริษัทอื่น มีบริษัทอะไรบ้าง 2 อันดับแรก?\n"
            "SQL: SELECT DISTINCT row_label, col_name, col_value FROM dim_table_rows WHERE table_name LIKE '%ลงทุน%' AND row_index < 2 ORDER BY row_index, col_name;\n\n"
            "Q: สินทรัพย์รวมปี 2567 เท่าไร?\n"
            "SQL: SELECT row_label, raw_value, unit FROM fact_financial_metrics WHERE row_label LIKE '%สินทรัพย์รวม%' AND metric_year = '2567';\n\n"
            f"Q: {question}\n"
            "SQL:"
        )


        try:
            async with httpx.AsyncClient(timeout=120.0, limits=HTTP_LIMITS) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_HOST}/api/generate",
                    json={
                        "model": settings.OLLAMA_LLM_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.1, "num_predict": 500},
                    },
                )
                resp.raise_for_status()
                sql = resp.json().get("response", "").strip()

                # Clean markdown fences
                if sql.startswith("```"):
                    sql = sql.split("```")[1]
                    if sql.startswith("sql"):
                        sql = sql[3:]
                    sql = sql.strip()

                return sql
        except Exception as exc:
            logger.warning("SQL generation failed: %s", exc)
            return ""

    @staticmethod
    def _format_results(result: Dict[str, Any]) -> str:
        rows = result.get("rows", [])
        if not rows:
            return "ไม่พบข้อมูลที่ตรงกับคำถาม"

        lines = []
        for row in rows[:50]:
            parts = [f"{k}={v}" for k, v in row.items()]
            lines.append(", ".join(parts))
        return "\n".join(lines)

    @staticmethod
    def _format_lookup_results(result: Dict[str, Any]) -> str:
        """Format grouped lookup table results for the agent."""
        grouped = result.get("grouped", {})
        if not grouped:
            return "ไม่พบข้อมูลที่ตรงกับคำถาม"

        lines = []
        for label, cols in grouped.items():
            lines.append(f"{label}")
            for col_name, col_value in cols.items():
                lines.append(f"  - {col_name}: {col_value}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. Vector Search Tool — queries pgvector
# ---------------------------------------------------------------------------

class VectorSearchTool:
    """Semantic search over document chunks using pgvector."""

    name = "vector_search"
    description = (
        "Search documents by meaning. Use for explanations, concepts, "
        "summaries, policies, strategies, or qualitative information."
    )

    async def execute(
        self,
        query: str,
        session: Any = None,
        top_k: int = 5,
    ) -> ToolResult:
        if session is None:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="No database session available",
            )

        from backend.services.rag import vector_search

        results = await vector_search(query, session, top_k=top_k)

        if not results:
            return ToolResult(
                tool_name=self.name,
                success=True,
                summary="ไม่พบเอกสารที่เกี่ยวข้อง",
                data={"chunks": []},
            )

        summary_parts = []
        chunks_data = []
        for r in results:
            text = (r.get("text") or "")[:600]
            source = r.get("source_kind", "semantic")
            sim = r.get("similarity", 0)
            summary_parts.append(
                f"[{r.get('filename', '?')}, chunk {r.get('chunk_index', '?')}, "
                f"source={source}, sim={sim:.2f}]\n{text}"
            )
            chunks_data.append({
                "filename": r.get("filename"),
                "chunk_index": r.get("chunk_index"),
                "similarity": sim,
                "source_kind": source,
                "text": text,
                "summary": r.get("summary", ""),
            })

        return ToolResult(
            tool_name=self.name,
            success=True,
            summary="\n\n".join(summary_parts),
            data={"chunks": chunks_data},
        )


# ---------------------------------------------------------------------------
# 3. Multi-hop Reasoning Tool
# ---------------------------------------------------------------------------

class MultiHopTool:
    """Decompose complex questions into sub-queries and synthesise results."""

    name = "multi_hop"
    description = (
        "Break a complex question into 2-3 simpler sub-questions, "
        "gather data from SQL and/or Vector Search, then combine. "
        "Use when a question requires cross-referencing multiple data points."
    )

    def __init__(self) -> None:
        self._sql_tool = SQLTool()
        self._vector_tool = VectorSearchTool()

    async def execute(
        self,
        question: str,
        session: Any = None,
    ) -> ToolResult:
        # Step 1: Decompose the question
        sub_questions = await self._decompose(question)
        if not sub_questions:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="ไม่สามารถแตกคำถามย่อยได้",
            )

        # Step 2: Answer each sub-question
        sub_results: List[Dict[str, Any]] = []
        for sq in sub_questions:
            sq_text = sq.get("question", "")
            sq_tool = sq.get("tool", "sql_query")

            if sq_tool == "vector_search":
                result = await self._vector_tool.execute(sq_text, session=session)
            else:
                result = await self._sql_tool.execute(sq_text)

            sub_results.append({
                "question": sq_text,
                "tool": sq_tool,
                "success": result.success,
                "summary": result.summary,
            })

        # Step 3: Synthesise
        combined_context = "\n\n".join(
            f"Sub-Q: {sr['question']}\nAnswer: {sr['summary']}"
            for sr in sub_results
        )

        return ToolResult(
            tool_name=self.name,
            success=True,
            summary=combined_context,
            data={"sub_results": sub_results},
        )

    async def _decompose(self, question: str) -> List[Dict[str, str]]:
        prompt = (
            "You are a Thai financial data analyst. "
            "Break the following complex question into 2-3 simpler sub-questions.\n"
            "For each sub-question, specify which tool to use:\n"
            "- 'sql_query' for numbers, statistics, comparisons\n"
            "- 'vector_search' for concepts, explanations, policies\n\n"
            f"Question: {question}\n\n"
            "Return JSON array ONLY, no explanation:\n"
            '[{"question": "...", "tool": "sql_query"}, ...]\n'
            "JSON:"
        )

        try:
            async with httpx.AsyncClient(timeout=120.0, limits=HTTP_LIMITS) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_HOST}/api/generate",
                    json={
                        "model": settings.OLLAMA_LLM_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.1, "num_predict": 500},
                    },
                )
                resp.raise_for_status()
                raw = resp.json().get("response", "").strip()

                # Extract JSON from response
                match = re.search(r"\[.*\]", raw, re.DOTALL)
                if match:
                    return json.loads(match.group())
                return json.loads(raw)
        except Exception as exc:
            logger.warning("Decomposition failed: %s", exc)
            # Fallback: use original question as single sub-query
            return [{"question": question, "tool": "sql_query"}]


# ---------------------------------------------------------------------------
# 4. Web Search Tool
# ---------------------------------------------------------------------------

class WebSearchTool:
    """Search the web for up-to-date information."""

    name = "tavily_search"
    description = (
        "Search the internet for current events, news, or general knowledge "
        "that might not be in the internal database. Use as a fallback "
        "when other tools don't have the answer."
    )

    async def execute(self, query: str, session: Any = None) -> ToolResult:
        if not settings.TAVILY_API_KEY:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="TAVILY_API_KEY is not configured.",
            )
            
        try:
            from tavily import TavilyClient
            # Synchronous call in async wrapper for simplicity, or use async if supported
            client = TavilyClient(api_key=settings.TAVILY_API_KEY)
            response = client.search(query=query, search_depth="basic", max_results=3)
            
            summary_parts = []
            results_data = []
            for r in response.get("results", []):
                summary_parts.append(f"[{r.get('title', 'Unknown')}]\n{r.get('content', '')}")
                results_data.append(r)
                
            summary = "\n\n".join(summary_parts)
            if not summary:
                summary = "ไม่พบข้อมูลจาก Web Search"
                
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={"results": results_data},
                summary=summary,
            )
        except Exception as exc:
            logger.error("Web search failed: %s", exc)
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc)
            )


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

ALL_TOOLS = {
    "sql_query": SQLTool(),
    "vector_search": VectorSearchTool(),
    "multi_hop": MultiHopTool(),
    "tavily_search": WebSearchTool(),
}


def get_tools_description() -> str:
    """Return a description of all available tools for the agent prompt."""
    lines = []
    for name, tool in ALL_TOOLS.items():
        lines.append(f"- **{name}**: {tool.description}")
    return "\n".join(lines)
