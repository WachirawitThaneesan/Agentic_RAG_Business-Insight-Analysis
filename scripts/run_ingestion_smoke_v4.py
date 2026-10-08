"""Bounded selected-page smoke through the actual API upload and ingestion job.

Uses a new PostgreSQL database and isolated uploads/DuckDB. Physical page maps
are explicit because uploaded samples are derivatives of development reports.
No gold answer is passed to ingestion, retrieval or the agent. No DB is dropped.
"""
import argparse
import asyncio
import datetime
import json
import os
from pathlib import Path
import time
import threading
import hashlib

import httpx
from sqlalchemy.engine import make_url

from scripts.bounded_cloud_meter import BoundedCloudMeter
from scripts.evaluate_comprehensive import load, save, sha


async def run(a):
    plan = load(a.plan)
    budget = load(a.budget)
    if budget.get('deadline_local') and datetime.datetime.now(datetime.timezone.utc) >= datetime.datetime.fromisoformat(budget['deadline_local']):
        raise ValueError('Original deadline reached; no new cloud experiment permitted')
    for d in plan['documents']:
        if sha(d['sample_pdf']) != d['sample_sha256'] or sha(d['original_pdf']) != d['original_sha256']:
            raise ValueError('Source/sample hash mismatch')
    from backend.config import get_settings
    settings = get_settings()
    if (settings.OFFLINE_MODE or settings.PDF_OCR_PROVIDER != 'typhoon' or
        settings.PDF_TABLE_OCR_PROVIDER != 'gemini' or settings.LLM_PROVIDER != 'gemini' or
        settings.EMBED_MODEL != 'bge-m3'):
        raise ValueError('Expected Typhoon/Gemini/BGE-M3 production providers')
    if not a.run:
        print('Preflight hashes/provider configuration verified; --run required for cloud dispatch')
        return
    a.output.mkdir(parents=True, exist_ok=False)
    save(a.output/'model_configuration.json', {key:getattr(settings,key) for key in
        ('LLM_PROVIDER','GEMINI_MODEL','GEMINI_THINKING_BUDGET','EMBED_MODEL',
         'PDF_OCR_PROVIDER','PDF_TABLE_OCR_PROVIDER','TYPHOON_OCR_MODEL','OFFLINE_MODE',
         'TYPHOON_OCR_REQUEST_TIMEOUT','TYPHOON_OCR_PAGE_TIMEOUT_SECONDS',
         'GEMINI_MAX_RETRIES','GEMINI_RETRY_BASE_DELAY')})
    save(a.output/'plan_locked.json', plan)
    save(a.output/'budget_before.json', budget)
    from scripts.benchmark_long_document import _create_test_db
    base_url = settings.DATABASE_URL
    previous = load(a.resume_from/'run_manifest.json') if a.resume_from else None
    db_name = previous['database_name'] if previous else f'ragdb_ingest_smoke_v4_{os.getpid()}'
    import re
    if not re.fullmatch(r'ragdb_ingest_smoke_v4_\d+', db_name):
        raise ValueError('Refusing to access a database outside this isolated experiment')
    if not previous:
        await _create_test_db(base_url, db_name)
    elif load(a.resume_from/'plan_locked.json') != plan:
        raise ValueError('Resume plan differs from frozen experiment')
    url = make_url(base_url).set(database=db_name)
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC'] = url.set(drivername='postgresql').render_as_string(hide_password=False)
    os.environ['DUCKDB_PATH'] = previous['duckdb_path'] if previous else str((a.output/'warehouse.duckdb').resolve())
    os.environ['GRAPH_BUILD_ENABLED'] = 'false'
    get_settings.cache_clear()
    from fastapi import FastAPI
    from sqlalchemy import select, func
    from backend.database import AsyncSessionLocal, engine, init_db
    from backend.models import Chunk, DocumentPage, StructuredData
    from backend.routes import documents
    from backend.services import document_jobs, llm
    from backend.services.agent import agent_query
    from backend.services.rag import vector_search
    from backend.services.duckdb_warehouse import close_warehouse

    # The production online route defaults to repo uploads; override only this
    # evaluation process, before any upload. Database module imports are isolated.
    owned_uploads=(Path(previous.get('uploads_directory',Path(previous['duckdb_path']).parent/'uploads'))
                   if previous else a.output/'uploads')
    documents.UPLOAD_DIR = str(owned_uploads.resolve())
    Path(documents.UPLOAD_DIR).mkdir(exist_ok=True)
    app = FastAPI()
    app.include_router(documents.router, prefix='/api/documents')
    events, answers, trace, inspections = [], [], [], []
    doc_ids = {}
    started = time.perf_counter()
    paths = ['backend/routes/documents.py', 'backend/services/ocr.py',
        'backend/services/gemini_tables.py', 'backend/services/agent.py',
        'backend/services/rag.py', 'backend/services/llm.py',
        'backend/services/answer_capture.py', 'backend/services/pdf_layout.py',
        'backend/services/source_provenance.py', 'backend/services/document_jobs.py',
        'backend/services/embedding.py', 'backend/services/chunker.py',
        'backend/services/tools.py', 'backend/services/duckdb_warehouse.py',
        'backend/models.py', 'backend/database.py',
        'scripts/run_ingestion_smoke_v4.py', 'scripts/bounded_cloud_meter.py',
        'backend/scripts/reocr_tables.py']
    save(a.output/'run_manifest.json', {'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'deadline_local': budget['deadline_local'], 'database_name': db_name,
        'postgres_production_database_touched': False,
        'duckdb_path': os.environ['DUCKDB_PATH'], 'graph_build_enabled': False,
        'uploads_directory':documents.UPLOAD_DIR,
        'plan_sha256': sha(a.plan), 'code_sha256': {p: sha(p) for p in paths},
        'resume_parent': {'path':str(a.resume_from),'run_manifest_sha256':sha(a.resume_from/'run_manifest.json')}
            if a.resume_from else None,
        'scope': plan['scope'], 'review_status': 'provisional_ai', 'human_confirmed': False,
        'ui_screenshot_status': 'not_measured_API_only', 'database_retained': True})
    for p in paths:
        target = a.output/'frozen_code'/p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(p).read_bytes())
    meter = BoundedCloudMeter(a.budget, a.output, max_new_attempts=a.max_new_attempts)
    original_ocr = documents.ocr_service.extract_from_pdf_path
    from backend.scripts import reocr_tables
    original_table_read=reocr_tables._read_page_once
    table_trace_lock=threading.Lock()
    table_trace_index=0

    def recorded_table_read(client,model,png):
        nonlocal table_trace_index
        phase=dict(meter.phase)
        try:
            result=original_table_read(client,model,png)
        except BaseException as exc:
            result=None;error=type(exc).__name__
            raise
        else:error=None
        finally:
            with table_trace_lock:
                index=table_trace_index;table_trace_index+=1
                save(a.output/'gemini_page_reads'/f'{index:04d}.json',{
                    'phase':phase,'model':model,'image_sha256':hashlib.sha256(png).hexdigest(),
                    'parsed_response':result,'error_type':error})
        return result
    reocr_tables._read_page_once=recorded_table_read
    counted = set()

    async def measured_ocr(filepath, *args, **kwargs):
        for page in kwargs.get('pages', []):
            key = (filepath, page)
            counted.add(key)
            meter.phase.update(uploaded_pdf_page=page,
                               ocr_page_key=sha(filepath)+':'+str(page))
        result = await original_ocr(filepath, *args, **kwargs)
        index = len(list((a.output/'ocr_outputs').glob('*.json'))) if (a.output/'ocr_outputs').exists() else 0
        save(a.output/'ocr_outputs'/f'{index:03d}.json', {
            'uploaded_pdf': Path(filepath).name, 'pages': kwargs.get('pages'), 'result': result})
        return result
    documents.ocr_service.extract_from_pdf_path = measured_ocr
    try:
        await init_db()
        with meter:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://evaluation.local') as api:
                for d in plan['documents']:
                    meter.phase = {'stage': 'ingestion', 'document': d['code']}
                    sample = Path(d['sample_pdf'])
                    t = time.perf_counter()
                    if a.resume_from and (a.resume_from/f"upload_{d['code']}.json").is_file():
                        upload = load(a.resume_from/f"upload_{d['code']}.json")
                        doc_id = upload['id']
                        saved_upload=Path(documents.UPLOAD_DIR)/f'{doc_id}.pdf'
                        if not saved_upload.is_file() or sha(saved_upload)!=d['sample_sha256']:
                            raise ValueError('Resume saved upload missing or differs from frozen sample')
                        before_resume=await api.get(f'/api/documents/{doc_id}/pages')
                        before_resume.raise_for_status()
                        save(a.output/f"resume_before_{d['code']}.json",before_resume.json())
                        response = await api.post(f'/api/documents/{doc_id}/resume')
                        if response.status_code != 409:
                            response.raise_for_status()
                    elif d.get('ingest_route') == 'scraped_file':
                        from backend.services.scraper import _ingest_scraped_file
                        upload = await _ingest_scraped_file(str(sample), d.get('original_source_url', ''))
                        if upload.get('error'):
                            raise RuntimeError(upload['error'])
                        doc_id = upload['document_id']
                        upload['id'] = doc_id
                    else:
                        with sample.open('rb') as f:
                            response = await api.post('/api/documents/upload', files={'file': (sample.name, f, 'application/pdf')})
                        response.raise_for_status()
                        upload = response.json(); doc_id = upload['id']
                    doc_ids[d['code']] = doc_id
                    save(a.output/f"upload_{d['code']}.json", upload)
                    print('Uploaded', d['code'], upload, flush=True)
                    last = None
                    while document_jobs.is_pdf_job_active(doc_id):
                        response = await api.get(f'/api/documents/{doc_id}/pages')
                        response.raise_for_status(); snapshot = response.json()
                        if snapshot != last:
                            events.append({'elapsed_seconds': time.perf_counter()-started, **snapshot})
                            save(a.output/'page_events.json', events); last = snapshot
                        await asyncio.sleep(.5)
                    snapshot = (await api.get(f'/api/documents/{doc_id}/pages')).json()
                    events.append({'elapsed_seconds': time.perf_counter()-started, **snapshot})
                    save(a.output/'page_events.json', events)
                    for mapping in d['page_map']:
                        p = mapping['uploaded_pdf_page']
                        page = await api.get(f'/api/documents/{doc_id}/pages/{p}')
                        page.raise_for_status(); save(a.output/'stored_pages'/f'{d["code"]}_{p}.json', page.json())
                        # Exercise the actual citation image endpoint; this verifies
                        # addressable physical pages, not screenshot/UI behavior.
                        image = await api.get(f'/api/documents/{doc_id}/pages/{p}/image')
                        if image.status_code == 200:
                            target = a.output/'citation_images'/f'{d["code"]}_{p}.png'
                            target.parent.mkdir(exist_ok=True); target.write_bytes(image.content)
                        inspections.append({'document': d['code'], **mapping,
                            'image_http_status': image.status_code})
                    async with AsyncSessionLocal() as db:
                        counts = {name: (await db.execute(select(func.count(model.id)).where(model.document_id == doc_id))).scalar_one()
                                  for name, model in [('chunks', Chunk), ('structured_rows', StructuredData), ('pages', DocumentPage)]}
                    save(a.output/f'counts_{d["code"]}.json', {**counts, 'ingestion_seconds': time.perf_counter()-t})
                    print('Ingested', d['code'], snapshot['status'], counts, flush=True)
                for q in plan['questions']:
                    meter.phase = {'stage': 'answer', 'id': q['id']}
                    t = time.perf_counter()
                    async with AsyncSessionLocal() as db:
                        hits = await vector_search(q['question'], db, top_k=5)
                        with llm.trace_model_calls() as calls:
                            result = await agent_query(q['question'], db)
                    answers.append({**q, 'answer': result['answer'], 'full_result': result,
                                    'retrieval': hits, 'agent_elapsed_seconds': time.perf_counter()-t})
                    trace.append({'id': q['id'], 'calls': calls})
                    save(a.output/'answers.json', answers); save(a.output/'model_call_traces.json', trace)
                    print('Answered', q['id'], result['method'], flush=True)
                # Resume completed jobs to measure idempotency without rerunning OCR.
                before = meter.budget['sdk_attempts']
                async with AsyncSessionLocal() as db:
                    counts_before = [(await db.execute(select(func.count(m.id)))).scalar_one()
                                     for m in (Chunk, StructuredData, DocumentPage)]
                save(a.output/'idempotency_before.json', {'row_counts': counts_before, 'sdk_attempts': before})
                for doc_id in doc_ids.values():
                    status = (await api.get(f'/api/documents/{doc_id}/pages')).json()
                    if any(p['status'] not in ('indexed', 'empty') for p in status['pages']):
                        continue
                    response = await api.post(f'/api/documents/{doc_id}/resume')
                    # A completed document rejects resume explicitly; that is a
                    # valid idempotency guard, rather than a failed ingestion.
                    if response.status_code != 409:
                        response.raise_for_status()
                    while document_jobs.is_pdf_job_active(doc_id):
                        await asyncio.sleep(.5)
                async with AsyncSessionLocal() as db:
                    counts_after = [(await db.execute(select(func.count(m.id)))).scalar_one()
                                    for m in (Chunk, StructuredData, DocumentPage)]
                save(a.output/'idempotency.json', {'row_counts_before': counts_before,
                    'row_counts_after': counts_after, 'rows_unchanged': counts_before == counts_after,
                    'new_sdk_attempts': meter.budget['sdk_attempts']-before})
        save(a.output/'citation_checks.json', inspections)
        save(a.output/'summary.json', {'n_uploaded_documents': len(doc_ids), 'n_selected_pages': len(counted),
            'n_app_responses': len(answers),
            'n_model_generated_answers': sum(any(c.get('status') == 'success' for c in t['calls']) for t in trace),
            'new_sdk_attempts': len(meter.calls),
            'new_calls_by_provider': {p: sum(r['provider'] == p for r in meter.calls) for p in ('typhoon', 'gemini')},
            'wall_seconds': time.perf_counter()-started, 'review_status': 'provisional_ai',
            'human_confirmed': False, 'ui_screenshots': None, 'scope': plan['scope']})
    finally:
        documents.ocr_service.extract_from_pdf_path = original_ocr
        reocr_tables._read_page_once=original_table_read
        await document_jobs.stop_pdf_jobs()
        close_warehouse()
        await engine.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--budget', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--max-new-attempts', type=int, default=None, help='Optional run cap; global ledger still applies')
    p.add_argument('--run', action='store_true', help='Explicitly enable bounded cloud calls')
    p.add_argument('--resume-from', type=Path, help='Retry failed pages in a prior isolated smoke DB; keep successful pages')
    a = p.parse_args()
    asyncio.run(run(a))


if __name__ == '__main__':
    main()
