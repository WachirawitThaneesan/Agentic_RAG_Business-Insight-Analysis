"""Hybrid RAG engine: Vector Search + Text-to-SQL."""

import csv
import io
import json
import re
import httpx
from typing import List, Dict, Any, Optional
from sqlalchemy import text as sql_text, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from backend.config import get_settings
from backend.services.embedding import get_embedding
from backend.services.table_utils import rebuild_structured_tables
from backend.models import Chunk, Document, StructuredData

settings = get_settings()
HTTP_LIMITS = httpx.Limits(max_connections=4, max_keepalive_connections=2)


def _rows_to_csv(headers: List[str], rows: List[Dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(header, "") for header in headers])
    return buffer.getvalue().strip()


def _normalize_lookup_text(text: str) -> str:
    value = str(text or "")
    value = value.replace(" ", "")
    value = re.sub(r"[\n\r\t,:;(){}\[\]\"'`“”‘’%\-_/]", "", value)
    return value.strip().lower()


def _extract_years(question: str) -> List[str]:
    return re.findall(r"\b(25\d{2}|20\d{2})\b", question or "")


_KEYWORD_STOPWORDS = {
    "อะไร", "เท่าไร", "เท่าไหร่", "เท่า", "ใด", "บ้าง", "ของ", "ใน", "ปี",
    "และ", "กับ", "ที่", "เป็น", "ได้", "หรือ", "มี", "จาก", "ให้", "ว่า",
    "จะ", "ควร", "ทั้งหมด", "กี่", "คือ", "ด้าน", "โดย", "ซึ่ง", "นี้", "นั้น",
    "อยู่", "ทำ", "แล้ว", "การ", "ตาม", "ต่อ", "เมื่อ", "ราย",
    # domain-ubiquitous terms — they appear in almost every chunk of this corpus
    # so they carry no discriminative signal and only add noise to keyword search.
    "กรุงศรี", "ธนาคาร", "บริษัท", "จำกัด", "มหาชน", "รายงาน", "ประจำปี",
    "กรุ๊ป", "อยุธยา", "ประเทศ", "ไทย", "กลุ่ม", "กิจการ",
    "how", "what", "which", "does", "did", "the", "for", "from", "and", "of",
    "is", "are", "in", "to", "a", "an",
}


def _thai_tokenize(text: str) -> List[str]:
    """Word-segment mixed Thai/English text.

    Thai is written without spaces, so a naive ``[ก-๙]+`` regex yields one giant
    token (e.g. 'คณะกรรมการทรัพยากรบุคคลของกรุงศรี') that matches no chunk. We
    use pythainlp to split it into real words ('คณะกรรมการ', 'ทรัพยากรบุคคล', …)
    which makes keyword search actually work. Falls back to the old regex if
    pythainlp is unavailable.
    """
    try:
        from pythainlp.tokenize import word_tokenize
        return word_tokenize(text, engine="newmm", keep_whitespace=False)
    except Exception:
        return re.findall(r"[A-Za-z]{2,}|\d{4}|[ก-๙]{2,}", text)


def _extract_keyword_terms(question: str) -> List[str]:
    raw_question = str(question or "").strip()
    if not raw_question:
        return []

    tokens = _thai_tokenize(raw_question)

    seen = set()
    terms: List[str] = []
    for token in tokens:
        normalized = token.strip()
        if not normalized:
            continue
        normalized_lower = normalized.lower()
        if normalized_lower in _KEYWORD_STOPWORDS:
            continue
        # keep 4-digit years, otherwise require >=2 alnum/thai chars
        if not re.fullmatch(r"(?:25|20)\d{2}", normalized):
            if len(normalized) < 2 or not re.search(r"[A-Za-z0-9ก-๙]", normalized):
                continue
        if normalized_lower in seen:
            continue
        seen.add(normalized_lower)
        terms.append(normalized)
    return terms


