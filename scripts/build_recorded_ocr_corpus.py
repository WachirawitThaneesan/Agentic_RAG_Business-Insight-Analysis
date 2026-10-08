"""Use real stored OCR chunks on mapped development pages; retain full native scope elsewhere.

Only indexed semantic/accepted table chunks are admitted. Audit/quarantined rows
never become evidence. Exact BGE-M3 embeddings are reused from recorded storage.
This is a development data-repair ablation, not a full production or unseen test.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import numpy as np
from sqlalchemy.engine import make_url
from scripts.evaluate_comprehensive import load, save, sha
from scripts.benchmark_large_retrieval import corpus
from scripts.run_capture_paired import fingerprint


def page_lineage(directory, code, uploaded):
    """A database snapshot is not proof of a fresh extraction in that run."""
    directory=Path(directory)
    manifest=load(directory/'run_manifest.json')
    before_path=directory/f'resume_before_{code}.json'
    before=load(before_path) if before_path.exists() else None
    previous=next((p for p in (before or {}).get('pages',[]) if p['page']==uploaded),None)
    parent=manifest.get('resume_parent')
    result={'snapshot_run':str(directory),'snapshot_manifest_sha256':sha(directory/'run_manifest.json'),
            'resume_before_sha256':sha(before_path) if before else None,
            'prior_page_status':previous.get('status') if previous else None}
    if previous and previous['status']=='indexed':
        result['fresh_extraction_in_snapshot_run']=False
        if parent:
            parent_dir=Path(parent['path'])
            if sha(parent_dir/'run_manifest.json')!=parent['run_manifest_sha256']:
                raise ValueError('Resume parent manifest changed')
            result['parent_page_lineage']=page_lineage(parent_dir,code,uploaded)
        else:
            result['extraction_origin']='unknown_prior_run; old resume manifest did not bind its parent'
    elif previous:
        result['fresh_extraction_in_snapshot_run']=True
    elif parent:
        result['fresh_extraction_in_snapshot_run']=None
        result['extraction_origin']='resume without a saved before-page status'
    else:
        # Older runners did not record resume metadata. Do not call reused
        # evidence fresh merely because that field is missing.
        result['fresh_extraction_in_snapshot_run']=None
        result['extraction_origin']='not certified by legacy run manifest'
    return result


async def run(a):
    import asyncpg
    from backend.config import get_settings
    base=make_url(get_settings().DATABASE_URL)
    bank,paths=load(a.reference),load(a.pdf_paths)
    sources={'documents':[{**d,'path':paths[d['code']]} for d in bank['documents']]}
    for d in sources['documents']:
        if sha(d['path'])!=d['source_sha256']:raise ValueError('Original PDF changed')
    native=load(a.source_corpus) if a.source_corpus else corpus(sources)
    registry={d['code']:d for d in bank['documents']}
    for chunk in native:
        doc=registry[chunk['document']]
        if chunk['filename']!=doc['source_file'] or not 1<=chunk['source_pdf_page']<=doc['source_page_count']:
            raise ValueError('Input corpus source identity/page differs from registry')
    with np.load(a.native_cache) as cache:
        if str(cache['fingerprint'])!=fingerprint([c['text'] for c in native]):raise ValueError('Native embedding cache mismatch')
        native_vectors=cache['vectors'].copy()
    replacements={};provenance=[];unreplaced=[]
    for directory in a.run_dir:
        plan=load(directory/'plan_locked.json');manifest=load(directory/'run_manifest.json')
        name=manifest['database_name']
        if not re.fullmatch(r'ragdb_ingest_smoke_v4_\d+',name):raise ValueError('Database outside recorded isolated ingestion')
        conn=await asyncpg.connect(host=base.host,port=base.port or 5432,user=base.username,password=base.password,database=name)
        try:
            for d in plan['documents']:
                if sha(d['sample_pdf'])!=d['sample_sha256'] or sha(d['original_pdf'])!=d['original_sha256']:
                    raise ValueError('Mapped original/upload PDF changed')
                docid=load(directory/f"upload_{d['code']}.json")['id']
                doc=next(x for x in bank['documents'] if x['code']==d['code'])
                if doc['source_sha256']!=d['original_sha256']:raise ValueError('Original registry differs')
                rows=await conn.fetch('''SELECT c.chunk_index,c.chunk_text,c.embedding::text AS vector,c.metadata
                    FROM chunks c JOIN document_pages p ON p.document_id=c.document_id
                    AND p.page_number=(c.metadata->>'page')::integer
                    WHERE c.document_id=$1 AND p.status='indexed' AND c.embedding IS NOT NULL
                    AND COALESCE(c.metadata->>'source_kind','semantic') IN ('semantic','table_csv') ORDER BY c.chunk_index''',docid)
                for mapping in d['page_map']:
                    uploaded,original=mapping['uploaded_pdf_page'],mapping['original_pdf_page']
                    lineage=page_lineage(directory,d['code'],uploaded)
                    part=[]
                    for row in rows:
                        meta=json.loads(row['metadata']) if isinstance(row['metadata'],str) else row['metadata']
                        if meta['page']!=uploaded:continue
                        metadata={**meta,'page':original,'extraction_input_sha256':d['sample_sha256'],
                                  'extraction_uploaded_pdf_page':uploaded,'recorded_ingestion_run':str(directory),
                                  'recorded_page_lineage':lineage}
                        chunk={'document':d['code'],'filename':doc['source_file'],'source_pdf_page':original,
                               'text':row['chunk_text'],'source_kind':meta.get('source_kind') or 'semantic','metadata':metadata}
                        vector=np.asarray(json.loads(row['vector']),dtype=np.float32)
                        if vector.shape!=(1024,) or not np.isfinite(vector).all():raise ValueError('Invalid stored embedding')
                        part.append((chunk,vector))
                    if not part:
                        unreplaced.append({'document':d['code'],'original_pdf_page':original,
                            'uploaded_pdf_page':uploaded,'recorded_run':str(directory),
                            'state':'No eligible indexed OCR evidence; unchanged native baseline retained; OCR gap remains'})
                        continue
                    replacements[(d['code'],original)]=part
                    provenance.append({'document':d['code'],'original_pdf_page':original,'uploaded_pdf_page':uploaded,
                        'original_sha256':d['original_sha256'],'extraction_input_sha256':d['sample_sha256'],
                        'n_admitted_chunks':len(part),'run_manifest_sha256':sha(directory/'run_manifest.json'),
                        'page_lineage':lineage,
                        'replacement_precedence':'later explicit run wins for repeated source page'})
        finally:await conn.close()
    result=[];vectors=[];inserted=set()
    for c,v in zip(native,native_vectors):
        key=(c['document'],c['source_pdf_page'])
        if key in replacements:
            if key not in inserted:
                for chunk,vector in replacements[key]:
                    result.append({**chunk,'chunk_id':len(result)});vectors.append(vector)
                inserted.add(key)
        else:
            result.append({**c,'chunk_id':len(result)});vectors.append(v)
    for key,part in replacements.items():
        if key not in inserted:
            for chunk,vector in part:
                result.append({**chunk,'chunk_id':len(result)});vectors.append(vector)
    a.output.mkdir(parents=True,exist_ok=False)
    save(a.output/'corpus.json',result)
    np.savez_compressed(a.output/'embeddings.npz',vectors=np.asarray(vectors,dtype=np.float32),
                       fingerprint=fingerprint([c['text'] for c in result]))
    save(a.output/'provenance.json',provenance)
    save(a.output/'unreplaced_pages.json',unreplaced)
    save(a.output/'manifest.json',{'reference_sha256':sha(a.reference),'original_cache_sha256':sha(a.native_cache),
        'code_sha256':sha(__file__),'new_embedding_calls':0,'new_sdk_attempts':0,
        'n_original_native_chunks':None if a.source_corpus else len(native),
        'n_input_base_chunks':len(native),'n_result_chunks':len(result),'n_unique_repaired_original_pages':len(replacements),
        'n_unreplaced_page_dispatches':len(unreplaced),
        'corpus_sha256':sha(a.output/'corpus.json'),'embedding_cache_sha256':sha(a.output/'embeddings.npz'),
        'source_corpus_path':str(a.source_corpus) if a.source_corpus else None,
        'source_corpus_sha256':sha(a.source_corpus) if a.source_corpus else None,
        'scope':('Full development PDF scope; current sampled OCR replaces mapped pages in explicitly frozen historical OCR/native base; base outside mapped pages unchanged; no gold in retrieval'
                 if a.source_corpus else 'Full development PDF scope; mapped real OCR on explicitly sampled pages, native elsewhere; no gold in retrieval'),
        'not_full_report_production_ingestion':True})
    print(json.dumps(load(a.output/'manifest.json')),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','pdf-paths','native-cache','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--source-corpus',type=Path,help='Frozen OCR/native base; cache must bind its exact texts')
    p.add_argument('--run-dir',type=Path,action='append',required=True)
    asyncio.run(run(p.parse_args()))


if __name__=='__main__':main()
