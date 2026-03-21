"""Warehouse management API routes — DuckDB sync and status."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import StructuredData, Document
from backend.services.duckdb_warehouse import (
    execute_sql,
    get_schema_description,
    load_document_dim,
    load_table_into_warehouse,
    sync_structured_data_from_postgres,
)
from backend.services.table_utils import rebuild_structured_tables

router = APIRouter()


@router.post("/sync")
async def sync_warehouse(db: AsyncSession = Depends(get_db)):
    """Bulk-sync all PostgreSQL structured_data into DuckDB warehouse.

    Use this endpoint for the first-time migration or to resync after
    data changes.
    """
    # Load all structured data from PostgreSQL
    sd_result = await db.execute(
        select(
            StructuredData.document_id,
            StructuredData.table_name,
            StructuredData.headers,
            StructuredData.row_data,
            StructuredData.row_index,
        ).order_by(StructuredData.document_id, StructuredData.table_name, StructuredData.row_index)
    )
    rows = sd_result.all()

    # Load document dimensions
    doc_result = await db.execute(select(Document))
    docs = doc_result.scalars().all()
    for doc in docs:
        load_document_dim(
            doc.id,
            doc.filename or "",
            doc.doc_type or "pdf",
            doc.source_url or "",
        )

    # Build pg_rows list for sync
    pg_rows = []
    for document_id, table_name, headers, row_data, row_index in rows:
        pg_rows.append({
            "document_id": document_id,
            "table_name": table_name,
            "headers": headers,
            "row_data": row_data,
            "row_index": row_index,
        })

    total_facts = sync_structured_data_from_postgres(pg_rows)

    return {
        "status": "synced",
        "documents": len(docs),
        "structured_rows": len(rows),
        "fact_records": total_facts,
    }


@router.get("/status")
async def warehouse_status():
    """Get DuckDB warehouse status: table counts, sample data."""
    try:
        tables_info = execute_sql(
            "SELECT table_name, COUNT(*) as row_count "
            "FROM fact_financial_metrics "
            "GROUP BY table_name "
            "ORDER BY row_count DESC"
        )
        total = execute_sql("SELECT COUNT(*) as total FROM fact_financial_metrics")
        years = execute_sql(
            "SELECT DISTINCT metric_year FROM fact_financial_metrics ORDER BY metric_year"
        )
        docs = execute_sql("SELECT COUNT(*) as total FROM dim_documents")

        return {
            "status": "ok",
            "total_fact_records": total["rows"][0]["total"] if total["rows"] else 0,
            "total_documents": docs["rows"][0]["total"] if docs["rows"] else 0,
            "tables": tables_info["rows"],
            "available_years": [r["metric_year"] for r in years.get("rows", [])],
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@router.get("/schema")
async def warehouse_schema():
    """Get the DuckDB schema description (used by the SQL Tool)."""
    return {"schema": get_schema_description()}


@router.post("/query")
async def warehouse_query(body: dict):
    """Execute a raw SQL query on the DuckDB warehouse (SELECT only)."""
    sql = body.get("sql", "")
    if not sql:
        return {"error": "No SQL provided"}
    return execute_sql(sql)
