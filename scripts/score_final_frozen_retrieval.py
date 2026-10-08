"""Read-only ranking measurement on the exact final corpus/cache; zero cloud calls."""
import asyncio
import os
from pathlib import Path
import numpy as np
from sqlalchemy.engine import make_url

from backend.eval.comprehensive import page_metrics,wilson
from scripts.evaluate_comprehensive import load,save,sha
from scripts.run_capture_paired import fingerprint,distinct_page_indices

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'TestFile/evaluation_completion_2026-10-07/final_retrieval'
OLD=Path(r'C:\Users\nonga\Documents\Codex\2026-10-05\step2-rag-evaluation-continuation\outputs\plan_completion_authorized_v1')


async def run():
    from backend.config import get_settings
    from scripts.benchmark_long_document import _create_test_db
    from scripts.benchmark_heldout import BM25
    from backend.services.retrieval_rank import normalize_search_text
    bank=load(OLD/'heldout_fact_dedup_v4/reference_locked.json')
    chunks=load(OLD/'heldout_native_corpus_prepared/corpus.json')
    with np.load(OLD/'heldout_native_corpus_prepared/embeddings.npz') as cache:
        if str(cache['fingerprint'])!=fingerprint([c['text'] for c in chunks]):raise ValueError('Corpus cache mismatch')
        vectors=cache['vectors']
    with np.load(OLD/'heldout_fact_dedup_v4/query_vectors.npz') as cache:
        if str(cache['fingerprint'])!=fingerprint([q['question_th'] for q in bank['items']]):raise ValueError('Query cache mismatch')
        queries=cache['vectors']
    OUT.mkdir(exist_ok=False)
    base=get_settings().DATABASE_URL;name=f'ragdb_final_retrieval_{os.getpid()}'
    await _create_test_db(base,name)
    url=make_url(base).set(database=name)
    os.environ['DATABASE_URL']=url.render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC']=url.set(drivername='postgresql').render_as_string(hide_password=False)
    os.environ['DUCKDB_PATH']=str(OUT/'warehouse.duckdb');get_settings.cache_clear()
    from backend.database import AsyncSessionLocal,engine,init_db
    from backend.models import Chunk,Document,DocumentPage
    from backend.services import rag
    await init_db()
    query_cache={q['question_th']:v.tolist() for q,v in zip(bank['items'],queries)}
    original=rag.get_embedding
    async def cached(query):return query_cache[query]
    rag.get_embedding=cached
    try:
        async with AsyncSessionLocal() as db:
            ids={}
            for doc in bank['documents']:
                d=Document(filename=doc['source_file'],doc_type='pdf',status='completed',source_sha256=doc['source_sha256'])
                db.add(d);await db.flush();ids[doc['code']]=d.id
                db.add_all(DocumentPage(document_id=d.id,page_number=p,status='indexed') for p in range(1,doc['source_page_count']+1))
            db.add_all(Chunk(document_id=ids[c['document']],chunk_index=c['chunk_id'],chunk_text=c['text'],
                embedding=v.tolist(),summary='',token_count=len(c['text'].split()),metadata_={**c.get('metadata',{}),
                    'page':c['source_pdf_page'],'source_kind':c.get('source_kind','semantic')}) for c,v in zip(chunks,vectors))
            await db.commit()
        ranker=BM25([normalize_search_text(c['text']) for c in chunks],thai_words=True)
        norms=np.maximum(np.linalg.norm(vectors,axis=1),1e-12)
        docs={d['code']:d for d in bank['documents']};rows=[];raw=[]
        for qi,q in enumerate(bank['items']):
            if not q.get('answerable',True):continue
            order=ranker.rank(normalize_search_text(q['question_th']),len(chunks))
            keywords=[chunks[i] for i in distinct_page_indices(chunks,order,10)]
            score=vectors@queries[qi]/(norms*max(np.linalg.norm(queries[qi]),1e-12))
            dense=[chunks[i] for i in distinct_page_indices(chunks,np.argsort(-score,kind='stable'),10)]
            async with AsyncSessionLocal() as db:improved=await rag.vector_search(q['question_th'],db,top_k=10,ranking_policy='lexical_first')
            def source(c):return {'filename':c['filename'],'source_pdf_page':c.get('source_pdf_page',c.get('page'))}
            arms={'bm25_thai':[source(c) for c in keywords],'dense':[source(c) for c in dense],
                'simple_rag':[source(c) for c in dense],'lexical_first':[source(c) for c in improved]}
            raw.append({'id':q['id'],'arms':arms})
            for arm,hits in arms.items():
                for k in [1,3,5,10]:rows.append({'id':q['id'],'document':q['document'],'arm':arm,
                    **page_metrics(q,hits,docs,k=k,depth=10)})
            save(OUT/'retrieval.json',raw)
            if len(raw)%20==0:print('Frozen retrieval',len(raw),'/118',flush=True)
        summary={}
        for arm in arms:
            for k in [1,3,5,10]:
                part=[r for r in rows if r['arm']==arm and r['k']==k];n=len(part);hits=sum(r['hit'] for r in part)
                summary[f'{arm}@{k}']={'n':n,'hits':hits,'hit_rate':hits/n,'hit_wilson95':wilson(hits,n),
                    **{'mean_'+key:sum(r[key] for r in part)/n for key in ['recall','precision','mrr','ndcg','complete_evidence']}}
        save(OUT/'details.json',rows);save(OUT/'summary.json',summary)
        save(OUT/'method_lock.json',{'reference_sha256':sha(OLD/'heldout_fact_dedup_v4/reference_locked.json'),
            'corpus_sha256':sha(OLD/'heldout_native_corpus_prepared/corpus.json'),'code_sha256':sha(__file__),
            'database':name,'sdk_attempts':0,'n_controls_excluded':15,
            'scope':'Initial-query retrieval only, frozen corpus and rankers; independent of later agent tool calls; incomplete page qrels limit precision/nDCG'})
    finally:rag.get_embedding=original;await engine.dispose()
    print('Frozen final retrieval scored; zero cloud calls')


if __name__=='__main__':asyncio.run(run())
