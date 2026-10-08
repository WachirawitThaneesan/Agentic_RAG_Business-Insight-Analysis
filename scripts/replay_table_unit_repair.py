"""Paired storage replay of cached real OCR, with optional bounded fresh answers.

The original upload DB and DuckDB are retained. Only a new DuckDB copy is
modified; PostgreSQL is read from the original isolated evaluation DB.
Truth is used after storage and inference, never passed to the agent.
"""
import argparse
import asyncio
import datetime
import os
from pathlib import Path
import re
import shutil
import time

import duckdb
from sqlalchemy.engine import make_url

from scripts.bounded_cloud_meter import BoundedCloudMeter
from scripts.evaluate_comprehensive import load, save, sha


def check_cells(conn, truth):
    cells = conn.execute("select row_label,col_name,col_value_num,unit,source_page from dim_table_rows order by row_index,col_name").fetchall()
    checks = []
    for row in truth['rows']:
        for year, value in zip(truth['year_columns_be'], row['values']):
            matches = [c for c in cells if c[0] == row['row_label']+' (ล้านบาท)' and str(year) in c[1]]
            cell = matches[0] if len(matches) == 1 else None
            checks.append({'row_label': row['row_label'], 'year_be': year, 'expected_value': value,
                'expected_unit': truth['row_unit'], 'actual': list(cell) if cell else None,
                'value_match': bool(cell and cell[2] == float(value)),
                'tuple_match': bool(cell and cell[2] == float(value) and cell[3] == truth['row_unit'] and cell[4] == truth['uploaded_pdf_page'])})
    return {'n_cells': len(checks), 'value_correct': sum(c['value_match'] for c in checks),
        'tuple_correct': sum(c['tuple_match'] for c in checks), 'checks': checks,
        'review_status': truth['review_status'], 'human_confirmed': False}


async def run(a):
    manifest = load(a.source/'run_manifest.json')
    if not re.fullmatch(r'ragdb_ingest_smoke_v4_\d+', manifest['database_name']):
        raise ValueError('Not an isolated evaluation database')
    # Prefer the archived run-local copy, so offline replay survives relocation.
    original = a.source/'warehouse.duckdb'
    original_hash = sha(original)
    cached = a.source/'ocr_outputs/000.json'
    ocr = load(cached)['result']
    truth = load(a.truth)
    a.output.mkdir(parents=True, exist_ok=False)
    copy = a.output/'warehouse.duckdb'
    shutil.copyfile(original, copy)
    from backend.services import duckdb_warehouse as w
    conn = duckdb.connect(str(copy))
    w._conn = conn
    before = check_cells(conn, truth)
    tables = conn.execute('select distinct document_id,table_name from dim_table_rows').fetchall()
    if len(tables) != len(ocr['tables']):
        raise ValueError('Cached table count differs from stored table identities')
    for (doc_id, table_name), table in zip(tables, ocr['tables']):
        w.load_table_into_warehouse(doc_id, table_name, table['headers'], table['rows'],
            title=table['title'], unit=table['unit'], source_page=table['page'],
            source_provider=table['source_provider'], quality_status='unverified')
    after = check_cells(conn, truth)
    w.close_warehouse()
    save(a.output/'cell_comparison.json', {'before': before, 'after': after,
        'same_cached_ocr': True, 'new_ocr_calls': 0, 'original_sha256_unchanged': sha(original) == original_hash})
    paths = ['backend/services/duckdb_warehouse.py', 'backend/services/agent.py',
        'backend/services/llm.py', 'scripts/replay_table_unit_repair.py', 'scripts/bounded_cloud_meter.py']
    for p in paths:
        target = a.output/'frozen_code'/p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(p).read_bytes())
    save(a.output/'run_manifest.json', {'started_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_run': str(a.source), 'database_name': manifest['database_name'], 'postgres_writes': 0,
        'postgres_production_database_touched': False, 'duckdb_path': str(copy.resolve()),
        'original_duckdb_sha256': original_hash, 'cached_ocr_sha256': sha(cached),
        'truth_sha256': sha(a.truth), 'code_sha256': {p: sha(p) for p in paths},
        'scope': 'Development paired cached-OCR storage repair; optional fresh full agent answers; not fresh upload/OCR or unseen',
        'review_status': 'provisional_ai', 'human_confirmed': False})
    if not a.run:
        return
    from backend.config import get_settings
    settings = get_settings()
    url = make_url(settings.DATABASE_URL).set(database=manifest['database_name'])
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC'] = url.set(drivername='postgresql').render_as_string(hide_password=False)
    os.environ['DUCKDB_PATH'] = str(copy.resolve())
    os.environ['GRAPH_BUILD_ENABLED'] = 'false'
    get_settings.cache_clear()
    from backend.database import AsyncSessionLocal, engine
    from backend.services.agent import agent_query
    from backend.services import llm
    answers, traces = [], []
    meter = BoundedCloudMeter(a.budget, a.output, max_new_attempts=6)
    try:
        with meter:
            for q in load(a.source/'plan_locked.json')['questions']:
                meter.phase = {'stage': 'cached_ocr_unit_repair_answer', 'id': q['id']}
                start = time.perf_counter()
                async with AsyncSessionLocal() as db:
                    with llm.trace_model_calls() as calls:
                        result = await agent_query(q['question'], db)
                answers.append({**q, 'answer': result['answer'], 'full_result': result,
                    'agent_elapsed_seconds': time.perf_counter()-start})
                traces.append({'id': q['id'], 'calls': calls})
                save(a.output/'answers.json', answers)
                save(a.output/'model_call_traces.json', traces)
                print('Answered', q['id'], result['answer'], flush=True)
        save(a.output/'summary.json', {'before_cell_tuples': before['tuple_correct'],
            'after_cell_tuples': after['tuple_correct'], 'n_cells': after['n_cells'],
            'n_answers': len(answers), 'new_sdk_attempts': len(meter.calls), 'new_ocr_calls': 0,
            'original_duckdb_sha256_unchanged': sha(original) == original_hash,
            'review_status': 'provisional_ai', 'human_confirmed': False})
    finally:
        w.close_warehouse()
        await engine.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--truth', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--budget', type=Path, required=True)
    p.add_argument('--run', action='store_true', help='Enable at most six fresh SDK attempts for full agent answers')
    asyncio.run(run(p.parse_args()))


if __name__ == '__main__':
    main()
