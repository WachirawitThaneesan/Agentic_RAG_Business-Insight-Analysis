"""Celery tasks that do not open the API-owned DuckDB warehouse."""

import asyncio

from celery import Celery

from backend.config import get_settings

settings = get_settings()
celery_app = Celery("financial_agent", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Bangkok",
    enable_utc=True,
    task_track_started=True,
)


@celery_app.task(bind=True, name="process_document")
def process_document_task(self, document_id: int, filepath: str):
    """Reject the retired worker path so it cannot bypass PDF quality checks."""
    raise RuntimeError(
        "process_document is retired. Upload PDFs through /api/documents/upload; "
        "the API-owned resumable job keeps DuckDB writes in one process."
    )


@celery_app.task(bind=True, name="scrape_and_process")
def scrape_and_process_task(self, keyword: str, target_urls: list | None = None):
    """Scrape only; do not enqueue a fake document_id=0 for processing."""
    from backend.services.scraper import scrape_by_keyword

    self.update_state(state="SCRAPING", meta={"step": f"Scraping for: {keyword}"})
    result = asyncio.run(scrape_by_keyword(keyword, target_urls))
    return {
        "status": "scraped_only",
        "result": result,
        "warning": "Files are not indexed by this legacy Celery task; upload them through the document API.",
    }


@celery_app.task(bind=True, name="build_graph")
def build_graph_task(self, doc_id: int, text: str):
    """Build a knowledge graph after successful ingestion; failure is isolated."""
    self.update_state(state="PROCESSING", meta={"step": f"Building knowledge graph for doc_id={doc_id}..."})
    try:
        from backend.services.graph_service import build_knowledge_graph
        result = build_knowledge_graph(doc_id=doc_id, text=text)
        if result.get("success"):
            print(
                f"[graph_task] doc_id={doc_id} - "
                f"{result.get('entities', 0)} entities, {result.get('relations', 0)} relations"
            )
        else:
            print(f"[graph_task] doc_id={doc_id} - build failed: {result.get('error')}")
        return result
    except Exception as exc:
        print(f"[graph_task] Unexpected error for doc_id={doc_id}: {exc}")
        return {"success": False, "error": str(exc)}
