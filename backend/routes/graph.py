"""Knowledge Graph API routes.

Endpoints:
  GET  /api/graphs                     — list all built KAs
  GET  /api/graphs/{doc_id}/status     — KA status for a specific document
  POST /api/graphs/{doc_id}/rebuild    — manually trigger KA rebuild
  GET  /api/graphs/search?q=...        — direct graph search (no agent)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from backend.database import get_db
from backend.models import Document
from sqlalchemy import select

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def list_graphs():
    """List all built Knowledge Abstracts."""
    from backend.services.graph_service import list_all_graphs
    return {"graphs": list_all_graphs()}


@router.get("/search")
async def graph_search(q: str = Query(..., description="Natural language query")):
    """Direct graph search — bypasses the agent, returns raw KA results."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")

    from backend.services.graph_service import search_knowledge_graph
    result = search_knowledge_graph(q)
    return result


@router.get("/{doc_id}/status")
async def graph_status(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Return Knowledge Abstract build status for a document."""
    # Verify document exists
    res = await db.execute(select(Document).where(Document.id == doc_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    from backend.services.graph_service import get_graph_status
    return get_graph_status(doc_id)


@router.post("/{doc_id}/rebuild")
async def rebuild_graph(doc_id: int, db: AsyncSession = Depends(get_db)):
    """Trigger a Knowledge Abstract rebuild for a document.

    Builds the graph synchronously (returns when done) so the user gets
    immediate feedback. Also fires a Celery task as an async side-effect
    if a worker is running (it will overwrite with a fresh build).
    """
    res = await db.execute(select(Document).where(Document.id == doc_id))
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    raw_text = (doc.raw_text or "").strip()
    if not raw_text:
        raise HTTPException(
            status_code=422,
            detail=f"Document {doc_id} has no raw text. Re-process the document first.",
        )

    # Build synchronously so we always return a real result
    import asyncio
    loop = asyncio.get_event_loop()
    from backend.services.graph_service import build_knowledge_graph
    result = await loop.run_in_executor(
        None, lambda: build_knowledge_graph(doc_id=doc_id, text=raw_text)
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Graph build failed"))

    # Optionally also queue to Celery (fire-and-forget, ignore errors)
    try:
        from backend.tasks import build_graph_task
        build_graph_task.delay(doc_id=doc_id, text=raw_text)
    except Exception:
        pass  # Celery not running — that's fine, we already built it above

    return {
        "status": "completed",
        "doc_id": doc_id,
        "entities": result.get("entities", 0),
        "relations": result.get("relations", 0),
        "ka_path": result.get("ka_path"),
        "filename": doc.filename,
    }

