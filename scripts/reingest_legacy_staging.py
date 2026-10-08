"""Reindex a COPY of a real prior ingestion using its recorded OCR, then verify rollback.

No new OCR or hosted generation; this isolates storage/migration/restart behavior.
All source, staging, backup and restored databases are retained. No production DB
is selected. Cached extraction does not validate the new PDF crop or OCR accuracy.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from sqlalchemy.engine import make_url
from scripts.evaluate_comprehensive import load, save, sha


async def database_digest(base, name):
    import asyncpg
    url = make_url(base).set(database=name)
    conn = await asyncpg.connect(host=url.host,port=url.port or 5432,user=url.username,
                                 password=url.password,database=name)
    try:
        tables = {}
        for table in ('documents', 'document_pages', 'chunks', 'structured_data'):
            rows = await conn.fetch(f'SELECT row_to_json(t)::text AS payload FROM {table} t ORDER BY id')
            # Normalize JSON object ordering, while retaining all stored content.
            encoded = json.dumps([json.loads(row['payload']) for row in rows], sort_keys=True, ensure_ascii=False)
            tables[table] = {'rows': len(rows), 'sha256': hashlib.sha256(encoded.encode()).hexdigest()}
        return tables
    finally:
        await conn.close()


async def clone(base, source, target):
    from scripts.benchmark_long_document import _admin_connect
    for name in (source, target):
        if not re.fullmatch(r'ragdb_ingest_smoke_v4_\d+|ragdb_legacy_(?:stage|backup|restored)_\d+', name):
            raise ValueError('Database outside owned isolated experiment')
    conn = await _admin_connect(base)
    try:
        if await conn.fetchval('SELECT 1 FROM pg_database WHERE datname=$1', target):
            raise ValueError('Refusing to overwrite existing database')
        await conn.execute(f'CREATE DATABASE "{target}" TEMPLATE "{source}"')
    finally:
        await conn.close()


async def run(a):
    from backend.config import get_settings
    base = get_settings().DATABASE_URL
    manifest = load(a.run_dir/'run_manifest.json')
    source = manifest['database_name']
    if not re.fullmatch(r'ragdb_ingest_smoke_v4_\d+', source):
        raise ValueError('Only a recorded isolated ingestion database is accepted')
    plan = load(a.run_dir/'plan_locked.json')
    for doc in plan['documents']:
        if sha(doc['sample_pdf']) != doc['sample_sha256']:
            raise ValueError('Uploaded source changed')
    a.output.mkdir(parents=True, exist_ok=False)
    stage, backup, restored = [f'ragdb_legacy_{kind}_{os.getpid()}' for kind in ('stage', 'backup', 'restored')]
    before = await database_digest(base, source)
    save(a.output/'original_before.json', before)
    await clone(base, source, backup)
    await clone(base, source, stage)
    warehouse = Path(manifest['duckdb_path']).resolve()
    owned_root = a.run_dir.resolve()
    if not warehouse.is_relative_to(owned_root):
        raise ValueError('Warehouse must be within the recorded isolated run')
    snapshot = a.output/'warehouse_before.duckdb'
    shutil.copy2(warehouse, snapshot)
    staging_warehouse = a.output/'warehouse_staging.duckdb'
    shutil.copy2(snapshot, staging_warehouse)
    url = make_url(base).set(database=stage)
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC'] = url.set(drivername='postgresql').render_as_string(hide_password=False)
    os.environ['DUCKDB_PATH'] = str(staging_warehouse.resolve())
    os.environ['GRAPH_BUILD_ENABLED'] = 'false'
    get_settings.cache_clear()
    from sqlalchemy import select, func
    from backend.database import init_db, AsyncSessionLocal, engine
    from backend.models import Document, DocumentPage, Chunk, StructuredData
    from backend.routes import documents
    from backend.services.duckdb_warehouse import close_warehouse
    from backend.services.source_provenance import saved_source_hash
    from backend.services import llm
    root = Path(__file__).resolve().parents[1]
    code = ['backend/routes/documents.py', 'backend/services/source_provenance.py',
            'backend/models.py', 'backend/database.py', 'backend/services/duckdb_warehouse.py',
            'scripts/reingest_legacy_staging.py']
    save(a.output/'manifest.json', {'source_database': source, 'staging_database': stage,
        'backup_database': backup, 'restored_database': restored, 'production_database_touched': False,
        'new_OCR_or_generation': False, 'cached_OCR_run': str(a.run_dir),
        'code_sha256': {p:sha(root/p) for p in code},
        'OCR_inputs_sha256': {p.name:sha(p) for p in sorted((a.run_dir/'ocr_outputs').glob('*.json'))}})
    cache = {}
    for path in sorted((a.run_dir/'ocr_outputs').glob('*.json')):
        row = load(path)
        if len(row['pages']) != 1:
            raise ValueError('Expected page-level real OCR records')
        cache.setdefault((row['uploaded_pdf'], row['pages'][0]), []).append(row['result'])
    original_extract = documents.ocr_service.extract_from_pdf_path
    original_generate = llm.generate
    seen, interrupted, first_document, dispatches = [], False, None, []
    async def forbid_generation(*args, **kwargs):
        raise RuntimeError('Hosted generation forbidden in cached legacy migration')
    async def cached_extract(filepath, *args, **kwargs):
        nonlocal interrupted
        key = (Path(filepath).name, kwargs['pages'][0])
        if first_document == key[0] and key[1] == 2 and not kwargs.get('render_dpi') and not interrupted:
            interrupted = True
            raise asyncio.CancelledError('Controlled restart after persisted first page')
        if key not in cache:
            raise ValueError('No verified real OCR record for requested uploaded page')
        index = 1 if kwargs.get('render_dpi') and len(cache[key]) > 1 else 0
        seen.append({'uploaded_pdf':key[0], 'page':key[1], 'cached_result_index':index})
        return deepcopy(cache[key][index])
    documents.ocr_service.extract_from_pdf_path = cached_extract
    llm.generate = forbid_generation
    documents.UPLOAD_DIR = str(a.run_dir/'uploads')
    try:
        await init_db()
        async with AsyncSessionLocal() as db:
            docs = (await db.execute(select(Document).order_by(Document.id))).scalars().all()
            first_document = f'{docs[0].id}.pdf'
            for doc in docs:
                current_doc_id = doc.id
                filepath = a.run_dir/'uploads'/f'{doc.id}.pdf'
                expected = next(d['sample_sha256'] for d in plan['documents']
                                if load(a.run_dir/f"upload_{d['code']}.json")['id'] == doc.id)
                if saved_source_hash(filepath) != expected:
                    raise ValueError('Saved upload differs from frozen source/sample hash')
                doc.raw_text = ''; doc.status = 'pending'; doc.error_message = None
                pages = (await db.execute(select(DocumentPage).where(DocumentPage.document_id==doc.id))).scalars().all()
                for page in pages:
                    page.status = 'pending'; page.error_stage = page.error_message = None
                await db.commit()
                try:
                    await documents._process_saved_document(doc, str(filepath), 'pdf', db)
                except asyncio.CancelledError:
                    await db.rollback()
                    statuses = (await db.execute(select(DocumentPage.page_number,DocumentPage.status)
                                .where(DocumentPage.document_id==current_doc_id))).all()
                    save(a.output/'interrupted_checkpoint.json', [list(row) for row in statuses])
                    doc = (await db.execute(select(Document).where(Document.id==current_doc_id))).scalar_one()
                    await documents._process_saved_document(doc, str(filepath), 'pdf', db)
                print('Legacy staging reindexed', doc.id, doc.status, flush=True)
            counts = [(await db.execute(select(func.count(m.id)))).scalar_one()
                      for m in (Chunk,StructuredData,DocumentPage)]
            cached_before = len(seen)
            for doc in docs:
                await documents._process_saved_document(doc,str(a.run_dir/'uploads'/f'{doc.id}.pdf'),'pdf',db)
            counts_after = [(await db.execute(select(func.count(m.id)))).scalar_one()
                           for m in (Chunk,StructuredData,DocumentPage)]
            hashes = {doc.id:doc.source_sha256 for doc in docs}
            chunks = (await db.execute(select(Chunk))).scalars().all()
            rows = (await db.execute(select(StructuredData))).scalars().all()
            save(a.output/'migration_checks.json', {'chunk_count':len(chunks),'structured_count':len(rows),
                'chunks_hash_bound':sum((c.metadata_ or {}).get('source_sha256')==hashes[c.document_id] for c in chunks),
                'structured_hash_bound':sum(r.source_sha256==hashes[r.document_id] for r in rows),
                'duplicate_page_chunk_indices':len(chunks)-len({(c.document_id,c.chunk_index) for c in chunks}),
                'idempotent_counts':counts==counts_after,'idempotent_new_cached_extractions':len(seen)-cached_before,
                'controlled_restart_exercised':interrupted})
        save(a.output/'cached_dispatches.json',seen)
    finally:
        documents.ocr_service.extract_from_pdf_path = original_extract
        llm.generate = original_generate
        close_warehouse(); await engine.dispose()
    await clone(base,backup,restored)
    shutil.copy2(snapshot,a.output/'warehouse_restored.duckdb')
    after = await database_digest(base,source)
    restored_digest = await database_digest(base,restored)
    save(a.output/'original_after.json',after);save(a.output/'rollback_restored.json',restored_digest)
    checks = load(a.output/'migration_checks.json')
    save(a.output/'summary.json', {'original_database_unchanged':before==after,
        'original_warehouse_unchanged':sha(warehouse)==sha(snapshot),
        'rollback_database_content_restored':restored_digest==before,
        'rollback_warehouse_content_restored':sha(a.output/'warehouse_restored.duckdb')==sha(snapshot),
        'new_sdk_attempts':0,'review_status':'storage integration; cached real OCR; not a new OCR quality score',
        'all_databases_retained':True, **checks})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    asyncio.run(run(parser.parse_args()))


if __name__=='__main__':main()
