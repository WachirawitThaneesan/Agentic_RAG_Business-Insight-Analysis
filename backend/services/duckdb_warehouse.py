"""DuckDB Data Warehouse for structured table data.

Manages a local DuckDB file with a star-schema optimised for fast
analytical queries on Thai financial data extracted via OCR.

Schema
------
- **dim_documents** – one row per uploaded document
- **dim_tables**    – one row per extracted table
- **fact_financial_metrics** – one row per *cell value* (denormalised)
- **dim_chunks**    – optional mirror of pgvector chunks for DuckDB-local search
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_DB_PATH = getattr(settings, "DUCKDB_PATH", "warehouse.duckdb")
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Connection management (thread-safe singleton)
# ---------------------------------------------------------------------------

_conn: Optional[duckdb.DuckDBPyConnection] = None


def _get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is not None:
            return _conn
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", _DB_PATH)
        db_path = os.path.abspath(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _conn = duckdb.connect(db_path, read_only=False)
        logger.info("DuckDB connected: %s", db_path)
        _init_schema(_conn)
        return _conn


def close_warehouse() -> None:
    """Explicitly close the DuckDB connection."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def reset_warehouse() -> Dict[str, int]:
    """Delete all data from the DuckDB warehouse tables.

    Returns a dict with the number of rows deleted from each table.
    """
    conn = _get_conn()
    deleted: Dict[str, int] = {}
    for table in ("fact_financial_metrics", "dim_table_rows", "dim_tables", "dim_documents", "dim_chunks"):
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            conn.execute(f"DELETE FROM {table}")
            deleted[table] = count
        except Exception:
            deleted[table] = 0
    logger.info("DuckDB warehouse reset: %s", deleted)
    return deleted


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
-- ============================================================
-- Dimension: documents
-- ============================================================
CREATE TABLE IF NOT EXISTS dim_documents (
    document_id  INTEGER PRIMARY KEY,
    filename     VARCHAR,
    doc_type     VARCHAR,
    source_url   VARCHAR,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- Dimension: tables (one per OCR-extracted table)
-- ============================================================
CREATE SEQUENCE IF NOT EXISTS seq_dim_tables START 1;
CREATE TABLE IF NOT EXISTS dim_tables (
    table_id     INTEGER PRIMARY KEY DEFAULT nextval('seq_dim_tables'),
    document_id  INTEGER,
    table_name   VARCHAR,
    title        VARCHAR,
    headers      VARCHAR[],
    row_count    INTEGER DEFAULT 0
);

-- ============================================================
-- Fact: financial metrics  (one row = one cell in the original table)
-- ============================================================
CREATE SEQUENCE IF NOT EXISTS seq_fact_metrics START 1;
CREATE TABLE IF NOT EXISTS fact_financial_metrics (
    id            INTEGER PRIMARY KEY DEFAULT nextval('seq_fact_metrics'),
    document_id   INTEGER,
    table_name    VARCHAR,
    row_label     VARCHAR,
    metric_year   VARCHAR,
    raw_value     VARCHAR,
    numeric_value DOUBLE,
    unit          VARCHAR,
    row_index     INTEGER
);

-- ============================================================
-- Dimension: text chunks (mirror from pgvector for DuckDB usage)
-- ============================================================
CREATE TABLE IF NOT EXISTS dim_chunks (
    chunk_id     INTEGER PRIMARY KEY,
    document_id  INTEGER,
    chunk_index  INTEGER,
    chunk_text   VARCHAR,
    summary      VARCHAR,
    source_kind  VARCHAR
);

-- ============================================================
-- Lookup: non-year-based table rows (e.g. investment holdings)
-- Stored as key-value pairs per row, not time-series.
-- ============================================================
CREATE SEQUENCE IF NOT EXISTS seq_dim_table_rows START 1;
CREATE TABLE IF NOT EXISTS dim_table_rows (
    id             INTEGER PRIMARY KEY DEFAULT nextval('seq_dim_table_rows'),
    document_id    INTEGER,
    table_name     VARCHAR,
    row_label      VARCHAR,
    col_name       VARCHAR,
    col_value      VARCHAR,
    col_value_num  DOUBLE,
    row_index      INTEGER
);
"""


def _migrate_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Apply idempotent migrations for warehouses created by older versions.

    1. Add ``col_value_num`` to ``dim_table_rows`` (pre-parsed numeric of
       ``col_value``) so the SQL agent never has to CAST/REPLACE by hand.
    2. Backfill ``col_value_num`` for any existing rows that lack it.
    3. (Re)create the ``v_table_rows_wide`` pivot view that turns the EAV
       ``dim_table_rows`` into one row per (table, company) with each
       ``col_name`` as its own column — removing the need for correlated
       sub-queries in generated SQL.
    """
    # --- 1. Add the numeric column if the table pre-dates it ---
    try:
        conn.execute("ALTER TABLE dim_table_rows ADD COLUMN IF NOT EXISTS col_value_num DOUBLE")
    except Exception as exc:
        logger.debug("col_value_num add skipped: %s", exc)

    # --- 2. Backfill rows where the numeric value is still NULL ---
    # Strip thousands separators, %, parentheses, and stray unit text, then
    # TRY_CAST so non-numeric cells become NULL instead of raising.
    try:
        conn.execute(
            """
            UPDATE dim_table_rows
            SET col_value_num = TRY_CAST(
                NULLIF(regexp_replace(replace(replace(col_value, ',', ''), '%', ''),
                                      '[^0-9.\\-]', '', 'g'), '')
                AS DOUBLE)
            WHERE col_value_num IS NULL AND col_value IS NOT NULL
            """
        )
    except Exception as exc:
        logger.debug("col_value_num backfill skipped: %s", exc)

    # --- 3. Pivot view: EAV -> wide (one row per company/row_label) ---
    _create_pivot_view(conn)


def _create_pivot_view(conn: duckdb.DuckDBPyConnection) -> None:
    """(Re)create v_table_rows_wide. Safe to call repeatedly.

    DuckDB does not allow a PIVOT with data-derived columns inside a view, so we
    enumerate the distinct ``col_name`` values ourselves and pin them into an
    explicit ``IN (...)`` list. The view is rebuilt after each ingestion so new
    attributes appear as columns.
    """
    try:
        names = conn.execute(
            "SELECT DISTINCT col_name FROM dim_table_rows "
            "WHERE col_name IS NOT NULL AND col_name <> '' "
            "ORDER BY col_name"
        ).fetchall()
    except Exception as exc:
        logger.debug("v_table_rows_wide skipped (cannot read col_names): %s", exc)
        return

    col_names = [n[0] for n in names if n[0]]
    if not col_names:
        # Empty warehouse — nothing to pivot yet.
        return

    # Escape single quotes for safe embedding in the IN (...) literal list.
    in_list = ", ".join("'" + c.replace("'", "''") + "'" for c in col_names)
    try:
        conn.execute(
            f"""
            CREATE OR REPLACE VIEW v_table_rows_wide AS
            PIVOT dim_table_rows
            ON col_name IN ({in_list})
            USING first(col_value)
            GROUP BY document_id, table_name, row_label, row_index
            """
        )
    except Exception as exc:
        logger.debug("v_table_rows_wide not created: %s", exc)


def _init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all warehouse tables if they don't exist yet."""
    for stmt in _SCHEMA_SQL.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt)
            except Exception as exc:
                # Sequences may already exist etc.
                logger.debug("Schema stmt skipped: %s", exc)
    _migrate_schema(conn)
    logger.info("DuckDB schema initialised")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