def _is_year_term(term: str) -> bool:
    return bool(re.fullmatch(r"25\d{2}|20\d{2}", str(term or "")))


def _is_acronym_term(term: str) -> bool:
    value = str(term or "").strip()
    return bool(re.fullmatch(r"[A-Z]{2,6}", value))


def _row_label_candidates(row_data: Dict[str, Any]) -> List[tuple[str, str]]:
    candidates: List[tuple[str, str]] = []
    for key, value in (row_data or {}).items():
        text = str(value or "").strip()
        if not text:
            continue
        if re.fullmatch(r"25\d{2}|20\d{2}|column_\d+", key or ""):
            continue
        candidates.append((key, text))
    return candidates


def _parse_numeric_value(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = text.replace(",", "").replace("%", "").replace("(", "").replace(")", "").strip()
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return -number if negative else number


def _format_numeric_delta(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}"


def _infer_value_unit(label_value: str, question: str, table_name: str = "") -> str:
    text = f"{label_value} {question} {table_name}".lower()
    if "ต่อหุ้น" in text:
        return "บาท"
    if any(token in text for token in ["roe", "roa", "อัตราส่วน", "ค่าใช้จ่ายต่อรายได้", "เงินให้สินเชื่อด้อยคุณภาพต่อเงินให้สินเชื่อรวม", "เงินให้สินเชื่อต่อเงินรับฝาก"]):
        return "%"
    if "ล้านบาท" in text:
        return "ล้านบาท"
    return ""


def _apply_unit(raw_value: str, unit: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return value
    if unit == "%" and not value.endswith("%"):
        return f"{value}%"
    if unit == "บาท" and not value.endswith("บาท"):
        return f"{value} บาท"
    if unit == "ล้านบาท" and not value.endswith("ล้านบาท"):
        return f"{value} ล้านบาท"
    return value


async def _load_grouped_structured_tables(session: AsyncSession) -> Dict[tuple[int, str], Dict[str, Any]]:
    rows_result = await session.execute(
        select(
            StructuredData.document_id,
            StructuredData.table_name,
            StructuredData.headers,
            StructuredData.row_data,
            StructuredData.row_index,
        )
    )
    db_rows = rows_result.all()

    grouped_tables: Dict[tuple[int, str], Dict[str, Any]] = {}
    for document_id, table_name, headers, row_data, row_index in db_rows:
        key = (document_id, table_name or "unknown_table")
        bucket = grouped_tables.setdefault(
            key,
            {"headers": headers or [], "rows": []},
        )
        bucket["rows"].append(row_data or {})
    return grouped_tables


async def _find_best_structured_row(question: str, session: AsyncSession) -> Optional[Dict[str, Any]]:
    normalized_question = _normalize_lookup_text(question)
    question_terms = [term for term in _extract_keyword_terms(question) if not _is_year_term(term)]
    grouped_tables = await _load_grouped_structured_tables(session)

    best_match = None
    best_score = -1

    for (document_id, base_table_name), payload in grouped_tables.items():
        logical_tables = rebuild_structured_tables(base_table_name, payload["headers"], payload["rows"])
        for logical_table in logical_tables:
            headers = logical_table.get("headers", [])
            if not headers:
                continue
            label_key = headers[0]
            for row_index, row_values in enumerate(logical_table.get("rows", [])):
                row_data = {
                    header: row_values[col_index] if col_index < len(row_values) else ""
                    for col_index, header in enumerate(headers)
                }
                label_value = str(row_data.get(label_key, "")).strip()
                normalized_label = _normalize_lookup_text(label_value)
                if not normalized_label:
                    continue

                score = 0
                if normalized_label in normalized_question:
                    score += len(normalized_label) + 100
                elif normalized_question in normalized_label:
                    score += len(normalized_question) + 50

                for term in question_terms:
                    normalized_term = _normalize_lookup_text(term)
                    if normalized_term and normalized_term in normalized_label:
                        score += max(10, len(term) * 3)

                if score <= 0:
                    continue

                year_headers = [header for header in headers if re.fullmatch(r"25\d{2}|20\d{2}", header or "")]
                if not year_headers:
                    continue

                # Require a minimum score of 40 to prevent weak matches (like just matching the word "ธนาคาร")
                if score > best_score and score >= 40:
                    best_score = score
                    best_match = {
                        "document_id": document_id,
                        "table_name": logical_table.get("table_name") or base_table_name,
                        "headers": headers,
                        "row_data": row_data,
                        "row_index": row_index,
                        "label_key": label_key,
                        "label_value": label_value,
                        "year_headers": year_headers,
                    }

    return best_match


async def try_direct_structured_answer(
    question: str,
    session: AsyncSession,
) -> Optional[Dict[str, Any]]:
    # FORCE Disable fast-path to enforce use of LLM Agent and SQL generation
    return None
    
    best_match = await _find_best_structured_row(question, session)
    question_text = str(question or "")

    if not best_match and "อัตราส่วนเงินกองทุนทั้งสิ้น" in question_text:
        grouped_tables = await _load_grouped_structured_tables(session)
        for (_, base_table_name), payload in grouped_tables.items():
            logical_tables = rebuild_structured_tables(base_table_name, payload["headers"], payload["rows"])
            for logical_table in logical_tables:
                headers = logical_table.get("headers", [])
                if not headers:
                    continue
                label_key = headers[0]
                for row_index, row_values in enumerate(logical_table.get("rows", [])):
                    row_data = {
                        header: row_values[col_index] if col_index < len(row_values) else ""
                        for col_index, header in enumerate(headers)
                    }
                    label_value = str(row_data.get(label_key, "")).strip()
                    if "อัตราส่วนเงินกองทุนทั้งสิ้น" in label_value:
                        best_match = {
                            "table_name": logical_table.get("table_name") or base_table_name,
                            "row_index": row_index,
                            "label_value": label_value,
                            "row_data": row_data,
                            "year_headers": [header for header in headers if re.fullmatch(r"25\d{2}|20\d{2}", header or "")],
                        }
                        break
                if best_match:
                    break
            if best_match:
                break

    if not best_match:
        return None

    row_data = best_match["row_data"]
    label_value = best_match["label_value"]
    year_headers = best_match["year_headers"]
    years = _extract_years(question_text)
    unit = _infer_value_unit(label_value, question_text, best_match.get("table_name", ""))

    if len(years) >= 2 and any(token in question_text for token in ["เปลี่ยนจาก", "ต่างจาก", "เปรียบเทียบ", "เพิ่มขึ้น", "ลดลง"]):
        target_year = years[0]
        base_year = years[1]
        target_raw = str(row_data.get(target_year, "")).strip()
        base_raw = str(row_data.get(base_year, "")).strip()
        target_num = _parse_numeric_value(target_raw)
        base_num = _parse_numeric_value(base_raw)
        if target_raw and base_raw and target_num is not None and base_num is not None:
            delta = target_num - base_num
            direction = "เพิ่มขึ้น" if delta > 0 else "ลดลง"
            unit_label = "จุดเปอร์เซ็นต์" if unit == "%" else "บาท"
            base_display = _apply_unit(base_raw, unit) if unit == "%" else base_raw
            target_display = _apply_unit(target_raw, unit) if unit == "%" else target_raw
            answer = (
                f"{label_value}ปี {target_year} {direction} {_format_numeric_delta(abs(delta))} {unit_label} "
                f"จาก {base_display} เหลือ {target_display}"
            )
            return {
                "answer": answer,
                "method": "direct_structured_fact",
                "sources": [
                    {
                        "type": "sql",
                        "table_name": best_match["table_name"],
                        "row_index": best_match["row_index"],
                        "row_label": label_value,
                        "row_count": 1,
                    }
                ],
                "sql_info": None,
            }

    if any(token in question_text for token in ["สูงสุด", "ต่ำสุด"]):
        numeric_years = []
        for year in year_headers:
            raw_value = str(row_data.get(year, "")).strip()
            numeric_value = _parse_numeric_value(raw_value)
            if numeric_value is None:
                continue
            numeric_years.append((year, raw_value, numeric_value))

        if numeric_years:
            if "สูงสุด" in question_text:
                best_year, best_raw, _ = max(numeric_years, key=lambda item: item[2])
            else:
                best_year, best_raw, _ = min(numeric_years, key=lambda item: item[2])
            answer = (
                f"ปี {best_year} ที่ {_apply_unit(best_raw, unit)}"
                if "สูงสุด" in question_text
                else f"ปี {best_year} ที่ {_apply_unit(best_raw, unit)}"
            )
            return {
                "answer": answer,
                "method": "direct_structured_fact",
                "sources": [
                    {
                        "type": "sql",
                        "table_name": best_match["table_name"],
                        "row_index": best_match["row_index"],
                        "row_label": label_value,
                        "row_count": 1,
                    }
                ],
                "sql_info": None,
            }

    if len(years) == 1 and years[0] in row_data and str(row_data.get(years[0], "")).strip():
        year = years[0]
        raw_value = str(row_data.get(year, "")).strip()
        answer = f"{label_value}ในปี {year} เท่ากับ {_apply_unit(raw_value, unit)}"
        return {
            "answer": answer,
            "method": "direct_structured_fact",
            "sources": [
                {
                    "type": "sql",
                    "table_name": best_match["table_name"],
                    "row_index": best_match["row_index"],
                    "row_label": label_value,
                    "row_count": 1,
                }
            ],
            "sql_info": None,
        }

    # --- All-years fallback: no specific year asked, show all available ---
    if len(years) == 0 and year_headers:
        parts = []
        for yh in sorted(year_headers):
            rv = str(row_data.get(yh, "")).strip()
            if rv:
                parts.append(f"ปี {yh}: {_apply_unit(rv, unit)}")
        if parts:
            answer = f"{label_value}\n" + "\n".join(parts)
            return {
                "answer": answer,
                "method": "direct_structured_fact",
                "sources": [
                    {
                        "type": "sql",
                        "table_name": best_match["table_name"],
                        "row_index": best_match["row_index"],
                        "row_label": label_value,
                        "row_count": 1,
                    }
                ],
                "sql_info": None,
            }

    return None


async def _try_direct_table_lookup(question: str, session: AsyncSession) -> Optional[Dict[str, Any]]:
    years = _extract_years(question)
    if not years:
        return None

    normalized_question = _normalize_lookup_text(question)
    grouped_tables = await _load_grouped_structured_tables(session)

    best_match = None
    best_score = -1

    for (document_id, base_table_name), payload in grouped_tables.items():
        logical_tables = rebuild_structured_tables(base_table_name, payload["headers"], payload["rows"])
        for logical_table in logical_tables:
            headers = logical_table.get("headers", [])
            label_key = headers[0] if headers else "รายการ"
            for row_index, row_values in enumerate(logical_table.get("rows", [])):
                row_data = {
                    header: row_values[col_index] if col_index < len(row_values) else ""
                    for col_index, header in enumerate(headers)
                }
                available_years = [year for year in years if year in row_data and str(row_data.get(year, "")).strip()]
                if not available_years:
                    continue

                label_value = row_data.get(label_key, "")
                normalized_label = _normalize_lookup_text(label_value)
                if not normalized_label:
                    continue

                score = 0
                if normalized_label in normalized_question:
                    score = len(normalized_label) + 100
                elif normalized_question in normalized_label:
                    score = len(normalized_question)
                else:
                    continue

                if score > best_score:
                    best_score = score
                    best_match = {
                        "document_id": document_id,
                        "table_name": logical_table.get("table_name") or base_table_name,
                        "headers": headers,
                        "row_data": row_data,
                        "row_index": row_index,
                        "label_key": label_key,
                        "label_value": label_value,
                        "year": available_years[0],
                    }

    if not best_match:
        return None

    year = best_match["year"]
    label_key = best_match["label_key"]
    label_value = str(best_match["label_value"]).replace("'", "''")
    table_name = str(best_match["table_name"] or "").replace("'", "''")

    sql = (
        f"SELECT document_id, table_name, row_index, "
        f"row_data ->> '{label_key}' AS row_label, "
        f"row_data ->> '{year}' AS value, "
        f"'{year}' AS year "
        "FROM structured_data "
        f"WHERE table_name = '{table_name}' "
        f"AND row_data ->> '{label_key}' = '{label_value}' "
        "LIMIT 1"
    )

    return {
        "sql": sql,
        "results": [
            {
                "document_id": best_match["document_id"],
                "table_name": best_match["table_name"],
                "row_index": best_match["row_index"],
                "row_label": best_match["label_value"],
                "value": best_match["row_data"].get(year, ""),
                "year": year,
            }
        ],
        "row_count": 1,
        "columns": ["document_id", "table_name", "row_index", "row_label", "value", "year"],
        "heuristic": True,
    }


async def vector_search(
    query: str,
    session: AsyncSession,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Search chunks by semantic similarity using pgvector cosine distance."""
    query_embedding = await get_embedding(query)
    keyword_terms = _extract_keyword_terms(query)
    normalized_query = _normalize_lookup_text(query)

    semantic_stmt = (
        select(Chunk, Document.filename, Chunk.embedding.cosine_distance(query_embedding).label("distance"))
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.embedding.is_not(None))
        .order_by(Chunk.embedding.cosine_distance(query_embedding))
        .limit(max(top_k * 3, 15))
    )
    semantic_result = await session.execute(semantic_stmt)
    semantic_rows = semantic_result.all()

    merged: List[Dict[str, Any]] = []
    seen_chunk_ids = set()

    def add_result(item: Dict[str, Any]) -> None:
        chunk_id = item["chunk_id"]
        if chunk_id in seen_chunk_ids:
            return
        seen_chunk_ids.add(chunk_id)
        merged.append(item)

    for chunk, filename, distance in semantic_rows:
        source_kind = ((chunk.metadata_ or {}).get("source_kind") if hasattr(chunk, "metadata_") else None) or "semantic"
        similarity = 1.0 - float(distance)
        if source_kind == "raw_ocr_page":
            similarity -= 0.08
        elif source_kind == "raw_ocr_table":
            similarity -= 0.03
        add_result(
            {
                "chunk_id": chunk.id,
                "text": chunk.chunk_text,
                "summary": chunk.summary,
                "chunk_index": chunk.chunk_index,
                "document_id": chunk.document_id,
                "filename": filename,
                "similarity": similarity,
                "retrieval_method": "semantic",
                "source_kind": source_kind,
            }
        )

    if keyword_terms:
        acronym_terms = [term for term in keyword_terms if _is_acronym_term(term)]
        non_year_terms = [term for term in keyword_terms if not _is_year_term(term)]
        keyword_clauses = [Chunk.chunk_text.ilike(f"%{term}%") for term in keyword_terms]
        keyword_stmt = (
            select(Chunk, Document.filename)
            .join(Document, Document.id == Chunk.document_id)
            .where(or_(*keyword_clauses))
            .limit(200)
        )
        keyword_result = await session.execute(keyword_stmt)
        keyword_rows = keyword_result.all()

        scored_keyword_hits = []
        for chunk, filename in keyword_rows:
            text = chunk.chunk_text or ""
            text_lower = text.lower()
            normalized_text = _normalize_lookup_text(text)
            source_kind = ((chunk.metadata_ or {}).get("source_kind") if hasattr(chunk, "metadata_") else None) or "semantic"

            score = 0
            matched_non_year_terms = 0
            matched_acronym_terms = 0
            for term in keyword_terms:
                term_lower = term.lower()
                if term_lower in text_lower:
                    if _is_year_term(term):
                        score += 4
                    else:
                        score += max(8, len(term) * 4)
                        matched_non_year_terms += 1
                        if _is_acronym_term(term):
                            matched_acronym_terms += 1
                if _normalize_lookup_text(term) and _normalize_lookup_text(term) in normalized_text:
                    if _is_year_term(term):
                        score += 3
                    else:
                        score += max(8, len(term) * 3)
                        matched_non_year_terms += 1
                        if _is_acronym_term(term):
                            matched_acronym_terms += 1

            if normalized_query and normalized_query[:60] and normalized_query[:60] in normalized_text:
                score += 40

            if "ssf" in [term.lower() for term in keyword_terms] and "ssf" in text_lower:
                score += 120

            for year in _extract_years(query):
                if year in text:
                    score += 10

            if acronym_terms and matched_acronym_terms == 0:
                continue

            if non_year_terms and matched_non_year_terms == 0:
                continue

            if source_kind == "raw_ocr_page":
                score -= 20
            elif source_kind == "raw_ocr_table":
                score -= 8

            if score <= 0:
                continue

            scored_keyword_hits.append(
                (
                    score,
                    {
                        "chunk_id": chunk.id,
                        "text": chunk.chunk_text,
                        "summary": chunk.summary,
                        "chunk_index": chunk.chunk_index,
                        "document_id": chunk.document_id,
                        "filename": filename,
                        "similarity": min(0.999, score / 200.0),
                        "retrieval_method": "keyword",
                        "source_kind": source_kind,
                    },
                )
            )

        scored_keyword_hits.sort(key=lambda item: item[0], reverse=True)

        prioritized_keyword_hits = []
        for _, hit in scored_keyword_hits:
            prioritized_keyword_hits.append(hit)

        final_results: List[Dict[str, Any]] = []
        final_seen = set()
        for result in prioritized_keyword_hits + merged:
            if result["chunk_id"] in final_seen:
                continue
            final_seen.add(result["chunk_id"])
            final_results.append(result)
            if len(final_results) >= top_k:
                break
        return final_results

    return merged[:top_k]


async def generate_sql_from_query(question: str, session: AsyncSession) -> str:
    """Use LLM to generate SQL from a natural language question.

    The SQL targets the structured_data table which stores table data in JSONB.
    """
    # Get sample schema info
    sample_result = await session.execute(
        select(
            StructuredData.document_id,
            StructuredData.table_name,
            StructuredData.headers,
            StructuredData.row_data,
            StructuredData.row_index,
        )
        .order_by(StructuredData.table_name, StructuredData.row_index)
        .limit(150)
    )
    rows = sample_result.all()

    grouped_tables: Dict[tuple[int, str], Dict[str, Any]] = {}
    for document_id, table_name, headers, row_data, row_index in rows:
        key = (document_id, table_name or "unknown_table")
        bucket = grouped_tables.setdefault(
            key,
            {"headers": headers or [], "rows": []},
        )
        if row_data and len(bucket["rows"]) < 3:
            bucket["rows"].append(row_data)

    schema_desc = "Available tables in structured_data:\n"
    logical_schema_count = 0
    for (_, table_name), payload in grouped_tables.items():
        for logical_table in rebuild_structured_tables(table_name, payload["headers"], payload["rows"]):
            headers = logical_table.get("headers", [])
            row_dicts = [
                {
                    header: row[col_index] if col_index < len(row) else ""
                    for col_index, header in enumerate(headers)
                }
                for row in logical_table.get("rows", [])[:3]
            ]
            schema_desc += (
                f"- table_name: '{logical_table.get('table_name')}', "
                f"columns: {json.dumps(headers, ensure_ascii=False)}\n"
            )
            if headers and row_dicts:
                csv_preview = _rows_to_csv(headers, row_dicts)
                schema_desc += f"  sample_csv:\n{csv_preview}\n"
            logical_schema_count += 1
            if logical_schema_count >= 10:
                break
        if logical_schema_count >= 10:
            break

    if not logical_schema_count:
        schema_desc += "(No structured data tables available yet)\n"

    prompt = (
        "You are a SQL expert. Generate a PostgreSQL query to answer the user's question.\n"
        "The data is stored in a table called 'structured_data' with columns:\n"
        "- id (integer), document_id (integer), table_name (text), headers (jsonb), "
        "row_data (jsonb), row_index (integer)\n"
        "The headers column is a JSON array of column names, for example "
        "['รายการ','2567','2566','2565','2564','2563','column_7'].\n"
        "The row_data column is a JSON object with keys matching the headers, for example "
        "{'รายการ':'สินทรัพย์รวม','2567':'2,620,074', ...}.\n"
        "Important rules:\n"
        "- Use row_data ->> '<column_name>' to filter or select values.\n"
        "- Do NOT use headers @> with a JSON object.\n"
        "- For row labels such as 'สินทรัพย์รวม', filter with row_data ->> 'รายการ' = 'สินทรัพย์รวม'.\n"
        "- Use table_name only when you need to narrow to a specific extracted table.\n"
        "- Return plain SELECT only.\n\n"
        f"{schema_desc}\n"
        f"Question: {question}\n\n"
        "Return ONLY the SQL query, no explanation. Use proper JSONB operators (->>, ->).\n"
        "SQL:"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0, limits=HTTP_LIMITS) as client:
            response = await client.post(
                f"{settings.OLLAMA_HOST}/api/generate",
                json={
                    "model": settings.OLLAMA_LLM_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 500}
                }
            )
            response.raise_for_status()
            sql = response.json().get("response", "").strip()

            # Clean up the SQL (remove markdown fences if present)
            if sql.startswith("```"):
                sql = sql.split("```")[1]
                if sql.startswith("sql"):
                    sql = sql[3:]
                sql = sql.strip()

            return sql
    except Exception as e:
        print(f"WARNING: SQL generation failed: {e}")
        return ""


async def execute_text_to_sql(
    question: str,
    session: AsyncSession,
) -> Dict[str, Any]:
    """Generate and execute SQL from natural language question."""
    direct_answer = await try_direct_structured_answer(question, session)
    if direct_answer:
        return {
            "success": True,
            "sql": "",
            "columns": [],
            "results": [{"answer": direct_answer["answer"]}],
            "row_count": 1,
            "heuristic": True,
            "direct_answer": direct_answer["answer"],
        }

    direct_result = await _try_direct_table_lookup(question, session)
    if direct_result:
        return {
            "success": True,
            "sql": direct_result["sql"],
            "columns": direct_result["columns"],
            "results": direct_result["results"],
            "row_count": direct_result["row_count"],
            "heuristic": True,
        }

    sql = await generate_sql_from_query(question, session)

    if not sql:
        return {"success": False, "error": "Could not generate SQL", "sql": "", "results": []}

    try:
        # Safety: only allow SELECT statements
        sql_upper = sql.upper().strip()
        if not sql_upper.startswith("SELECT"):
            return {"success": False, "error": "Only SELECT queries are allowed", "sql": sql, "results": []}

        result = await session.execute(sql_text(sql))
        rows = result.fetchall()
        columns = list(result.keys()) if result.keys() else []

        return {
            "success": True,
            "sql": sql,
            "columns": columns,
            "results": [dict(zip(columns, row)) for row in rows],
            "row_count": len(rows),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "sql": sql, "results": []}
