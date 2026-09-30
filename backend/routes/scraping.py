"""Scraping API routes."""

import json
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.services.scraper import scrape_url, scrape_by_keyword, discover_url
from backend.config import get_settings

router = APIRouter()


class ScrapeURLRequest(BaseModel):
    url: str
    download_pdfs: bool = True

    download_images: bool = False
    max_files: int = 20


class ScrapeKeywordRequest(BaseModel):
    keyword: str
    max_sites: int = 3
    max_files_per_site: int = 10


class DiscoverRequest(BaseModel):
    url: str
    max_pages: int = 20
    max_depth: int = 2
    max_pdfs: int = 20
    max_seconds: float = 90
    browser_fallback: bool = True


@router.post("/discover")
async def discover_pdf_links(request: DiscoverRequest):
    """Return verified report links and explicit blocked/failed crawl results."""
    if get_settings().OFFLINE_MODE:
        raise HTTPException(status_code=403, detail="Public website collection is disabled in OFFLINE_MODE")
    try:
        return await discover_url(
            request.url, max_pages=request.max_pages, max_depth=request.max_depth,
            max_pdfs=request.max_pdfs, max_seconds=request.max_seconds,
            browser_fallback=request.browser_fallback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/url")
async def scrape_single_url(request: ScrapeURLRequest):
    """Scrape a single URL for PDFs and images."""
    if get_settings().OFFLINE_MODE:
        raise HTTPException(status_code=403, detail="Public website collection is disabled in OFFLINE_MODE")
    result = await scrape_url(
        url=request.url,
        download_pdfs=request.download_pdfs,
        download_images=request.download_images,
        max_files=request.max_files,
    )
    return result


@router.post("/keyword")
async def scrape_by_keyword_endpoint(request: ScrapeKeywordRequest):
    """Search by keyword on Google and scrape top N results (Streams progress)."""
    if get_settings().OFFLINE_MODE:
        raise HTTPException(status_code=403, detail="Public website collection is disabled in OFFLINE_MODE")
    async def event_generator():
        async for chunk in scrape_by_keyword(
            keyword=request.keyword,
            max_sites=request.max_sites,
            max_files_per_site=request.max_files_per_site,
        ):
            yield json.dumps(chunk, ensure_ascii=False) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