_RE_YEAR = re.compile(r"^(?:25|20)\d{2}$")
_RE_NUMERIC = re.compile(r"^[+-]?\d[\d,]*\.?\d*$")


def _sanitize_text(text: str) -> str:
    """Remove invalid unicode bytes that crash DuckDB."""
    if not text:
        return ""
    # Encode to UTF-8 replacing errors, then decode back
    clean = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    return _dedup_table_name(clean)


def _dedup_table_name(text: str) -> str:
    """Remove exact-repeated halves in a string.

    E.g. 'การลงทุนของธนาคารในบริษัทอื่นการลงทุนของธนาคารในบริษัทอื่น'
      →  'การลงทุนของธนาคารในบริษัทอื่น'
    """
    if not text or len(text) < 4:
        return text
    half = len(text) // 2
    if len(text) % 2 == 0 and text[:half] == text[half:]:
        return text[:half]
    # Also check with underscore separator
    for sep in ("_", ):
        parts = text.split(sep)
        mid = len(parts) // 2
        if mid > 0 and parts[:mid] == parts[mid:2 * mid]:
            return sep.join(parts[:mid])
    return text


def _parse_numeric(value: str) -> Optional[float]:
    """Try to parse a Thai-formatted number string."""
    text = str(value or "").strip()
    if not text or text in {"-", "–", "—"}:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    text = text.replace(",", "").replace("%", "").strip()
    try:
        num = float(text)
        return -num if negative else num
    except ValueError:
        return None


