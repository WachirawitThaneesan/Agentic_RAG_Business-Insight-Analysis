"""FastAPI main application with lifespan, CORS, and static file serving."""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import get_settings

if get_settings().OFFLINE_MODE:
    from backend.services.offline_network import install_offline_network_guard

    install_offline_network_guard()

from backend.database import init_db
from backend.routes.documents import router as documents_router
from backend.routes.scraping import router as scraping_router
from backend.routes.query import router as query_router
from backend.routes.chunks import router as chunks_router
from backend.routes.warehouse import router as warehouse_router
from backend.routes.graph import router as graph_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and DuckDB warehouse on startup."""
    settings = get_settings()
    if settings.OFFLINE_MODE:
        from backend.services.offline_runtime import prepare_offline_runtime
        await prepare_offline_runtime()
    await init_db()
    # Initialise DuckDB warehouse (creates schema if needed)
    try:
        from backend.services.duckdb_warehouse import _get_conn
        _get_conn()
        print("[OK] DuckDB warehouse initialised")
    except Exception as exc:
        print(f"[WARN] DuckDB init warning: {exc}")
    from backend.services.document_jobs import resume_interrupted_pdf_jobs, stop_pdf_jobs
    resumed = await resume_interrupted_pdf_jobs()
    if resumed:
        print(f"[OK] Resumed {resumed} interrupted PDF job(s)")
    yield
    await stop_pdf_jobs()
    if settings.OFFLINE_MODE:
        from backend.services.ocr import ocr_service
        ocr_service.close()


app = FastAPI(
    title="Intelligent Financial Data Agent",
    description="Thai financial document extraction & hybrid RAG system with Agentic RAG",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
_app_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        [f"http://127.0.0.1:{_app_settings.APP_PORT}", f"http://localhost:{_app_settings.APP_PORT}"]
        if _app_settings.OFFLINE_MODE else ["*"]
    ),
    allow_credentials=not _app_settings.OFFLINE_MODE,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes
app.include_router(documents_router, prefix="/api/documents", tags=["Documents"])
app.include_router(scraping_router, prefix="/api/scrape", tags=["Scraping"])
app.include_router(query_router, prefix="/api/query", tags=["Query"])
app.include_router(chunks_router, prefix="/api/chunks", tags=["Chunks"])
app.include_router(warehouse_router, prefix="/api/warehouse", tags=["Warehouse"])
app.include_router(graph_router, prefix="/api/graphs", tags=["Knowledge Graphs"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "Financial Data Agent", "version": "2.0.0",
            "privacy_mode": "offline" if get_settings().OFFLINE_MODE else "online"}


# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.isdir(FRONTEND_DIR):
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="frontend_assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Serve the SPA index.html for any non-API route."""
        file_path = os.path.join(FRONTEND_DIR, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    from backend.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_RELOAD,
    )
