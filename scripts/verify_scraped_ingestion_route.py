"""Compare real upload/scraped PDF registration in an isolated live database.

Hold the actual worker semaphore while registering, then cancel the queued
jobs. This tests durable preparation/provenance and interruption, not fresh
OCR quality; the prior 32-page experiment supplies that separate evidence.
"""
import asyncio
import os
from pathlib import Path

import httpx
from sqlalchemy.engine import make_url

from scripts.evaluate_comprehensive import load, save, sha


async def run():
    from backend.config import get_settings
    from scripts.benchmark_long_document import _create_test_db
    source = Path(r'C:\Users\nonga\Documents\Codex\2026-10-05\step2-rag-evaluation-continuation\outputs\plan_completion_authorized_v1\integration32_real')
    plan = load(source/'plan_locked.json')
    doc = next(d for d in plan['documents'] if d['code'] == 'CPAXT')
    sample = Path(doc['sample_pdf'])
    if sha(sample) != doc['sample_sha256']: raise ValueError('Original sample changed')
    out = Path('TestFile/evaluation_completion_2026-10-07/scraped_route_registration')
    out.mkdir(exist_ok=False)
    base = get_settings().DATABASE_URL
    name = f'ragdb_route_compare_{os.getpid()}'
    await _create_test_db(base, name)
    url = make_url(base).set(database=name)
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC'] = url.set(drivername='postgresql').render_as_string(hide_password=False)
    os.environ['DUCKDB_PATH'] = str((out/'warehouse.duckdb').resolve())
    get_settings.cache_clear()
    from fastapi import FastAPI
    from sqlalchemy import select
    from backend.database import AsyncSessionLocal, engine, init_db
    from backend.models import Document, DocumentPage
    from backend.routes import documents
    from backend.services import document_jobs, scraper
    documents.UPLOAD_DIR = str((out/'uploads').resolve())
    Path(documents.UPLOAD_DIR).mkdir()
    app = FastAPI()
    app.include_router(documents.router, prefix='/api/documents')
    await init_db()
    registrations = []
    await document_jobs._one_writer.acquire()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://evaluation.local') as api:
            response = await api.post('/api/documents/upload', files={'file': (sample.name, sample.read_bytes(), 'application/pdf')})
            response.raise_for_status()
            registrations.append(('upload', response.json()['id'], response.json()))
        public_url = 'https://hub.optiwise.io/storage/116/annual-report/2024/cpaxt-or-2024-th.pdf'
        result = await scraper._ingest_scraped_file(str(sample), public_url)
        if 'error' in result: raise ValueError(result['error'])
        registrations.append(('scraped_file', result['document_id'], result))
        evidence = []
        for origin, ident, result in registrations:
            active_before = document_jobs.is_pdf_job_active(ident)
            await document_jobs.cancel_pdf_job(ident)
            async with AsyncSessionLocal() as db:
                stored = (await db.execute(select(Document).where(Document.id == ident))).scalar_one()
                pages = (await db.execute(select(DocumentPage).where(DocumentPage.document_id == ident).order_by(DocumentPage.page_number))).scalars().all()
            saved = document_jobs.saved_upload_path(ident, 'pdf')
            evidence.append({'origin': origin, 'document_id': ident, 'registration_response': result,
                'queued_worker_active_before_cancel': active_before,
                'worker_active_after_cancel': document_jobs.is_pdf_job_active(ident),
                'filename': stored.filename, 'stored_source_sha256': stored.source_sha256,
                'saved_bytes_sha256': sha(saved), 'source_url': stored.source_url,
                'page_numbers': [p.page_number for p in pages], 'page_states': [p.status for p in pages]})
        same = all(evidence[0][k] == evidence[1][k] for k in ('filename', 'stored_source_sha256', 'saved_bytes_sha256', 'page_numbers', 'page_states'))
        assert same and all(e['queued_worker_active_before_cancel'] and not e['worker_active_after_cancel'] for e in evidence)
        save(out/'summary.json', {'same_durable_preparation_and_provenance': same,
            'n_pages_per_origin': len(evidence[0]['page_numbers']), 'sdk_attempts': 0,
            'database': name, 'production_database_touched': False, 'human_confirmed': False,
            'scope': 'Actual downloaded-file registration and upload API using the same preserved original-derived sample; queued workers deliberately held/cancelled. Does not measure fresh OCR or web downloading.',
            'source_sample_sha256': doc['sample_sha256'], 'original_pdf_sha256': doc['original_sha256'],
            'page_map': doc['page_map'], 'evidence': evidence})
        print('Live upload/scraped registration matched:', len(evidence[0]['page_numbers']), 'pages; zero cloud calls')
    finally:
        await document_jobs.stop_pdf_jobs()
        document_jobs._one_writer.release()
        await engine.dispose()


if __name__ == '__main__': asyncio.run(run())