def _guess_unit(
    label: str,
    table_name: str = "",
    row_data: Optional[Dict[str, str]] = None,
) -> str:
    """Infer the unit from context clues."""
    combined = f"{label} {table_name}".lower()
    if "ล้านบาท" in combined:
        return "ล้านบาท"
    if "พันบาท" in combined:
        return "พันบาท"

    # Check for a หน่วย column in the row
    if row_data:
        unit_val = str(row_data.get("หน่วย", "")).strip().strip("()")
        if unit_val:
            return unit_val

    if any(kw in combined for kw in ["roe", "roa", "อัตราส่วน", "ต่อรายได้", "npl"]):
        return "%"
    if "ต่อหุ้น" in combined:
        return "บาท"
    # Default for ฐานะการเงิน tables
    if "ฐานะการเงิน" in combined:
        return "ล้านบาท"
    return ""


def load_document_dim(
    document_id: int,
    filename: str,
    doc_type: str = "pdf",
    source_url: str = "",
) -> None:
    """Upsert a document row into dim_documents."""
    conn = _get_conn()
    conn.execute(
        """
        INSERT OR REPLACE INTO dim_documents (document_id, filename, doc_type, source_url)
        VALUES (?, ?, ?, ?)
        """,
        [document_id, filename, doc_type, source_url],
    )


