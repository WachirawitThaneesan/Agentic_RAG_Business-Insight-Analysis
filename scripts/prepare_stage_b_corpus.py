"""Freeze a paired development corpus using recorded Gemini regions and real OCR prose.

No reference answers enter extraction/chunking. Outside eight mapped pages both
arms retain the identical recorded OCR/native corpus. Cloud generation is absent.
"""
import argparse
import asyncio
from copy import deepcopy
from pathlib import Path
import numpy as np
from scripts.evaluate_comprehensive import load, save, sha
from scripts.run_capture_paired import fingerprint


async def run(a):
    from backend.routes.documents import _assess_ocr_tables
    from backend.services.table_utils import normalize_ocr_tables, build_table_chunk_payloads
    from backend.services.embedding import get_embeddings_batch
    source = load(a.source / 'corpus.json')
    with np.load(a.source / 'embeddings.npz') as cache:
        if str(cache['fingerprint']) != fingerprint([c['text'] for c in source]):
            raise ValueError('Recorded corpus cache mismatch')
        old_vectors = cache['vectors'].copy()
    selection = load(a.selection)['pages']
    mapped = {(p['document'], p['physical_page']): p for p in selection}
    for p in selection:
        if sha(p['pdf']) != p['pdf_sha256'] or sha(p['cached_stored_page']) != p['cached_sha256']:
            raise ValueError('Original/cached source evidence changed')
    a.output.mkdir(parents=True, exist_ok=False)
    embedding_memo = {c['text']: v for c, v in zip(source, old_vectors)}
    for arm, directory in [('baseline', a.baseline), ('candidate', a.candidate)]:
        replacement = {}; lineage = []; reports = []
        for key, page in mapped.items():
            reads = sorted(directory.joinpath('pages').glob(page['id'] + '_*.json'))
            if not reads:
                raise ValueError('Missing mapped region')
            tables = []
            for path in reads:
                read = load(path)
                if read['source_pdf_sha256'] != page['pdf_sha256'] or read['physical_page'] != key[1]:
                    raise ValueError('Region source/page mismatch')
                tables.extend(read['tables'])
                lineage.append({'region': read['id'], 'record_sha256': sha(path), 'error': read.get('error'),
                    'source_sha256': page['pdf_sha256'], 'physical_page': key[1],
                    'image_sha256': read['image_sha256'], 'projection': read.get('projection')})
            filename = next(c['filename'] for c in source if c['document'] == key[0])
            normalized = normalize_ocr_tables(filename, tables)
            accepted, audit = _assess_ocr_tables(normalized)
            reports.extend({'document': key[0], **r} for r in audit)
            replacement[key] = []
            for payload in build_table_chunk_payloads(filename, accepted):
                replacement[key].append({'document': key[0], 'filename': next(c['filename'] for c in source if c['document'] == key[0]),
                    'source_pdf_page': key[1], 'text': payload['text'], 'source_kind': 'table_csv',
                    'metadata': {**{k: v for k, v in payload.items() if k != 'text'}, 'page': key[1],
                        'source_kind': 'table_csv', 'source_sha256': page['pdf_sha256'], 'source_provider': 'gemini',
                        'recorded_region_directory': str(directory.resolve()), 'extraction_scope': 'recorded component plus current deterministic storage replay'}})
        result = []; inserted = set()
        for chunk in source:
            key = (chunk['document'], chunk['source_pdf_page'])
            if key in mapped and chunk.get('source_kind') == 'table_csv':
                continue
            result.append(deepcopy(chunk))
            if key in mapped and key not in inserted:
                result.extend(replacement[key]); inserted.add(key)
        for key in mapped.keys() - inserted:
            result.extend(replacement[key])
        texts = list(dict.fromkeys(c['text'] for c in result if c['text'] not in embedding_memo))
        if texts:
            embeddings = await get_embeddings_batch(texts)
            embedding_memo.update(zip(texts, embeddings))
        for i, c in enumerate(result): c['chunk_id'] = i
        out = a.output / arm
        save(out / 'corpus.json', result)
        np.savez_compressed(out / 'embeddings.npz', vectors=np.asarray([embedding_memo[c['text']] for c in result], dtype=np.float32),
            fingerprint=fingerprint([c['text'] for c in result]))
        save(out / 'quality_reports.json', reports)
        save(out / 'lineage.json', lineage)
        save(out / 'manifest.json', {'scope': 'paired table data ablation on eight development pages; real cached Typhoon prose held fixed; OCR/native elsewhere',
            'source_corpus_sha256': sha(a.source / 'corpus.json'), 'selection_sha256': sha(a.selection),
            'n_chunks': len(result), 'mapped_pages': len(mapped), 'n_table_chunks': sum(len(v) for v in replacement.values()),
            'local_embedding_inputs_new': len(texts), 'new_sdk_attempts': 0,
            'corpus_sha256': sha(out / 'corpus.json'), 'embedding_sha256': sha(out / 'embeddings.npz'),
            'source_labels_used_by_inference': False, 'not_full_report_ingestion': True,
            'code_sha256': {p: sha(p) for p in ['scripts/prepare_stage_b_corpus.py', 'backend/services/table_utils.py', 'backend/routes/documents.py']}})
        print(arm, len(result), 'chunks;', len(texts), 'local embedding inputs', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'selection', 'baseline', 'candidate', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    asyncio.run(run(p.parse_args()))
