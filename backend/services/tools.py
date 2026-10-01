"""Agent Tools for the Agentic RAG system.

Five tools the ReAct agent can invoke:
1. **SQLTool**           – queries DuckDB ``fact_financial_metrics``
2. **VectorSearchTool**  – semantic search via pgvector
3. **MultiHopTool**      – decomposes complex questions into sub-queries
4. **WebSearchTool**     – Tavily web search fallback
5. **GraphSearchTool**   – entity/relationship search via Hyper-Extract KA
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from backend.config import get_settings, ollama_extra_fields
from backend.services.duckdb_warehouse import (
    execute_sql, get_schema_description, resolve_result_evidence, warehouse_capabilities,
)
from backend.services.llm import generate as llm_generate
from backend.services.retrieval_rank import normalize_search_text

settings = get_settings()
logger = logging.getLogger(__name__)

HTTP_LIMITS = httpx.Limits(max_connections=4, max_keepalive_connections=2)

_SELECT_START_RE = re.compile(r"\b(SELECT|WITH)\b", re.IGNORECASE)


# Cap per-term occurrences so a stop-word-ish token on a long page cannot make
# the window search quadratic in the page length.
_MAX_TERM_HITS = 40

# Shorter verbatim spans than this match generic Thai prose and anchor nothing.
_MIN_SPAN = 10


def _question_spans(question: str, text: str, limit: int = 5) -> List[str]:
    """Longest verbatim substrings of *question* that occur in *text*.

    The same signal ``SQLTool._exact_label_rows`` uses on table rows: a phrase
    the question spells out and the page repeats verbatim points at the answer
    far more reliably than the frequency of its individual words. Whitespace is
    never normalised — in this corpus "รวมในประเทศและ ต่างประเทศ" and
    "รวมในประเทศและต่างประเทศ" are different things.
    """
    q = str(question or "")
    if not q or not text:
        return []
    found: List[str] = []
    for start in range(len(q)):
        lo, hi, best = _MIN_SPAN, len(q) - start, None
        while lo <= hi:                       # longest span that still occurs
            mid = (lo + hi) // 2
            if q[start:start + mid] in text:
                best, lo = mid, mid + 1
            else:
                hi = mid - 1
        if best:
            found.append(q[start:start + best])
    found.sort(key=len, reverse=True)
    keep: List[str] = []
    for span in found:
        if not any(span in k for k in keep):  # drop spans inside a longer one
            keep.append(span)
    return keep[:limit]


def _focus_excerpt(
    text: str,
    terms: List[str],
    budget: int,
    head: int = 400,
    question: str = "",
) -> str:
    """Excerpt that keeps the region where the query terms actually appear.

    Corpus chunks are whole OCR pages (3-5k chars) and the answer to a specific
    question often sits deep inside one — measured positions for real failures
    were 1376, 2077 and 2206. A head-only cut drops those silently, so the model
    is handed the right chunk and still reports "ไม่พบข้อมูล". Window around the
    densest cluster of term hits instead, always keeping a head slice so the
    chunk's topic survives.
    """
    text = text or ""
    if len(text) <= budget:
        return text
    raw_low = text.lower()
    low = normalize_search_text(raw_low)
    # Search normalized Thai glyphs, but return the original evidence verbatim.
    raw_positions = list(range(len(low)))
    if low != raw_low:
        from difflib import SequenceMatcher
        for tag, i, j, a, b in SequenceMatcher(None, low, raw_low, autojunk=False).get_opcodes():
            if tag == "equal":
                raw_positions[i:j] = range(a, b)
            elif i < j:
                raw_positions[i:j] = [a] * (j - i)
    # Every occurrence, not just the first. A page repeats its query terms, so
    # scoring on first hits alone pinned the window near the top of the chunk
    # and the answer further down was dropped (measured on ids 439/498/507).
    hits: List[tuple] = []
    for idx, term in enumerate(dict.fromkeys(t.lower() for t in terms if t)):
        if not term:
            continue
        needle, at, found = normalize_search_text(term.lower()), 0, 0
        if not needle:
            continue
        while found < _MAX_TERM_HITS:
            p = low.find(needle, at)
            if p < 0:
                break
            hits.append((raw_positions[p], idx))
            at, found = p + max(1, len(needle)), found + 1
    anchors: List[int] = []
    for span in _question_spans(question, text):
        at = 0
        for _ in range(_MAX_TERM_HITS):
            p = text.find(span, at)
            if p < 0:
                break
            anchors.append(p)
            at = p + max(1, len(span))
    if not hits and not anchors:
        return text[:budget]
    hits.sort()
    win = max(budget - head, 200)
    # Rank a window by the verbatim question spans it covers first, then by how
    # many *distinct* query terms — so a window is not won by one common word
    # repeating; total hits only breaks ties.
    candidates = sorted({p for p, _ in hits} | set(anchors)) or [0]
    best_start, best_key = candidates[0], (-1, -1, -1)
    for p in candidates:
        covered = sum(1 for a in anchors if p <= a < p + win)
        seen, total = set(), 0
        for q, term_idx in hits:
            if q < p:
                continue
            if q >= p + win:
                break
            seen.add(term_idx)
            total += 1
        key = (covered, len(seen), total)
        if key > best_key:
            best_key, best_start = key, p
    # Keep the row label immediately before a matched year/value too.
    start = max(0, best_start - 80)
    if start + win > len(text):
        start = max(0, len(text) - win)
    if start <= head:
        return text[: start + win]
    return text[:head].rstrip() + " … " + text[start : start + win]


def _clean_sql(raw: str) -> str:
    """Extract a runnable SQL statement from a raw LLM reply.

    Handles the common local-model quirks: markdown ```sql fences, an echoed
    ``SQL:`` label (the prompt ends with ``SQL:`` and the model repeats it),
    and any leading prose. We take everything from the first SELECT/WITH.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        # keep the fenced body
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else parts[0]
        if text[:3].lower() == "sql":
            text = text[3:]
        text = text.strip()
    # Drop everything before the first SELECT/WITH (kills "SQL:" and any preamble).
    m = _SELECT_START_RE.search(text)
    if m:
        text = text[m.start():]
    # Trim a trailing code fence / stray backticks and whitespace.
    text = text.replace("```", "").strip()
    return text


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

        capabilities = warehouse_capabilities()
        if not (capabilities["year_cells"] or capabilities["lookup_cells"]):
            return ToolResult(tool_name=self.name, success=False,
                              error="No structured table cells are available yet")

        from backend.services.duckdb_warehouse import exact_measure_cells
        exact = exact_measure_cells(question)
        if exact:
            summary = self._format_results(exact, question)
            summary += "\nExact source cells (use these units): " + json.dumps(exact['evidence'], ensure_ascii=False)
            summary += "\nOCR-extracted values are not visually verified against the PDF."
            return ToolResult(tool_name=self.name, success=True, data=exact, summary=summary)

        # Compound headers require row AND column selection. Let the model
        # select only existing candidate IDs; it cannot invent values or lose
        # provenance by projecting away identity columns in generated SQL.
        if not capabilities['year_cells'] and re.search(r'(?<!\d)(?:25|20)\d{2}(?!\d)', question):
            return await self._select_year_cells(question)

        schema_desc = get_schema_description(question)
        feedback = ""
        evidence = []
        sql = ""
        result = {}
        # One original SELECT and at most one repair; missing identity is a
        # failure just like invalid SQL. Never return an untraceable number.
        for attempt in range(2):
            sql = await self._generate_sql(question, schema_desc, error_feedback=feedback)
            if not sql:
                return ToolResult(tool_name=self.name, success=False, error="ไม่สามารถสร้าง SQL ได้")
            result = execute_sql(sql)
            if result.get("error"):
                feedback = f"SQL error: {result['error']}\nFailed SQL: {sql}"
            elif not result.get("row_count"):
                feedback = (f"0 rows from: {sql}. Match stored row labels, not a guessed combined phrase. "
                            "Relax descriptive qualifiers but KEEP the requested document, year, unit and measure. "
                            "For a total, inspect the relevant table's row labeled รวม. Do not switch documents.")
            else:
                evidence = resolve_result_evidence(result.get("rows", []))
                if evidence:
                    break
                feedback = (f"Rows from {sql} cannot be traced to a PDF cell. Return original "
                            "document_id,table_name,row_label,col_name,col_value,unit from dim_table_rows "
                            "or document_id,table_name,row_label,metric_year,raw_value,unit from fact_financial_metrics. "
                            "Do not project aliases, aggregate or use the pivot view.")
        if not evidence:
            return ToolResult(tool_name=self.name, success=False,
                              error=result.get("error") or "ไม่พบข้อมูลตารางพร้อมหลักฐานหน้าเอกสารที่ตรงกับคำถาม",
                              data={"sql":sql, **result, "evidence":[]})
        summary = self._format_results(result, question)
        if evidence:
            pages = []
            for item in evidence[:5]:
                location = f"{item['filename']} PDF page {item['page'] or 'unknown'}"
                if location not in pages:
                    pages.append(location)
            summary += "\nSources: " + "; ".join(pages)
            summary += "\nExact source cells (use these units): " + json.dumps(evidence, ensure_ascii=False)
        summary += "\nOCR-extracted values are not visually verified against the PDF."
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"sql": sql, **result, "evidence": evidence},
            summary=summary,
        )

    async def _select_year_cells(self, question: str) -> ToolResult:
        from backend.services.duckdb_warehouse import candidate_year_cells
        candidates=candidate_year_cells(question)
        if not candidates:
            return ToolResult(tool_name=self.name,success=False,error='ไม่พบเซลล์ตรงปีและหน่วยที่ถาม')
        groups={}
        for c in candidates:
            key=c['table_name']
            if key not in groups:
                groups[key]={'table_id':len(groups),'name':key,'rows_in_order':c['table_rows_in_order']}
        cells=[{'id':i,'table_id':groups[c['table_name']]['table_id'],
                **{k:c[k] for k in ('filename','row_label','col_name','col_value','unit')}} for i,c in enumerate(candidates)]
        prompt=(
            'Select the original PDF table cells that directly answer the Thai question. Return JSON only: {"cell_ids":[...]} or {"cell_ids":[]} if unavailable.\n'
            'A question may combine a section heading with a component row, or a financial measure in the COLUMN with a maturity/credit-stage ROW. '
            'Use the most specific component asked for, never the parent total or a similarly named measure. '
            'For maturity ranges interpret >, ≤ and Thai wording exactly. For total choose รวม within the right column group. '
            'Match company, year, column measure, unit and statement context together. '
            'Comparisons require both years of the same measure. Do not select irrelevant nearby cells.\n'
            f'Question: {question}\nTables: {json.dumps(list(groups.values()),ensure_ascii=False)}\n'
            f'Candidate cells: {json.dumps(cells,ensure_ascii=False)}\nJSON:')
        raw=await llm_generate(prompt,temperature=0,max_tokens=180)
        try:
            match=re.search(r'\{.*\}',raw,re.DOTALL)
            ids=json.loads(match.group() if match else raw).get('cell_ids',[])
            # JSON models sometimes quote integer IDs. Accept only canonical
            # nonnegative decimal strings, then apply the same bounds check.
            if isinstance(ids, list):
                ids = [int(i) if isinstance(i, str) and re.fullmatch(r'0|[1-9][0-9]{0,5}', i) else i
                       for i in ids]
            if not isinstance(ids,list) or len(ids)>12 or any(type(i) is not int or i<0 or i>=len(candidates) for i in ids):
                raise ValueError('Invalid candidate IDs')
        except (ValueError,TypeError,AttributeError):
            return ToolResult(tool_name=self.name,success=False,error='ไม่สามารถเลือกเซลล์หลักฐานได้')
        rows=[{k:v for k,v in candidates[i].items() if k!='table_rows_in_order'} for i in dict.fromkeys(ids)]
        evidence=resolve_result_evidence(rows)
        if not evidence:
            return ToolResult(tool_name=self.name,success=False,error='ไม่พบเซลล์ที่ตอบคำถามพร้อมหน้าอ้างอิง')
        data={'sql':'-- Parameterized stored-cell candidate selection','rows':rows,'row_count':len(rows),
              'evidence':evidence,'selected_cell_ids':ids,'candidate_count':len(candidates)}
        summary='Exact source cells (machine extracted, not visually verified): '+json.dumps(evidence,ensure_ascii=False)
        return ToolResult(tool_name=self.name,success=True,data=data,summary=summary)

    async def _generate_sql(
        self,
        question: str,
        schema_desc: str,
        error_feedback: str = "",
    ) -> str:
        caps = warehouse_capabilities()
        prompt = (
            "Generate one DuckDB SELECT query, SQL only, using this actual schema/data.\n"
            f"{schema_desc}\n"
            "Rules:\n"
            "- document_id is INTEGER. Filter a named PDF via dim_documents.filename using a subquery or join. Never compare document_id to a filename.\n"
            "- Choose a POPULATED cell table. dim_table_rows includes financial years inside compound col_name headers. Match year AND measure/group in col_name.\n"
            "- Return document_id, table_name, row_label, metric_year, raw_value, unit for fact_financial_metrics; or document_id, table_name, row_label, col_name, col_value, unit for dim_table_rows. Preserve cell identity.\n"
            "- Never join the two cell tables. Never invent tables or columns. No web/file functions.\n"
            "- A cell's unit overrides the table title. EPS is baht; percentage columns and ratios use %. When asking for money exclude percentage columns.\n"
            "- Select the exact measure, year, statement section and entity asked for. Use LIKE for Thai phrases and rank exact labels first; do not mix total and component rows.\n"
            "- Questions combine section headings, row labels and column groups. Match those separately. A measure under a section need not repeat that section in its row_label. Use the STORED labels, not the entire question phrase.\n"
            "- Parenthesized sections may be in table_name; rank matching sections ahead of other ones.\n"
            "- For totals match row_label 'รวม' only in the relevant table/column group. For credit stages or maturity ranges select the precise row.\n"
            "- For a comparison retrieve BOTH years from the SAME row and measure. Do not calculate in SQL: return source cells.\n"
            "- Only sort numeric_value/col_value_num for highest/lowest; use row_index for first rows. Keep LIMIT 12 for comparisons, 6 otherwise.\n"
            "- If the requested value is not in stored table cells, returning no rows is correct. Prose search can follow.\n"
            f"Populated capabilities: {caps}\n"
            f"Previous attempt feedback: {error_feedback}\nQuestion: {question}\nSQL:"
        )
        if not caps["year_cells"]:
            prompt += "\nIMPORTANT: fact_financial_metrics is EMPTY. Use dim_table_rows for financial figures; the year is part of col_name."
        prompt += "\nFor answers needing citations NEVER select from v_table_rows_wide: use original cell rows with document_id/table_name/row_label/col_name/col_value/unit intact."
        if not caps["wide_view"]:
            prompt += "\nIMPORTANT: v_table_rows_wide DOES NOT EXIST."

        try:
            sql = await llm_generate(prompt, temperature=0.1, max_tokens=500)
            cleaned = _clean_sql(sql)
            if not warehouse_capabilities()["wide_view"] and re.search(
                r"\bv_table_rows_wide\b", cleaned, re.IGNORECASE
            ):
                return ""
            return cleaned
        except Exception as exc:
            logger.warning("SQL generation failed: %s", exc)
            return ""

    @staticmethod
    def _exact_label_rows(rows: List[Dict[str, Any]], question: str) -> set:
        """Indices of rows whose ``row_label`` appears verbatim in the question.

        ``LIKE '%keyword%'`` routinely returns the line item that was asked for
        *and* near-miss ones, and the answering LLM has been seen picking the near
        miss even when the SQL already ranked the right row first — asked for
        'ต่างประเทศ' it answered 76,289 from 'รวมต่างประเทศ' while the correct
        19,575 sat in row 1. Row order alone clearly does not carry, so mark the
        row the question actually names and let the marker carry it instead.

        Whitespace is significant here and must NOT be normalised away:
        'รวมในประเทศและ ต่างประเทศ' and 'รวมในประเทศและต่างประเทศ' are different
        rows on different statements with different values, and only one of the two
        is spelled the way the question spells it.

        A marker on every row says nothing, so in that case mark none — that keeps
        the annotation silent on genuinely ambiguous lookups ('อื่น ๆ' matches 29
        rows, all of them equally).
        """
        if not question:
            return set()
        hits = set()
        for i, row in enumerate(rows):
            label = str(row.get("row_label", "") or "").strip()
            if label and label in question:
                hits.add(i)
        return set() if len(hits) == len(rows) else hits

    @staticmethod
    def _format_results(result: Dict[str, Any], question: str = "") -> str:
        rows = result.get("rows", [])
        if not rows:
            return "ไม่พบข้อมูลที่ตรงกับคำถาม"

        shown = rows[:50]
        exact = SQLTool._exact_label_rows(shown, question)

        lines = []
        for i, row in enumerate(shown):
            parts = [f"{k}={v}" for k, v in row.items()]
            line = ", ".join(parts)
            if i in exact:
                line += "   <== ชื่อรายการตรงกับคำถามพอดี"
            lines.append(line)

        body = "\n".join(lines)
        if exact:
            body = (
                "(แถวที่มี <== คือแถวที่ row_label ตรงกับชื่อรายการในคำถามพอดี "
                "ให้ใช้แถวนั้นตอบ ห้ามหยิบแถวอื่นที่ชื่อใกล้เคียงหรือมีคำนำหน้าเพิ่ม)\n"
                + body
            )
        return body

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
        top_k: int | None = None,
    ) -> ToolResult:
        if session is None:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error="No database session available",
            )

        from backend.services.rag import vector_search, _extract_keyword_terms

        if top_k is None:
            top_k = getattr(settings, "VECTOR_TOP_K", 10)
        results = await vector_search(query, session, top_k=top_k)
        focus_terms = _extract_keyword_terms(query)
        budget = getattr(settings, "VECTOR_CHUNK_CHARS", 2500)

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
            text = _focus_excerpt(r.get("text") or "", focus_terms, budget, question=query)
            source = r.get("source_kind", "semantic")
            sim = r.get("similarity", 0)
            summary_parts.append(
                f"[{r.get('filename', '?')}, PDF page {r.get('page') or 'unknown'}, "
                f"chunk {r.get('chunk_index', '?')}, source={source}, sim={sim:.2f}; "
                "OCR evidence is not visually verified]\n"
                f"{text}"
            )
            chunks_data.append({
                "document_id": r.get("document_id"),
                "filename": r.get("filename"),
                "page": r.get("page"),
                "table_name": r.get("table_name"),
                "quality_status": r.get("quality_status"),
                "evidence_status": r.get("evidence_status"),
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
        seen: set[tuple[str, str]] = set()
        for sq in sub_questions:
            sq_text = str(sq.get("question") or "").strip()
            sq_tool = sq.get("tool", "sql_query")
            if not sq_text or sq_tool not in {"sql_query", "vector_search"}:
                continue
            key = (sq_tool, re.sub(r"\s+", "", sq_text).casefold())
            if key in seen:
                continue
            seen.add(key)

            if sq_tool == "vector_search":
                result = await self._vector_tool.execute(sq_text, session=session)
            else:
                result = await self._sql_tool.execute(sq_text)

            sub_results.append({
                "question": sq_text,
                "tool": sq_tool,
                "success": result.success,
                "summary": result.summary,
                "data": result.data,
            })
            if len(sub_results) >= 2:
                break

        if not sub_results:
            return ToolResult(tool_name=self.name, success=False,
                              error="No usable sub-question was produced")

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
            "Break the following complex question into at most 2 simpler sub-questions.\n"
            "For each sub-question, specify which tool to use:\n"
            "- 'sql_query' for numbers, statistics, comparisons\n"
            "- 'vector_search' for concepts, explanations, policies\n\n"
            f"Question: {question}\n\n"
            "Return JSON array ONLY, no explanation:\n"
            '[{"question": "...", "tool": "sql_query"}, ...]\n'
            "JSON:"
        )

        try:
            raw = await llm_generate(prompt, temperature=0.1, max_tokens=500)

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
        if settings.OFFLINE_MODE:
            return ToolResult(tool_name=self.name, success=False,
                              error="Web search is disabled in OFFLINE_MODE")
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
# 5. Graph Search Tool — queries Hyper-Extract Knowledge Abstracts
# ---------------------------------------------------------------------------

class GraphSearchTool:
    """Search entity-relationship knowledge graphs built by Hyper-Extract."""

    name = "graph_search"
    description = (
        "Search the knowledge graph for entity relationships, company structures, "
        "officer roles, ownership links, or connections between organisations. "
        "Use when the question asks 'who', 'which company', 'what is the relationship "
        "between', 'who owns', or requires cross-entity linking that vector search cannot answer."
    )

    async def execute(self, query: str, session: Any = None) -> ToolResult:
        """Search all built Knowledge Abstracts for the given query."""
        try:
            from backend.services.graph_service import search_knowledge_graph
            result = search_knowledge_graph(query)

            if not result.get("success", True):
                return ToolResult(
                    tool_name=self.name,
                    success=False,
                    error=result.get("error", "Graph search failed"),
                )

            return ToolResult(
                tool_name=self.name,
                success=True,
                summary=result.get("summary", "ไม่พบข้อมูลในกราฟความรู้"),
                data={"results": result.get("results", [])},
            )
        except Exception as exc:
            logger.error("GraphSearchTool failed: %s", exc)
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

ALL_TOOLS = {
    "sql_query": SQLTool(),
    "vector_search": VectorSearchTool(),
    "multi_hop": MultiHopTool(),
    "tavily_search": WebSearchTool(),
    "graph_search": GraphSearchTool(),
}


def get_tools_description() -> str:
    """Return a description of all available tools for the agent prompt."""
    lines = []
    for name, tool in ALL_TOOLS.items():
        lines.append(f"- **{name}**: {tool.description}")
    return "\n".join(lines)