def load_table_into_warehouse(
    document_id: int,
    table_name: str,
    headers: List[str],
    rows: List[List[str]],
    title: str = "",
) -> int:
    """Load one OCR-extracted table into the warehouse.

    - Tables with **year headers** (2567, 2566, …) → ``fact_financial_metrics``
    - Tables **without** year headers → ``dim_table_rows`` (key-value lookup)

    Returns the number of records inserted (fact OR lookup).
    """
    conn = _get_conn()

    # Sanitize names upfront (dedup + unicode fix)
    table_name = _sanitize_text(table_name)
    title = _sanitize_text(title) if title else table_name

    # Remove old data for this doc+table (idempotent re-loads)
    conn.execute(
        "DELETE FROM fact_financial_metrics WHERE document_id = ? AND table_name = ?",
        [document_id, table_name],
    )
    conn.execute(
        "DELETE FROM dim_table_rows WHERE document_id = ? AND table_name = ?",
        [document_id, table_name],
    )
    conn.execute(
        "DELETE FROM dim_tables WHERE document_id = ? AND table_name = ?",
        [document_id, table_name],
    )

    # dim_tables
    conn.execute(
        """
        INSERT INTO dim_tables (document_id, table_name, title, headers, row_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        [document_id, table_name, title, headers, len(rows)],
    )

    # Identify year columns and label column
    label_col = 0
    year_cols: List[Tuple[int, str]] = []
    unit_col: Optional[int] = None

    for i, h in enumerate(headers):
        h_stripped = str(h or "").strip()
        if _RE_YEAR.match(h_stripped):
            year_cols.append((i, h_stripped))
        elif h_stripped == "หน่วย":
            unit_col = i

    # ── Year-based table → fact_financial_metrics ──
    if year_cols:
        return _load_year_based_table(
            conn, document_id, table_name, headers, rows,
            label_col, year_cols, unit_col,
        )

    # ── Non-year table → dim_table_rows (key-value) ──
    return _load_lookup_table(
        conn, document_id, table_name, headers, rows, label_col,
    )


def _load_year_based_table(
    conn: duckdb.DuckDBPyConnection,
    document_id: int,
    table_name: str,
    headers: List[str],
    rows: List[List[str]],
    label_col: int,
    year_cols: List[Tuple[int, str]],
    unit_col: Optional[int],
) -> int:
    """Store year-based rows in fact_financial_metrics."""
    fact_count = 0

    for row_idx, row in enumerate(rows):
        label = str(row[label_col] if label_col < len(row) else "").strip()
        if not label:
            continue

        row_dict = {h: (row[i] if i < len(row) else "") for i, h in enumerate(headers)}
        unit = _guess_unit(label, table_name, row_dict)

        # Override with explicit หน่วย column
        if unit_col is not None and unit_col < len(row):
            explicit_unit = str(row[unit_col] or "").strip().strip("()")
            if explicit_unit:
                unit = explicit_unit

        # First pass: scan year columns for misplaced unit tokens
        # e.g. "(%)", "(บาท)", "(ล้านบาท)" shifted into a year column by OCR
        found_unit_in_year = False
        for col_idx, _year_label in year_cols:
            raw_value = str(row[col_idx] if col_idx < len(row) else "").strip()
            extracted_unit = _extract_unit_token(raw_value)
            if extracted_unit:
                unit = extracted_unit
                found_unit_in_year = True
                break  # found the unit, no need to check more columns

        # Second pass: insert actual data values
        if found_unit_in_year:
            # Unit token consumed one year column, so values are shifted.
            # Collect non-unit values and assign them to year labels
            # starting from the first year (shift-left).
            data_values: List[str] = []
            for col_idx, _ in year_cols:
                rv = str(row[col_idx] if col_idx < len(row) else "").strip()
                if rv and not _extract_unit_token(rv):
                    data_values.append(rv)

            year_labels = [yl for _, yl in year_cols]
            inserted_years: set = set()
            for i, raw_value in enumerate(data_values):
                if i >= len(year_labels):
                    break
                year_label = year_labels[i]
                numeric = _parse_numeric(raw_value)
                conn.execute(
                    """
                    INSERT INTO fact_financial_metrics
                        (document_id, table_name, row_label, metric_year,
                         raw_value, numeric_value, unit, row_index)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [document_id, _sanitize_text(table_name),
                     _sanitize_text(label), _sanitize_text(year_label),
                     _sanitize_text(raw_value), numeric,
                     _sanitize_text(unit), row_idx],
                )
                inserted_years.add(year_label)
                fact_count += 1

            # Preserve the last year's value if not already inserted.
            # This avoids losing the oldest year entirely.
            last_year_label = year_labels[-1] if year_labels else None
            if last_year_label and last_year_label not in inserted_years:
                last_col_idx = year_cols[-1][0]
                last_raw = str(row[last_col_idx] if last_col_idx < len(row) else "").strip()
                if last_raw and not _extract_unit_token(last_raw):
                    numeric = _parse_numeric(last_raw)
                    conn.execute(
                        """
                        INSERT INTO fact_financial_metrics
                            (document_id, table_name, row_label, metric_year,
                             raw_value, numeric_value, unit, row_index)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [document_id, _sanitize_text(table_name),
                         _sanitize_text(label), _sanitize_text(last_year_label),
                         _sanitize_text(last_raw), numeric,
                         _sanitize_text(unit), row_idx],
                    )
                    fact_count += 1
        else:
            for col_idx, year_label in year_cols:
                raw_value = str(row[col_idx] if col_idx < len(row) else "").strip()
                if not raw_value:
                    continue

                # Skip unit tokens — they are not data
                if _extract_unit_token(raw_value):
                    continue

                numeric = _parse_numeric(raw_value)

                conn.execute(
                    """
                    INSERT INTO fact_financial_metrics
                        (document_id, table_name, row_label, metric_year,
                         raw_value, numeric_value, unit, row_index)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [document_id, _sanitize_text(table_name),
                     _sanitize_text(label), _sanitize_text(year_label),
                     _sanitize_text(raw_value), numeric,
                     _sanitize_text(unit), row_idx],
                )
                fact_count += 1

    logger.info(
        "Loaded YEAR table %s: %d rows → %d fact records",
        table_name, len(rows), fact_count,
    )
    return fact_count


# Known unit tokens that OCR might shift into data columns
_UNIT_TOKENS = {
    "%", "(%)", "บาท", "(บาท)", "ล้านบาท", "(ล้านบาท)",
    "พันบาท", "(พันบาท)", "หุ้น", "(หุ้น)", "เท่า", "(เท่า)",
    "ล้านหุ้น", "(ล้านหุ้น)", "สัญญา", "(สัญญา)",
}

_RE_UNIT_TOKEN = re.compile(
    r"^\(?(%|บาท|ล้านบาท|พันบาท|หุ้น|ล้านหุ้น|เท่า|สัญญา|บาท/หุ้น|ต่อหุ้น)\)?$"
)


