"""Fair local retrieval comparison on an explicit frozen corpus and query cache.

BM25/dense are unscoped legacy baselines; the two app arms use production scope
and ranking. Differences are system comparisons, not fusion-only ablations.
"""
import argparse
import asyncio
import os
from pathlib import Path
import numpy as np
from sqlalchemy.engine import make_url
from scripts.evaluate_comprehensive import load, save, sha
from scripts.run_capture_paired import fingerprint
from scripts.benchmark_long_document import _create_test_db
from scripts.benchmark_heldout import BM25, _source
from scripts.score_paired_retrieval_v4 import metrics


async def run(a):
    bank,chunks=load(a.reference),load(a.corpus)
    with np.load(a.embedding_cache) as cached:
        if str(cached['fingerprint'])!=fingerprint([c['text'] for c in chunks]):raise ValueError('Corpus cache mismatch')
        vectors=cached['vectors'].copy()
    with np.load(a.query_cache) as cached:
        if str(cached['fingerprint'])!=fingerprint([q['question_th'] for q in bank['items']]):raise ValueError('Query cache mismatch')
        queries=cached['vectors'].copy()
    from backend.config import get_settings
    base=get_settings().DATABASE_URL;name=f'ragdb_frozen_retrieval_{os.getpid()}'
    await _create_test_db(base,name)
    url=make_url(base).set(database=name)
    os.environ['DATABASE_URL']=url.render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC']=url.set(drivername='postgresql').render_as_string(hide_password=False)
    os.environ['DUCKDB_PATH']=str((a.output/'unused_warehouse.duckdb').resolve())
    get_settings.cache_clear()
    from backend.database import AsyncSessionLocal,init_db,engine
    from backend.models import Document,DocumentPage,Chunk
    from backend.services import rag
    cache={q['question_th']:v.tolist() for q,v in zip(bank['items'],queries)}
    async def exact_query(query):
        if query not in cache:raise ValueError('Unfrozen query prohibited')
        return cache[query]
    original_embedding=rag.get_embedding;rag.get_embedding=exact_query
    a.output.mkdir(parents=True,exist_ok=False)
    code=['scripts/retrieval_frozen_corpus.py','backend/services/rag.py','backend/services/retrieval_rank.py']
    save(a.output/'manifest.json',{'database':name,'database_retained':True,'production_database_touched':False,
        'new_sdk_attempts':0,'inputs_sha256':{str(p):sha(p) for p in (a.reference,a.corpus,a.embedding_cache,a.query_cache)},
        'code_sha256':{p:sha(p) for p in code},'inference_inputs':'Only question and explicit corpus; no qrels/reference used by retrieval',
        'arms':'unscoped BM25/dense vs scoped app policies; system comparison, not fusion-only ablation'})
    records=[]
    try:
        await init_db()
        async with AsyncSessionLocal() as db:
            ids={};docs={d['code']:d for d in bank['documents']}
            for d in docs.values():
                doc=Document(filename=d['source_file'],source_sha256=d['source_sha256'],status='completed',doc_type='pdf')
                db.add(doc);await db.flush();ids[d['code']]=doc.id
                db.add_all(DocumentPage(document_id=doc.id,page_number=p,status='indexed')
                    for p in range(1,d['source_page_count']+1))
            db.add_all(Chunk(document_id=ids[c['document']],chunk_index=c['chunk_id'],chunk_text=c['text'],
                embedding=v.tolist(),summary='',metadata_={**c.get('metadata',{}),'page':c['source_pdf_page'],
                    'source_kind':c.get('source_kind','semantic'),'source_sha256':docs[c['document']]['source_sha256']})
                for c,v in zip(chunks,vectors))
            await db.commit()
        bm25=BM25([c['text'] for c in chunks]);norm=np.maximum(np.linalg.norm(vectors,axis=1),1e-12)
        for i,q in enumerate(bank['items']):
            score=vectors@queries[i]/(norm*max(np.linalg.norm(queries[i]),1e-12))
            arms={'bm25':[_source(chunks[j]) for j in bm25.rank(q['question_th'],10)],
                  'dense':[_source(chunks[int(j)]) for j in np.argsort(-score,kind='stable')[:10]]}
            debug={};evidence={}
            for policy in ('hybrid_current','lexical_first'):
                debug[policy]={}
                async with AsyncSessionLocal() as db:
                    hits=await rag.vector_search(q['question_th'],db,top_k=5,ranking_policy=policy,ranking_debug=debug[policy])
                arms[policy]=[{'filename':h['filename'],'source_pdf_page':h.get('page')} for h in hits]
                evidence[policy]=hits
            records.append({'id':q['id'],'arms':arms,'debug':debug,'retrieved_evidence':evidence})
            save(a.output/'retrieval.json',records)
            if (i+1)%25==0:print(f'Frozen retrieval {i+1}/{len(bank["items"])}',flush=True)
        _,summary=metrics(bank,records)
        save(a.output/'summary.json',summary)
    finally:
        rag.get_embedding=original_embedding;await engine.dispose()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','corpus','embedding-cache','query-cache','output'):p.add_argument('--'+name,type=Path,required=True)
    asyncio.run(run(p.parse_args()))


if __name__=='__main__':main()
