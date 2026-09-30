"""Hybrid RAG engine: Vector Search + Text-to-SQL."""

import csv
import io
import json
import re
import httpx
from typing import List, Dict, Any, Optional
from sqlalchemy import text as sql_text, select, or_, and_, case
from sqlalchemy.ext.asyncio import AsyncSession
from backend.config import get_settings
from backend.services.embedding import get_embedding
from backend.services.table_utils import rebuild_structured_tables
from backend.services.retrieval_rank import (
    bm25_rank, matched_document_aliases, normalize_search_text,
    unique_pages, without_document_aliases,
)
from backend.models import Chunk, Document, DocumentPage, StructuredData

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
    value = normalize_search_text(str(text or ""))
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
        return word_tokenize(normalize_search_text(text), engine="newmm", keep_whitespace=False)
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


_ANSWER_SOURCE_KINDS = {None, "semantic", "table_csv"}


def _is_answer_source(chunk: Chunk) -> bool:
    """Never offer OCR audit or quality-warning artifacts as answer evidence."""
    return (chunk.metadata_ or {}).get("source_kind") in _ANSWER_SOURCE_KINDS


def _searchable_chunk_filter():
    kind = Chunk.metadata_["source_kind"].as_string()
    return or_(kind.is_(None), kind.in_(["semantic", "table_csv"]))


def _indexed_page_join():
    return and_(
        DocumentPage.document_id == Chunk.document_id,
        DocumentPage.page_number == Chunk.metadata_["page"].as_integer(),
    )


def _indexed_page_filter():
    return or_(DocumentPage.id.is_(None), DocumentPage.status == "indexed")