def _extract_unit_token(value: str) -> Optional[str]:
    """If value is a unit token (e.g. '(%)', 'ล้านบาท'), return the unit. Else None."""
    text = value.strip()
    if not text:
        return None
    if text in _UNIT_TOKENS:
        return text.strip("()")
    m = _RE_UNIT_TOKEN.match(text)
    if m:
        return m.group(1)
    return None


def _load_lookup_table(
    conn: duckdb.DuckDBPyConnection,
    document_id: int,
    table_name: str,
    headers: List[str],
    rows: List[List[str]],
    label_col: int,
) -> int:
    """Store non-year rows in dim_table_rows (key-value pairs)."""
    record_count = 0

    for row_idx, row in enumerate(rows):
        label = str(row[label_col] if label_col < len(row) else "").strip()
        if not label:
            label = f"row_{row_idx}"

        for col_idx, col_name in enumerate(headers):
            if col_idx == label_col:
                continue
            col_value = str(row[col_idx] if col_idx < len(row) else "").strip()
            if not col_value:
                continue

            col_value_clean = _sanitize_text(col_value)
            conn.execute(
                """
                INSERT INTO dim_table_rows
                    (document_id, table_name, row_label, col_name, col_value, col_value_num, row_index)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [document_id, _sanitize_text(table_name),
                 _sanitize_text(label), _sanitize_text(col_name),
                 col_value_clean, _parse_numeric(col_value_clean), row_idx],
            )
            record_count += 1

    # Refresh the pivot view so newly-seen col_names become columns.
    _create_pivot_view(conn)

    logger.info(
        "Loaded LOOKUP table %s: %d rows → %d lookup records",
        table_name, len(rows), record_count,
    )
    return record_count


def load_chunk_dim(
    chunk_id: int,
    document_id: int,
    chunk_index: int,
    chunk_text: str,
    summary: str = "",
    source_kind: str = "semantic",
) -> None:
    """Mirror a pgvector chunk into dim_chunks."""
    conn = _get_conn()
    conn.execute(
        """
        INSERT OR REPLACE INTO dim_chunks
            (chunk_id, document_id, chunk_index, chunk_text, summary, source_kind)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [chunk_id, document_id, chunk_index, chunk_text, summary, source_kind],
    )


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

def execute_sql(sql: str) -> Dict[str, Any]:
    """Run a SELECT query on the warehouse and return structured results.

    Returns
    -------
    dict
        ``{"columns": [...], "rows": [...], "row_count": int}``
    """
    conn = _get_conn()
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed", "columns": [], "rows": [], "row_count": 0}

    try:
        result = conn.execute(sql)
        columns = [desc[0] for desc in result.description] if result.description else []
        rows = result.fetchall()
        return {
            "columns": columns,
            "rows": [dict(zip(columns, row)) for row in rows],
            "row_count": len(rows),
        }
    except Exception as exc:
        logger.warning("DuckDB query error: %s | SQL: %s", exc, sql[:200])
        return {"error": str(exc), "columns": [], "rows": [], "row_count": 0}


