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
            f"Question: {question}\n\n"
            "Rules:\n"
            "- Return ONLY the SQL query, no explanation\n"
            "- Use numeric_value for math/comparisons, raw_value for display\n"
            "- Use LIKE for fuzzy Thai label matching\n"
            "- DuckDB uses standard SQL (no ->> operator, use standard column access)\n"
            "SQL:"
        )

        try:
            async with httpx.AsyncClient(timeout=60.0, limits=HTTP_LIMITS) as client:
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
        for row in rows[:10]:
            parts = [f"{k}={v}" for k, v in row.items()]
            lines.append(", ".join(parts))
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
            async with httpx.AsyncClient(timeout=60.0, limits=HTTP_LIMITS) as client:
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
# Tool registry
# ---------------------------------------------------------------------------

ALL_TOOLS = {
    "sql_query": SQLTool(),
    "vector_search": VectorSearchTool(),
    "multi_hop": MultiHopTool(),
}


def get_tools_description() -> str:
    """Return a description of all available tools for the agent prompt."""
    lines = []
    for name, tool in ALL_TOOLS.items():
        lines.append(f"- **{name}**: {tool.description}")
    return "\n".join(lines)
