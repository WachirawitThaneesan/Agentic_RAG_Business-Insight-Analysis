"""Frozen-source OCR development evaluation. References never enter inference.

Runs the actual Gemini table component on locked production-rendered regions,
or scores saved component outputs locally. This is not full ingestion/RAG QA.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import time
import unicodedata

from scripts.evaluate_comprehensive import load, save, sha


def compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or ''))).casefold()


def number(value):
    text = str(value).strip().replace(',', '')
    if text.startswith('(') and text.endswith(')'):
        text = '-' + text[1:-1]
    try:
        result = Decimal(text)
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def unit_key(value):
    text = compact(value).strip('()')
    return {'ร้อยละ': '%', 'เปอร์เซ็นต์': '%', 'บาท(thb)': 'บาท',
            'ล้านกิโลวัตต์-ชั่วโมง': 'ล้านกิโลวัตต์ชั่วโมง'}.get(text, text)


def observed_unit(table, row, column):
    headers = table.get('headers', [])
    # Explicit unit column/row/cell dominates the broad table currency heading.
    for i, header in enumerate(headers):
        if compact(header) == 'หน่วย' and i < len(row) and str(row[i]).strip():
            return row[i]
    for text in (row[column], headers[column], row[0]):
        for match in re.finditer(r'\(([^()]*)\)', str(text)):
            if any(token in match.group(1) for token in ('บาท', 'ร้อยละ', '%', 'หน่วย')):
                return match.group(1)
    return table.get('unit') or ''


def score_fact(fact, tables):
    matches = []
    for table in tables:
        if table.get('page') != fact['physical_page']:
            continue
        if fact.get('region') and table.get('region') != fact['region']:
            continue
        title = compact(table.get('title'))
        if any(compact(t) not in title for t in fact.get('scope_tokens', [])):
            continue
        headers = table.get('headers', [])
        columns = [i for i, h in enumerate(headers) if i and
                   all(compact(t) in compact(h) for t in fact['column_tokens'])]
        for row in table.get('rows', []):
            label = re.sub(r'^\s*\d+[.)]\s*', '', str(row[0])) if row else ''
            if not row or not compact(label).startswith(compact(fact['row_token'])):
                continue
            for column in columns:
                if column < len(row):
                    matches.append((table, row, column))
    if len(matches) != 1:
        return {'state': 'omitted' if not matches else 'ambiguous_location',
                'correct': False, 'n_matching_locations': len(matches)}
    table, row, column = matches[0]
    observed = row[column]
    unit = observed_unit(table, row, column)
    checks = {'signed_value': number(fact['value']) is not None and number(observed) == number(fact['value']),
              'unit': unit_key(unit) == unit_key(fact['unit']),
              'source_header_available': not fact.get('header_source_page') or
                  table.get('header_source_page') == fact['header_source_page']}
    return {'state': 'correct' if all(checks.values()) else 'wrong_relation',
            'correct': all(checks.values()), 'observed_value': observed,
            'observed_unit': unit, 'observed_column': table['headers'][column],
            'checks': checks}


def score_run(output, references):
    results = []
    records = {p.stem: load(p) for p in (output/'pages').glob('*.json')}
    grouped = {}
    for record in records.values():
        grouped.setdefault(record['document_page_id'], []).extend(record.get('tables', []))
    for fact in references['facts']:
        page_records = [r for r in records.values() if r['document_page_id'] == fact['page_id']]
        failed = not page_records or any(r.get('error') for r in page_records)
        result = ({'state': 'extraction_failed_or_missing', 'correct': None} if failed
                  else score_fact(fact, grouped.get(fact['page_id'], [])))
        results.append({'id': fact['id'], 'page_id': fact['page_id'], **result})
    measured = [r for r in results if r['correct'] is not None]
    summary = {'method': 'strict-source-cell-v1', 'scope': references['scope'],
        'n_required': len(results), 'n_measured': len(measured),
        'n_correct': sum(r['correct'] is True for r in results),
        'n_unknown': len(results)-len(measured),
        'accuracy_measured': sum(r['correct'] is True for r in results)/len(measured) if measured else None,
        'strict_lower_bound_all': sum(r['correct'] is True for r in results)/len(results) if results else None,
        'states': dict(Counter(r['state'] for r in results)),
        'failed_checks_nonexclusive': dict(Counter(k for r in results for k,v in r.get('checks', {}).items() if not v)),
        'human_confirmed': False, 'reviewer': 'Codex visual source review; development only',
        'coverage': len(measured)/len(results) if results else None,
        'n_completed_regions': len(records),
        'n_error_regions': sum(bool(r.get('error')) for r in records.values())}
    save(output/'cell_details.json', results)
    save(output/'cell_summary.json', summary)
    return summary


async def generate(a):
    from backend.services.gemini_tables import extract_tables_from_png
    from backend.services import llm
    from backend.scripts import reocr_tables
    from scripts.bounded_cloud_meter import BoundedCloudMeter
    from backend.config import get_settings
    if get_settings().OFFLINE_MODE:
        raise ValueError('Gemini component requires online mode')
    inputs = load(a.inputs)
    if a.output.exists():
        raise ValueError('New inference run must use a new output directory')
    a.output.mkdir(parents=True)
    lock = {'inputs_sha256': sha(a.inputs), 'script_sha256': sha(__file__),
        'prompt_sha256': hashlib.sha256(reocr_tables.PROMPT.encode()).hexdigest(),
        'code_sha256': {f: sha(f) for f in ('backend/services/gemini_tables.py', 'backend/scripts/reocr_tables.py')},
        'model': get_settings().GEMINI_MODEL, 'temperature': 0,
        'provider_scope': inputs['provider_scope'], 'references_supplied_to_inference': False}
    save(a.output/'method_lock.json', lock)
    original = reocr_tables._read_page_once
    reads = []
    def read(client, model, png, **kwargs):
        value = original(client, model, png, **kwargs)
        reads.append({'image_sha256': hashlib.sha256(png).hexdigest(), 'response': value})
        save(a.output/'raw_component_reads.json', reads)
        return value
    reocr_tables._read_page_once = read
    started = time.perf_counter()
    try:
        with BoundedCloudMeter(a.budget, a.output, max_new_attempts=None) as meter:
            for entry in inputs['inputs']:
                image_path = Path(entry['image_path'])
                if sha(image_path) != entry['image_sha256']:
                    raise ValueError('Locked source image changed')
                if sha(Path(entry['pdf'])) != entry['pdf_sha256']:
                    raise ValueError('Original source PDF changed')
                # Actual OCR dispatches use the original source PDF/page key.
                meter.phase = {'stage': 'ingestion', 'id': entry['id'],
                    'ocr_page_key': entry['pdf_sha256']+':'+str(entry['physical_page'])}
                await llm._get_throttle().wait()
                stamp = time.perf_counter()
                try:
                    tables, usage = await extract_tables_from_png(image_path.read_bytes(),
                        page=entry['physical_page'], region=entry['region'])
                    error = None
                except Exception as exc:
                    tables, usage, error = [], None, str(exc)
                save(a.output/'pages'/(entry['id']+'.json'), {
                    'id': entry['id'], 'document_page_id': entry['document']+'_'+str(entry['physical_page']),
                    'document': entry['document'], 'source_pdf_sha256': entry['pdf_sha256'],
                    'physical_page': entry['physical_page'], 'image_sha256': entry['image_sha256'],
                    'region': entry['region'], 'tables': tables, 'usage': usage,
                    'error': error, 'elapsed_seconds': time.perf_counter()-stamp})
                print(entry['id'], 'failed: '+str(error) if error else f'{len(tables)} tables', flush=True)
    finally:
        reocr_tables._read_page_once = original
        save(a.output/'execution.json', {'elapsed_seconds': time.perf_counter()-started,
            'quality_goal_completed': False, 'human_confirmed': False})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--inputs', type=Path)
    p.add_argument('--budget', type=Path)
    p.add_argument('--references', type=Path)
    p.add_argument('--generate', action='store_true')
    a = p.parse_args()
    if a.generate:
        if not a.inputs or not a.budget or a.references:
            p.error('Inference needs inputs/budget and must not load references')
        asyncio.run(generate(a))
    else:
        if not a.references:
            p.error('Offline scoring requires frozen references')
        print(json.dumps(score_run(a.output, load(a.references)), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