def lookup_table_query(question: str) -> Optional[Dict[str, Any]]:
    """Deterministic fast-path for dim_table_rows questions.

    Matches the user question to a lookup table by keyword overlap,
    then returns the matching rows WITHOUT relying on LLM SQL generation.

    Returns None if no matching lookup table is found.
    """
    conn = _get_conn()

    # Get all lookup table names
    try:
        tables = conn.execute(
            "SELECT DISTINCT table_name FROM dim_table_rows"
        ).fetchall()
    except Exception:
        return None

    if not tables:
        return None

    # Find the best matching table by keyword overlap
    question_clean = re.sub(r"[?？\s]+", "", question)
    best_table = None
    best_score = 0

    for (table_name,) in tables:
        if not table_name:
            continue
        table_clean = re.sub(r"[_\s]+", "", table_name)
        # Check how many characters of table_name are in the question
        score = 0
        for char in table_clean:
            if char in question_clean:
                score += 1
        # Also check if the table_name is a substring of question or vice versa
        if table_clean in question_clean or question_clean in table_clean:
            score += len(table_clean) * 2
        # Require at least 60% character overlap
        if score >= len(table_clean) * 0.6 and score > best_score:
            best_score = score
            best_table = table_name

    if not best_table:
        return None

    logger.info("lookup_table_query matched table: %s (score=%d)", best_table, best_score)

    # Extract limit from question (e.g. "2 อันดับแรก" → 2)
    limit = None
    limit_match = re.search(r"(\d+)\s*(?:อันดับ|ลำดับ|รายการ|แรก|ตัว|บริษัท)", question)
    if limit_match:
        limit = int(limit_match.group(1))

    # Build and execute the query
    if limit:
        sql = (
            f"SELECT row_label, col_name, col_value, row_index "
            f"FROM dim_table_rows "
            f"WHERE table_name = ? "
            f"AND row_index < ? "
            f"ORDER BY row_index, col_name"
        )
        rows = conn.execute(sql, [best_table, limit]).fetchall()
    else:
        sql = (
            f"SELECT row_label, col_name, col_value, row_index "
            f"FROM dim_table_rows "
            f"WHERE table_name = ? "
            f"ORDER BY row_index, col_name"
        )
        rows = conn.execute(sql, [best_table]).fetchall()

    if not rows:
        return None

    # Format into a readable summary grouped by company
    columns = ["row_label", "col_name", "col_value", "row_index"]
    row_dicts = [dict(zip(columns, row)) for row in rows]

    # Group by row_label for nice output
    from collections import OrderedDict
    grouped: OrderedDict = OrderedDict()
    for rd in row_dicts:
        label = rd["row_label"]
        if label not in grouped:
            grouped[label] = {}
        grouped[label][rd["col_name"]] = rd["col_value"]

    # Build display SQL for reference
    display_sql = (
        f"SELECT row_label, col_name, col_value FROM dim_table_rows "
        f"WHERE table_name = '{best_table}' "
        f"ORDER BY row_index, col_name"
        + (f" LIMIT {limit * 10}" if limit else "")
    )

    return {
        "columns": columns,
        "rows": row_dicts,
        "row_count": len(row_dicts),
        "sql": display_sql,
        "grouped": grouped,
        "table_name": best_table,
    }




