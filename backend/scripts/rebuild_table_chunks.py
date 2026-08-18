"""Rebuild the vector store's table chunks from the warehouse.

Why
---
Re-OCR repaired the tables in DuckDB but not the copies embedded in Postgres.
The vector store still serves 254 chunks whose headers read ``column_3`` and
117 chunks for tables that no longer exist under that name, so an agent asking
a prose question retrieves the *broken* rendering of a table the warehouse
already holds correctly — which is a plausible source of the "found the right
chunk, quoted the wrong number" failures.

The warehouse is the curated copy (re-OCR'd tables plus the originals that were
never superseded), so regenerate every table chunk from it rather than trying
to patch the old text in place. Tables that were never re-OCR'd render exactly
as before; nothing gets worse.

Text format matches ``build_table_chunk_payloads`` so retrieval sees the same
shape it always has.

Usage:
    python -m backend.scripts.rebuild_table_chunks --dry-run
    python -m backend.scripts.rebuild_table_chunks --document-id 83
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any, Dict, List

from backend.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

MAX_ROWS_PER_CHUNK = 25
_YEARS = ("2563", "2564", "2565", "2566", "2567")


def _csv(headers: List[str], rows: List[List[str]]) -> str:
    """Serialise with the same writer the ingest path uses.

    Thai financial figures are comma-grouped ("1,784,110"), so naive joining
    splits one value across three columns and every field after it shifts —
    the model then reads a number from the wrong year. csv.writer quotes them.
    """
    from backend.services.table_utils import table_to_csv
    return table_to_csv(
        [str(h or "") for h in headers],
        [[("" if c is None else str(c)) for c in r] for r in rows],
    )


def _fact_table(con, doc_id: int, name: str):
    """Reconstruct a year-column table from fact_financial_metrics."""
    rows = con.execute(
        "SELECT row_label, metric_year, raw_value, unit, row_index "
        "FROM fact_financial_metrics WHERE document_id = ? AND table_name = ? "
        "ORDER BY row_index, row_label",
        [doc_id, name],
    ).fetchall()
    if not rows:
        return None, None
    # Key on (row_index, label), not label: a statement legitimately repeats a
    # label in different sections — p395 carries "เงินให้กู้ยืม" at index 1
    # (987,396, the headline) and again at index 12 (19,575, a sub-item). Keying
    # on the label alone let the later row overwrite the earlier one and the
    # headline figure vanished from the chunk without a trace.
    years, by_row, order, unit = set(), {}, [], ""
    for label, year, raw, u, idx in rows:
        years.add(year)
        key = (idx, label)
        if key not in by_row:
            by_row[key] = {}
            order.append(key)
        by_row[key][year] = raw
        if u and not unit:
            unit = u
    ycols = [y for y in _YEARS if y in years] + sorted(years - set(_YEARS))
    headers = ["รายการ"] + ycols + (["หน่วย"] if unit else [])
    body = [[lbl] + [by_row[(idx, lbl)].get(y, "") for y in ycols] + ([unit] if unit else [])
            for idx, lbl in order]
    return headers, body


def _lookup_table(con, doc_id: int, name: str):
    """Reconstruct a key-value table from dim_table_rows."""
    rows = con.execute(
        "SELECT row_label, col_name, col_value, row_index "
        "FROM dim_table_rows WHERE document_id = ? AND table_name = ? "
        "ORDER BY row_index",
        [doc_id, name],
    ).fetchall()
    if not rows:
        return None, None
    # Same (row_index, label) keying as _fact_table — entity tables repeat a
    # name across sections too, and a collapsed row is a silently lost row.
    cols, by_row, order = [], {}, []
    for label, col, val, idx in rows:
        if col not in cols:
            cols.append(col)
        key = (idx, label)
        if key not in by_row:
            by_row[key] = {}
            order.append(key)
        by_row[key][col] = val
    headers = ["รายการ"] + cols
    body = [[lbl] + [by_row[(idx, lbl)].get(c, "") for c in cols] for idx, lbl in order]
    return headers, body


def build_payloads(con, doc_id: int) -> List[Dict[str, Any]]:
    tables = con.execute(
        "SELECT table_name, title FROM dim_tables WHERE document_id = ? ORDER BY table_name",
        [doc_id],
    ).fetchall()
    payloads: List[Dict[str, Any]] = []
    for name, title in tables:
        headers, body = _fact_table(con, doc_id, name)
        kind = "fact"
        if not body:
            headers, body = _lookup_table(con, doc_id, name)
            kind = "lookup"
        if not body:
            continue
        title = title or name
        for start in range(0, len(body), MAX_ROWS_PER_CHUNK):
            batch = body[start:start + MAX_ROWS_PER_CHUNK]
            text = (
                f"TABLE_NAME: {name}\n"
                f"TABLE_TITLE: {title}\n"
                f"COLUMNS: {', '.join(headers)}\n"
                "CSV:\n"
                f"{_csv(headers, batch)}"
            )
            payloads.append({
                "text": text,
                "metadata": {
                    "source_kind": "table_csv",
                    "table_name": name,
                    "table_title": title,
                    "headers": headers,
                    "row_start": start,
                    "row_end": start + len(batch) - 1,
                    "rebuilt_from": "warehouse",
                    "table_kind": kind,
                },
            })
    return payloads


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--document-id", type=int, default=83)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit-preview", type=int, default=3)
    args = ap.parse_args()

    import duckdb
    con = duckdb.connect(settings.DUCKDB_PATH, read_only=True)
    payloads = build_payloads(con, args.document_id)
    con.close()

    broken = sum(1 for p in payloads if "column_" in p["text"])
    logger.info("built %d table chunks (%d still contain a column_N header)",
                len(payloads), broken)

    if args.dry_run:
        for p in payloads[:args.limit_preview]:
            logger.info("\n--- %s ---\n%s", p["metadata"]["table_name"][:60], p["text"][:600])
        return 0

    import psycopg2
    from backend.services.embedding import get_embedding

    con_pg = psycopg2.connect(settings.DATABASE_URL_SYNC)
    con_pg.set_client_encoding("UTF8")
    cur = con_pg.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM chunks WHERE document_id = %s "
        "AND metadata->>'source_kind' = 'table_csv'", [args.document_id])
    old_n = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(MAX(chunk_index), 0) FROM chunks WHERE document_id = %s",
                [args.document_id])
    next_idx = cur.fetchone()[0] + 1

    logger.info("embedding %d chunks (replacing %d existing table chunks)...",
                len(payloads), old_n)
    embedded = []
    for i, p in enumerate(payloads, 1):
        emb = await get_embedding(p["text"])
        embedded.append((p, emb))
        if i % 25 == 0:
            logger.info("  %d/%d", i, len(payloads))

    # Swap in one transaction: a half-applied rebuild would leave the index
    # serving neither the old tables nor the new ones.
    cur.execute(
        "DELETE FROM chunks WHERE document_id = %s AND metadata->>'source_kind' = 'table_csv'",
        [args.document_id])
    for offset, (p, emb) in enumerate(embedded):
        cur.execute(
            "INSERT INTO chunks (document_id, chunk_index, chunk_text, metadata, embedding, token_count) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [args.document_id, next_idx + offset, p["text"],
             json.dumps(p["metadata"], ensure_ascii=False), str(emb),
             max(1, len(p["text"]) // 4)],
        )
    con_pg.commit()
    logger.info("replaced %d chunks with %d rebuilt ones", old_n, len(embedded))
    con_pg.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
