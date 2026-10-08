"""BM25/dense/production hybrid on a frozen large Thai question bank.

Uses an isolated database, hash-verified PDFs and cached local embeddings.
--answer-limit additionally runs a deterministic stratified sample through the
real agent. Never feeds reference answers/pages into retrieval or generation.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
import shutil
import importlib.util
import sys
import time
from pathlib import Path
import numpy as np
from sqlalchemy.engine import make_url
from scripts.benchmark_heldout import _corpus,_embed_texts,_source,BM25
from scripts.benchmark_long_document import _create_test_db,_drop_test_db
from scripts.evaluate_comprehensive import save,load,sha


def corpus(sources):
    chunks=[]
    for doc in sources['documents']:
        part=_corpus({'documents':[doc]},Path(doc['path']).parent)
        for row in part: row['chunk_id']+=len(chunks)
        chunks+=part
    return chunks


def prepare_vectors(chunks,output,components):
    texts=[r['text'] for r in chunks]
    if components and not (output/'embeddings.npz').exists():
        vectors=[];offset=0
        for filename in components:
            with np.load(filename) as cached:
                v=cached['vectors'];subset=texts[offset:offset+len(v)]
                fingerprint=hashlib.sha256(('bge-m3\n'+'\n'.join(subset)).encode()).hexdigest()
                if str(cached['fingerprint'])!=fingerprint:
                    raise ValueError('Component embedding cache fingerprint mismatch')
                vectors.append(v);offset+=len(v)
        if offset!=len(texts):raise ValueError('Incomplete component caches')
        np.savez_compressed(output/'embeddings.npz',vectors=np.concatenate(vectors),
            fingerprint=hashlib.sha256(('bge-m3\n'+'\n'.join(texts)).encode()).hexdigest())
    return _embed_texts(texts,'bge-m3',output/'embeddings.npz')


async def run(args,manifest,chunks,vectors,qvectors,bm25,meter):
    from backend.config import get_settings
    settings=get_settings();base_url=settings.DATABASE_URL
    db_name=f'ragdb_comprehensive_{os.getpid()}'
    await _create_test_db(base_url,db_name)
    url=make_url(base_url).set(database=db_name)
    os.environ['DATABASE_URL']=url.render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC']=url.set(drivername='postgresql').render_as_string(hide_password=False)
    os.environ['DUCKDB_PATH']=str(args.output/'isolated_warehouse.duckdb')
    get_settings.cache_clear()
    from backend.database import AsyncSessionLocal,engine,init_db
    from backend.models import Chunk,Document,DocumentPage
    if args.retrieval_code_snapshot:
        # Evaluate historical code in a separate process without modifying the
        # current checkout. Only retrieval modules are swapped before agent import.
        import backend.services
        for name in ('retrieval_rank','rag'):
            module_name='backend.services.'+name
            spec=importlib.util.spec_from_file_location(module_name,args.retrieval_code_snapshot/(name+'.py'))
            module=importlib.util.module_from_spec(spec)
            sys.modules[module_name]=module
            setattr(backend.services,name,module)
            spec.loader.exec_module(module)
    from backend.services import rag
    from backend.services.agent import agent_query
    from backend.services.llm import usage,trace_model_calls
    original=rag.get_embedding
    cache={q['question_th']:v.tolist() for q,v in zip(manifest['items'],qvectors)}
    async def cached_embedding(query):
        if query in cache:return cache[query]
        return await original(query)
    rag.get_embedding=cached_embedding
    retrieval=[];answers=[];timings=[];model_call_traces=[]
    n=len(manifest['items'])
    selected={round(i*(n-1)/max(1,args.answer_limit-1)) for i in range(args.answer_limit)}
    save(args.output/'answer_selection.json',{'selection':'equally spaced indices through company-interleaved bank',
        'indices':sorted(selected),'n_answers_planned':len(selected)})
    try:
        await init_db()
        async with AsyncSessionLocal() as db:
            ids={}
            for d in manifest['documents']:
                doc=Document(filename=d['source_file'],doc_type='pdf',status='completed',source_url=d.get('download_url'))
                db.add(doc);await db.flush();ids[d['code']]=doc.id
                db.add_all(DocumentPage(document_id=doc.id,page_number=p,status='indexed')
                    for p in range(1,d['source_page_count']+1))
            db.add_all(Chunk(document_id=ids[c['document']],chunk_index=c['chunk_id'],
                chunk_text=c['text'],embedding=v.tolist(),summary='',token_count=len(c['text'].split()),
                metadata_={'page':c['source_pdf_page'],'source_kind':'semantic'}) for c,v in zip(chunks,vectors))
            await db.commit()
        norm=np.maximum(np.linalg.norm(vectors,axis=1),1e-12)
        for index,item in enumerate(manifest['items']):
            query=item['question_th'];qid=item['id'];meter.phase.update(id=qid,arm='retrieval')
            start=time.perf_counter()
            hits=[chunks[i] for i in bm25.rank(query,10)]
            score=vectors@qvectors[index]/(norm*max(np.linalg.norm(qvectors[index]),1e-12))
            dense=[chunks[int(i)] for i in np.argsort(-score,kind='stable')[:10]]
            debug={} if args.capture_ranking_debug else None
            # Historical snapshots predate ranking_policy. Current code must
            # receive the arm explicitly so benchmark labels cannot silently
            # change when the application's default policy changes.
            search_options=({} if args.retrieval_code_snapshot and
                            args.ranking_policy=='hybrid_current' and debug is None else
                            {'ranking_policy':args.ranking_policy,'ranking_debug':debug})
            async with AsyncSessionLocal() as db:
                app=await rag.vector_search(query,db,top_k=5,**search_options)
            arms={'bm25':[_source(h) for h in hits],
                'dense':[_source(h) for h in dense],
                'app_hybrid':[{'filename':h['filename'],'source_pdf_page':h.get('page')} for h in app]}
            if debug is not None:
                arms['app_keyword']=debug['keyword_pages'][:10]
                arms['app_dense']=debug['semantic_pages'][:10]
            retrieval.append({'id':qid,'arms':arms,**({'ranking_debug':debug} if debug is not None else {})})
            timings.append({'id':qid,'retrieval_seconds':time.perf_counter()-start})
            if index in selected:
                meter.phase.update(id=qid,arm='app_gemini');before=dict(usage);start=time.perf_counter()
                with trace_model_calls() as calls:
                    try:
                        async with AsyncSessionLocal() as db:
                            result=await asyncio.wait_for(agent_query(query,db),180)
                    except Exception as exc:
                        result={'answer':'','sources':[],'error_type':type(exc).__name__}
                model_call_traces.append({'id':qid,'calls':calls,
                    'logical_model_calls':len(calls),
                    'provider_attempts':sum(len(call['attempts']) for call in calls)})
                save(args.output/'model_call_traces.json',model_call_traces)
                answers.append({'id':qid,'answer':result['answer'],'full_result':result,
                    'citations':[{'filename':s.get('filename'),'source_pdf_page':s.get('page')}
                        for s in result.get('sources',[]) if s.get('filename') and s.get('page')]})
                timings[-1].update(agent_seconds=time.perf_counter()-start,
                    usage={k:usage[k]-before[k] for k in usage})
                save(args.output/'app_gemini_answers.json',answers)
            save(args.output/'retrieval.json',retrieval)
            save(args.output/'progress.json',{'completed':len(retrieval),'answers_completed':len(answers)})
            if (index+1)%10==0: print(f'Retrieved {index+1}/{n}; answered {len(answers)}',flush=True)
        answer_ids={r['id'] for r in answers}
        answer_manifest={**manifest,'items':[r for r in manifest['items'] if r['id'] in answer_ids]}
        save(args.output/'answer_reference_locked.json',answer_manifest)
        save(args.output/'metrics.json',{'n_retrieval':len(retrieval),'n_answers':len(answers),
            'embedding_query_mode':'precomputed bge-m3 vectors, exact query keyed; no gold used',
            'retrieval_k':{'bm25':10,'dense':10,'app_hybrid':5},'timings':timings,'usage':dict(usage)})
    finally:
        rag.get_embedding=original;await engine.dispose();await _drop_test_db(base_url,db_name)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--sources',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--component-cache',type=Path,action='append',default=[])
    p.add_argument('--answer-limit',type=int,default=0);p.add_argument('--prepare-only',action='store_true')
    p.add_argument('--query-cache',type=Path,help='Hash-validated query embedding cache for unchanged questions')
    p.add_argument('--retrieval-code-snapshot',type=Path,help='Frozen historical rag.py/retrieval_rank.py for paired diagnostics')
    p.add_argument('--ranking-policy',choices=['hybrid_current','lexical_first'],default='hybrid_current')
    p.add_argument('--capture-ranking-debug',action='store_true')
    args=p.parse_args()
    if args.output.exists() and not args.prepare_only:
        # Permit a prefilled, fingerprint-verified embedding cache. Do not
        # silently overwrite predictions from an earlier benchmark attempt.
        if (args.output/'retrieval.json').exists() or (args.output/'progress.json').exists():
            raise ValueError('Benchmark predictions already exist; use a fresh output directory')
        if not (args.output/'embeddings.npz').exists():
            raise ValueError('Existing output directory has no prepared embedding cache')
    args.output.mkdir(parents=True,exist_ok=True)
    from scripts.experiment_meter import ExperimentMeter
    meter=ExperimentMeter(args.output,capture_context=True);meter.start()
    try:
        sources=load(args.sources);chunks=corpus(sources)
        vectors=prepare_vectors(chunks,args.output,args.component_cache)
        if args.prepare_only:return
        manifest=load(args.reference)
        if not 0<=args.answer_limit<=len(manifest['items']):raise ValueError('Invalid answer limit')
        if args.query_cache:
            shutil.copyfile(args.query_cache,args.output/'query_vectors.npz')
        save(args.output/'reference_locked.json',manifest)
        save(args.output/'inference_code_lock.json',{'recorded_before_inference':True,
            'ranking_policy':args.ranking_policy,'capture_ranking_debug':args.capture_ranking_debug,
            'code_sha256':{name:sha(name) for name in ('scripts/benchmark_large_retrieval.py',
                'backend/services/rag.py','backend/services/retrieval_rank.py')},
            'retrieval_snapshot_sha256':{name:sha(args.retrieval_code_snapshot/(name+'.py'))
                for name in ('rag','retrieval_rank')} if args.retrieval_code_snapshot else None,
            'label_scope':'Diagnostic reports, not unseen validation'})
        save(args.output/'input_hashes.json',{'reference':sha(args.reference),'sources':sha(args.sources),
            'pdfs':{d['code']:sha(d['path']) for d in sources['documents']},
            'embeddings':sha(args.output/'embeddings.npz')})
        qvectors=_embed_texts([r['question_th'] for r in manifest['items']],'bge-m3',args.output/'query_vectors.npz')
        bm25=BM25([r['text'] for r in chunks],thai_words=True)
        asyncio.run(run(args,manifest,chunks,vectors,qvectors,bm25,meter))
    finally:meter.finish()

if __name__=='__main__':main()