def get_schema_description() -> str:
    """Return a human-readable schema summary for LLM SQL generation."""
    conn = _get_conn()

    tables = []
    lookup_tables = []
    sample_labels = []
    sample_years = []
    sample_col_names = []
    sample_lookup_labels = []

    try:
        tables = conn.execute(
            "SELECT DISTINCT table_name, COUNT(*) as rows FROM fact_financial_metrics GROUP BY table_name ORDER BY rows DESC LIMIT 20"
        ).fetchall()
    except Exception:
        pass

    try:
        lookup_tables = conn.execute(
            "SELECT DISTINCT table_name, COUNT(*) as rows FROM dim_table_rows GROUP BY table_name ORDER BY rows DESC LIMIT 20"
        ).fetchall()
    except Exception:
        pass

    try:
        sample_labels = conn.execute(
            "SELECT DISTINCT row_label FROM fact_financial_metrics LIMIT 30"
        ).fetchall()
    except Exception:
        pass

    try:
        sample_years = conn.execute(
            "SELECT DISTINCT metric_year FROM fact_financial_metrics ORDER BY metric_year"
        ).fetchall()
    except Exception:
        pass

    try:
        sample_col_names = conn.execute(
            "SELECT DISTINCT col_name FROM dim_table_rows LIMIT 20"
        ).fetchall()
    except Exception:
        pass

    try:
        sample_lookup_labels = conn.execute(
            "SELECT DISTINCT row_label FROM dim_table_rows LIMIT 20"
        ).fetchall()
    except Exception:
        pass

    # Pick the most *useful* pivoted attribute columns for the LLM: rank by how
    # often each col_name appears and drop OCR noise (auto-generated column_N,
    # single-char tokens, and over-long garbage strings).
    pivot_columns: List[str] = []
    try:
        candidates = conn.execute(
            """
            SELECT col_name, COUNT(*) AS c
            FROM dim_table_rows
            WHERE col_name IS NOT NULL
              AND col_name NOT LIKE 'column_%'
              AND length(col_name) BETWEEN 2 AND 40
            GROUP BY col_name
            ORDER BY c DESC
            LIMIT 30
            """
        ).fetchall()
        pivot_columns = [row[0] for row in candidates if row[0]]
    except Exception:
        pass

    desc = (
        "DuckDB warehouse schema:\n\n"
        "TABLE 1: fact_financial_metrics (year-based financial data)\n"
        "  Columns: document_id, table_name, row_label, metric_year,\n"
        "           raw_value, numeric_value (DOUBLE), unit, row_index\n"
        "  Use for: financial figures, assets, revenue, ratios\n\n"
        "TABLE 2: dim_table_rows (lookup data e.g. investment holdings, EAV/long format)\n"
        "  Columns: document_id, table_name, row_label, col_name, col_value,\n"
        "           col_value_num (DOUBLE, pre-parsed number of col_value), row_index\n"
        "  Use for: non-year data like company names, business types, shareholding\n\n"
        "VIEW 3: v_table_rows_wide (dim_table_rows PIVOTED to wide format)\n"
        "  Columns: document_id, table_name, row_label, row_index, + one column per attribute\n"
        "  One row per company/row_label. PREFER this view when a question filters on one\n"
        "  attribute and returns another (e.g. 'companies whose ประเภทธุรกิจ is บัตรเครดิต,\n"
        "  and their จำนวนหุ้น') — it avoids correlated sub-queries on dim_table_rows.\n\n"
        "IMPORTANT RULES:\n"
        "  - Use numeric_value for comparisons/aggregations in fact_financial_metrics\n"
        "  - metric_year is VARCHAR (e.g. '2567', '2566')\n"
        "  - Use LIKE '%keyword%' for fuzzy Thai label matching\n"
        "  - CRITICAL: 'ลำดับแรก' or 'แรก' means FIRST ROWS in the physical table. NEVER sort by a value column for these questions. ALWAYS use `ORDER BY row_index ASC LIMIT N`.\n"
        "  - Only sort by a value column if the user explicitly asks for 'มากที่สุด' (most), 'สูงสุด' (highest), etc.\n"
        "  - CRITICAL for dim_table_rows: Each row_label has multiple col_names (e.g. 'จำนวนหุ้น', 'ประเภทธุรกิจ'). If asked to list companies, just `SELECT DISTINCT row_label FROM dim_table_rows WHERE ... ORDER BY row_index`.\n"
        "  - To sort/compare dim_table_rows by number, use the ready-made col_value_num column (already parsed) instead of CAST(REPLACE(col_value ...)).\n\n"
    )

    if pivot_columns:
        desc += "Attribute columns available in v_table_rows_wide (quote Thai names with \"\"):\n"
        desc += f"  {', '.join(pivot_columns[:30])}\n\n"

    if tables:
        desc += "Year-based tables (fact_financial_metrics):\n"
        for name, count in tables:
            desc += f"  - {name} ({count} rows)\n"
        desc += "\n"

    if lookup_tables:
        desc += "Lookup tables (dim_table_rows):\n"
        for name, count in lookup_tables:
            desc += f"  - {name} ({count} rows)\n"
        desc += "\n"

    if sample_labels:
        desc += "Sample row_labels:\n"
        labels = [row[0] for row in sample_labels]
        desc += f"  {', '.join(labels)}\n\n"

    if sample_years:
        years = [row[0] for row in sample_years]
        desc += f"Available years: {', '.join(years)}\n\n"

    if sample_col_names:
        desc += "Sample col_names in dim_table_rows (use EXACT names in queries):\n"
        names = [row[0] for row in sample_col_names]
        desc += f"  {', '.join(names)}\n\n"

    if sample_lookup_labels:
        desc += "Sample row_labels in dim_table_rows:\n"
        labels = [row[0] for row in sample_lookup_labels]
        desc += f"  {', '.join(labels)}\n\n"

    return desc


def sync_structured_data_from_postgres(pg_rows: List[Dict[str, Any]]) -> int:
    """Bulk-load structured_data rows from PostgreSQL into DuckDB.

    Parameters
    ----------
    pg_rows : list[dict]
        Each dict has: document_id, table_name, headers, row_data, row_index

    Returns
    -------
    int
        Total fact rows inserted.
    """
    # Group by (document_id, table_name)
    grouped: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for row in pg_rows:
        key = (row["document_id"], row["table_name"] or "unknown")
        bucket = grouped.setdefault(key, {"headers": row.get("headers", []), "rows": []})
        bucket["rows"].append(row.get("row_data", {}))

    total = 0
    for (doc_id, tbl_name), payload in grouped.items():
        headers = payload["headers"] or []
        if not headers:
            continue
        # Convert row dicts → row lists
        raw_rows = []
        for rd in payload["rows"]:
            raw_rows.append([str(rd.get(h, "")) for h in headers])

        total += load_table_into_warehouse(doc_id, tbl_name, headers, raw_rows)

    logger.info("Synced %d fact rows from PostgreSQL", total)
    return total