async def vector_search(
    query: str,
    session: AsyncSession,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Find page evidence with scoped Thai keywords and semantic fallback.

    A named issuer may restrict the corpus. A mentioned year never excludes a
    report: a current annual report can contain prior-year comparison columns.
    Numeric questions prioritize lexical evidence; qualitative questions use
    page-level reciprocal-rank fusion.
    """
    if top_k < 1:
        return []
    documents = (await session.execute(select(Document.id, Document.filename))).all()
    document_scope, issuer_aliases = matched_document_aliases(query, documents)
    ranking_query = without_document_aliases(query, issuer_aliases)
    query_embedding = await get_embedding(query)
    keyword_terms = _extract_keyword_terms(ranking_query)
    lexical_query = " ".join(keyword_terms) or ranking_query

    semantic_stmt = (
        select(Chunk, Document.filename, Chunk.embedding.cosine_distance(query_embedding).label("distance"))
        .join(Document, Document.id == Chunk.document_id)
        .outerjoin(DocumentPage, _indexed_page_join())
        .where(Chunk.embedding.is_not(None), _searchable_chunk_filter(), _indexed_page_filter())
        .order_by(Chunk.embedding.cosine_distance(query_embedding))
        .limit(max(top_k * 10, 50))
    )
    if document_scope:
        semantic_stmt = semantic_stmt.where(Chunk.document_id.in_(document_scope))
    semantic_result = await session.execute(semantic_stmt)
    semantic_rows = semantic_result.all()

    semantic_hits: List[Dict[str, Any]] = []
    for chunk, filename, distance in semantic_rows:
        if not _is_answer_source(chunk):
            continue
        meta = chunk.metadata_ or {}
        semantic_hits.append({
            "chunk_id": chunk.id, "text": chunk.chunk_text,
            "summary": chunk.summary, "chunk_index": chunk.chunk_index,
            "document_id": chunk.document_id, "filename": filename,
            "page": meta.get("page"), "similarity": 1.0 - float(distance),
            "retrieval_method": "semantic", "source_kind": meta.get("source_kind") or "semantic",
            "table_name": meta.get("table_name"), "quality_status": meta.get("quality_status"),
            "evidence_status": "ocr_extracted_unverified" if meta.get("page") else "source_not_verified",
        })

    keyword_hits: List[Dict[str, Any]] = []
    if keyword_terms:
        keyword_stmt = (
            select(Chunk, Document.filename)
            .join(Document, Document.id == Chunk.document_id)
            .outerjoin(DocumentPage, _indexed_page_join())
            .where(_searchable_chunk_filter(), _indexed_page_filter())
        )
        if document_scope:
            keyword_stmt = keyword_stmt.where(
                Chunk.document_id.in_(document_scope)).order_by(Chunk.id)
        else:
            # New chunks carry normalized text for candidate generation. Raw
            # matching remains available for chunks indexed before this change.
            clauses = []
            match_score = None
            for term in sorted(keyword_terms, key=len, reverse=True)[:8]:
                raw_match = Chunk.chunk_text.ilike(f"%{term}%")
                normalized_match = Chunk.metadata_["search_text"].as_string().ilike(f"%{term}%")
                clauses.extend((raw_match, normalized_match))
                term_score = case((or_(raw_match, normalized_match), 1), else_=0)
                match_score = term_score if match_score is None else match_score + term_score
            keyword_stmt = keyword_stmt.where(or_(*clauses)).order_by(
                match_score.desc(), Chunk.id).limit(5000)
        keyword_rows = (await session.execute(keyword_stmt)).all()
        candidates = []
        for chunk, filename in keyword_rows:
            if not _is_answer_source(chunk):
                continue
            meta = chunk.metadata_ or {}
            candidates.append({
                "chunk_id": chunk.id, "text": chunk.chunk_text,
                "search_text": meta.get("search_text") or chunk.chunk_text,
                "summary": chunk.summary, "chunk_index": chunk.chunk_index,
                "document_id": chunk.document_id, "filename": filename,
                "page": meta.get("page"), "source_kind": meta.get("source_kind") or "semantic",
                "table_name": meta.get("table_name"), "quality_status": meta.get("quality_status"),
                "evidence_status": "ocr_extracted_unverified" if meta.get("page") else "source_not_verified",
            })
        for hit in bm25_rank(lexical_query, candidates):
            hit.pop("search_text", None)
            hit["retrieval_method"] = "keyword"
            hit["similarity"] = min(0.999, hit.pop("keyword_score") / 50.0)
            keyword_hits.append(hit)

    # The diagnostic Thai numeric set strongly favours exact lexical evidence.
    # Use the semantic arm after distinct keyword pages for numeric questions.
    if re.search(r"เท่าไร|เท่าไหร่|กี่|ร้อยละ|เปอร์เซ็นต์|%|จำนวน|มูลค่า|อัตรา|รายได้|กำไร|หนี้สิน|สินทรัพย์|เงินปันผล|คะแนน", query):
        return unique_pages([*keyword_hits, *semantic_hits])[:top_k]
    return _reciprocal_rank_fusion(semantic_hits, keyword_hits, top_k)


# Rank at which a result's fusion contribution is roughly halved. The standard
# constant from the RRF literature; large enough that the top few ranks of each
# list stay close together instead of the first one dominating.
_RRF_K = 60


def _reciprocal_rank_fusion(
    semantic: List[Dict[str, Any]],
    keyword: List[Dict[str, Any]],
    top_k: int,
) -> List[Dict[str, Any]]:
    """Blend distinct PDF pages by reciprocal rank for qualitative questions."""
    fused: Dict[Any, Dict[str, Any]] = {}
    for ranking, method in ((semantic, "semantic"), (keyword, "keyword")):
        for rank, item in enumerate(unique_pages(ranking)):
            key = ((item.get("document_id"), item.get("page"))
                   if item.get("document_id") is not None and item.get("page") is not None
                   else ("chunk", item["chunk_id"]))
            entry = fused.get(key)
            if entry is None:
                entry = {"item": dict(item), "score": 0.0, "methods": set()}
                fused[key] = entry
            entry["score"] += 1.0 / (_RRF_K + rank + 1)
            entry["methods"].add(method)
            if method == "keyword":
                entry["item"] = dict(item)

    ordered = sorted(fused.values(), key=lambda e: e["score"], reverse=True)

    out: List[Dict[str, Any]] = []
    for entry in ordered[:top_k]:
        item = entry["item"]
        item["retrieval_method"] = (
            "hybrid" if len(entry["methods"]) > 1 else next(iter(entry["methods"]))
        )
        item["fusion_score"] = round(entry["score"], 6)
        out.append(item)
    return out


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
        from backend.services.llm import generate as llm_generate

        sql = (await llm_generate(prompt, temperature=0.1, max_tokens=500)).strip()
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
