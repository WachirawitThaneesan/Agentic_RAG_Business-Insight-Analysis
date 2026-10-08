"""Bounded native-text paired app capture; no labels are sent to generation.

Both existing ranking policies share frozen questions, corpus, schema and
scorer. A 20-pair smoke never silently expands when capture coverage fails.
"""
import argparse
import asyncio
from collections import Counter
from copy import deepcopy
import datetime
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
from sqlalchemy.engine import make_url

from scripts.evaluate_comprehensive import load, save, sha


def fingerprint(texts):
    return hashlib.sha256(('bge-m3\n'+'\n'.join(texts)).encode()).hexdigest()


def summarize(records, labels, registry, planned, planned_ids=None, arms=None, answerable_ids=None, scope='development'):
    from backend.eval.contract_replay import numeric_results
    from backend.eval.comprehensive import is_abstention, fraction
    from backend.services.answer_capture import validate_binding
    arms = tuple(arms or ('hybrid_current', 'lexical_first'))
    summary = {'n_planned_pairs': planned, 'n_pairs_with_records': len(records),
               'n_completed_pairs': sum(len(r['arms']) == len(arms) and all(
                   not o['full_result'].get('error_type') and not any(c.get('status') in ('error', 'cancelled')
                       for c in o.get('model_calls', [])) for o in r['arms'].values()) for r in records),
               'scope': scope+'; frozen corpus representation recorded in manifest; actual full agent',
               'human_confirmed': False, 'arms': {}, 'regressions': [], 'recoveries': []}
    for arm in arms:
        outputs = [row['arms'][arm] for row in records if arm in row['arms']]
        captured = [r for r in outputs if r['full_result'].get('answer_capture', {}).get('status') == 'captured'
                    and r['full_result']['answer_capture'].get('claims_cover_answer')
                    and validate_binding(r['full_result'], r['answer'])]
        numeric = []
        for row in records:
            if arm not in row['arms']:
                continue
            output = row['arms'][arm]
            selected = [label for label in labels if label['id'] == row['id']]
            numeric.extend(numeric_results(selected, output['full_result'], output['answer'],
                                            allow_provisional=True, document_registry=registry))
        measurable = [n for n in numeric if n['correct'] is not None]
        started_ids = {r['id'] for r in records if arm in r['arms']}
        n_started_tuples = len(numeric)
        if planned_ids is not None:
            numeric += [{'quantity_index': label['quantity_index'], 'correct': None, 'state': 'question_not_started'}
                        for label in labels if label['id'] in planned_ids and label['id'] not in started_ids]
        summary['arms'][arm] = {
            'n_outputs': len(outputs), 'n_missing_outputs': planned-len(outputs),
            'n_captured_complete_prose': len(captured),
            'capture_coverage': fraction(len(captured), planned),
            'n_actual_citation_links': sum(len(r['full_result'].get('claim_citations') or []) for r in outputs),
            'n_claims_without_citation': sum(sum(not any(link['claim_index'] == i for link in
                (r['full_result'].get('claim_citations') or [])) for i, _ in enumerate(
                    r['full_result'].get('answer_claims') or [])) for r in captured),
            'capture_statuses': dict(Counter(r['full_result'].get('answer_capture', {}).get('status', 'missing') for r in outputs)),
            'n_errors': sum(bool(r.get('error_type') or r['full_result'].get('error_type')
                                or any(c.get('status') in ('error', 'cancelled') for c in r.get('model_calls', []))) for r in outputs),
            'n_refusals': sum(is_abstention(r['answer']) for r in outputs),
            'answer_coverage': fraction(sum(bool(r['answer'].strip()) and not is_abstention(r['answer'])
                and not r['full_result'].get('error_type') for r in outputs), planned),
            'numeric': {'n_required': len(numeric), 'n_measurable': len(measurable),
                        'n_required_tuples_in_started_subset': n_started_tuples,
                        'coverage': fraction(len(measurable), len(numeric)),
                        'n_correct': sum(n['correct'] is True for n in measurable),
                        'accuracy_measured_subset': fraction(sum(n['correct'] is True for n in measurable), len(measurable)),
                        'states': dict(Counter(n['state'] for n in numeric))},
            'actual_citation_precision': None, 'complete_answer_success': None,
            'limit': 'Capture is structural binding; citation entailment/factual audit not yet performed.'}
        if answerable_ids is not None:
            positives=[r for r in outputs if r['id'] in answerable_ids]
            negatives=[r for r in outputs if r['id'] not in answerable_ids]
            summary['arms'][arm]['answerable_control_breakdown']={
                'n_answerable_planned':len(answerable_ids),'n_unanswerable_planned':planned-len(answerable_ids),
                'n_answerable_nonrefusal':sum(bool(r['answer'].strip()) and not is_abstention(r['answer']) for r in positives),
                'n_false_refusals_on_answerable':sum(is_abstention(r['answer']) for r in positives),
                'n_control_refusals':sum(is_abstention(r['answer']) for r in negatives),
                'answer_coverage_answerable':fraction(sum(bool(r['answer'].strip()) and not is_abstention(r['answer']) for r in positives),len(answerable_ids))}
    for row in records:
        if not all(a in row['arms'] for a in ('hybrid_current', 'lexical_first')):
            continue
        states = [row['arms'][a]['full_result'].get('answer_capture', {}).get('status') == 'captured'
                  and not is_abstention(row['arms'][a]['answer']) for a in ('hybrid_current', 'lexical_first')]
        if states == [True, False]: summary['regressions'].append(row['id'])
        if states == [False, True]: summary['recoveries'].append(row['id'])
    summary['regression_scope'] = 'Captured/non-refusal transitions only; not factual accuracy delta'
    summary['ready_for_50_capture_gate'] = all(
        a['capture_coverage'] is not None and a['capture_coverage'] >= .95
        and a['n_claims_without_citation'] == 0
        and (a['numeric']['coverage'] is None or a['numeric']['coverage'] >= .95)
        for a in summary['arms'].values()) and len(records) == planned
    summary['ready_for_expansion_beyond_50'] = False
    return summary


def distinct_page_indices(chunks, indices, top_k):
    """Legacy baselines use the same physical-page evidence budget as app arms."""
    selected=[];seen=set()
    if top_k<1:return selected
    for index in indices:
        c=chunks[int(index)];key=(c['document'],c['source_pdf_page'])
        if key in seen:continue
        selected.append(int(index));seen.add(key)
        if len(selected)>=top_k:break
    return selected


async def run(args, bank, chunks, vectors, queries, selected, labels):
    from backend.config import get_settings
    from scripts.benchmark_long_document import _create_test_db
    settings = get_settings()
    if settings.OFFLINE_MODE or settings.LLM_PROVIDER != 'gemini':
        raise ValueError('Requires configured Gemini online provider')
    base_url = settings.DATABASE_URL
    resumed=load(args.output/'isolated_storage.json') if getattr(args,'resume',False) else None
    db_name = resumed['database'] if resumed else f'ragdb_capture_paired_{os.getpid()}'
    if resumed:
        import re
        if not re.fullmatch(r'ragdb_capture_paired_\d+',db_name):raise ValueError('Resume database outside owned run')
    else:
        await _create_test_db(base_url, db_name)
    url = make_url(base_url).set(database=db_name)
    os.environ['DATABASE_URL'] = url.render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC'] = url.set(drivername='postgresql').render_as_string(hide_password=False)
    os.environ['DUCKDB_PATH'] = str(args.output/'isolated_warehouse.duckdb')
    get_settings.cache_clear()
    from backend.database import AsyncSessionLocal, engine, init_db
    from backend.models import Chunk, Document, DocumentPage
    from backend.services import rag, agent, graph_service
    from backend.services.llm import trace_model_calls
    from scripts.bounded_cloud_meter import BoundedCloudMeter
    original_embedding, original_search, original_graphs = rag.get_embedding, rag.vector_search, graph_service.list_all_graphs
    original_agent_query = agent._agent_query
    query_cache = {q['question_th']: v.tolist() for q, v in zip(bank['items'], queries)}
    followup_vectors={}
    if resumed and (args.output/'followup_query_vectors.json').exists():
        prior=load(args.output/'followup_query_vectors.json')
        if prior['model']!=settings.EMBED_MODEL:raise ValueError('Follow-up model changed')
        followup_vectors=prior['queries']
        if any(len(v)!=vectors.shape[1] for v in followup_vectors.values()):raise ValueError('Follow-up cache dimension mismatch')
        query_cache.update(followup_vectors)
    async def cached(query):
        if query not in query_cache:
            # Real agent search repairs may reword a query. Preserve/cache the
            # locally generated follow-up vector, without reading any labels.
            vector=await original_embedding(query)
            if len(vector)!=vectors.shape[1]:raise ValueError('Follow-up embedding dimension mismatch')
            query_cache[query]=list(vector)
            followup_vectors[query]=list(vector)
            save(args.output/'followup_query_vectors.json',{'model':settings.EMBED_MODEL,
                'scope':'Actual inference-generated follow-up queries; initial frozen vectors unchanged',
                'queries':followup_vectors})
        return query_cache[query]
    rag.get_embedding = cached
    graph_service.list_all_graphs = lambda: []
    save(args.output/'isolated_storage.json', {'database': db_name, 'production_database_touched': False,
        'retained': True, 'duckdb': str(args.output/'isolated_warehouse.duckdb')})
    save(args.output/'model_configuration.json', {key:getattr(settings,key) for key in
        ('LLM_PROVIDER','GEMINI_MODEL','GEMINI_THINKING_BUDGET','EMBED_MODEL','OFFLINE_MODE')})
    records = load(args.output/'paired_answers.json') if resumed else []
    if [r['id'] for r in records]!=[q['id'] for q in selected[:len(records)]]:
        raise ValueError('Resume records do not match frozen selection prefix')
    policies = tuple(getattr(args,'ranking_policies',None) or ('hybrid_current','lexical_first'))
    answerable_ids={q['id'] for q in selected if q.get('answerable',True)}
    try:
        await init_db()
        async with AsyncSessionLocal() as db:
            ids = {}
            from sqlalchemy import select
            if resumed:
                stored=(await db.execute(select(Document))).scalars().all()
                byname={d.filename:d for d in stored}
                if len(stored)!=len(bank['documents']):raise ValueError('Resume registry changed')
                for doc in bank['documents']:
                    item=byname[doc['source_file']]
                    if item.source_sha256!=doc['source_sha256']:raise ValueError('Resume source hash changed')
                    ids[doc['code']]=item.id
                text_rows=(await db.execute(select(Chunk.chunk_index,Chunk.chunk_text).order_by(Chunk.chunk_index))).all()
                if [(i,t) for i,t in text_rows]!=[(c['chunk_id'],c['text']) for c in chunks]:raise ValueError('Resume corpus changed')
            else:
                for doc in bank['documents']:
                    item = Document(filename=doc['source_file'], doc_type='pdf', status='completed', source_url=doc.get('download_url'), source_sha256=doc['source_sha256'])
                    db.add(item); await db.flush(); ids[doc['code']] = item.id
                    db.add_all(DocumentPage(document_id=item.id, page_number=i, status='indexed')
                               for i in range(1, doc['source_page_count']+1))
                db.add_all(Chunk(document_id=ids[c['document']], chunk_index=c['chunk_id'], chunk_text=c['text'],
                    embedding=v.tolist(), summary='', token_count=len(c['text'].split()),
                    metadata_={**c.get('metadata', {}), 'page': c['source_pdf_page'], 'source_kind': c.get('source_kind', 'semantic'),
                        'source_sha256': next(d['source_sha256'] for d in bank['documents'] if d['code']==c['document'])}) for c, v in zip(chunks, vectors))
                await db.commit()
            chunk_ids=dict((await db.execute(select(Chunk.chunk_index,Chunk.id))).all())
        from scripts.benchmark_heldout import BM25
        from backend.services.retrieval_rank import normalize_search_text
        bm25=BM25([c['text'] for c in chunks]) if 'bm25' in policies else None
        bm25_thai=BM25([normalize_search_text(c['text']) for c in chunks],thai_words=True) if 'bm25_thai' in policies else None
        norms=np.maximum(np.linalg.norm(vectors,axis=1),1e-12)

        async def baseline_search(query,session,policy,top_k=5):
            if policy in ('bm25','bm25_thai'):
                ranker=bm25 if policy=='bm25' else bm25_thai
                rank_query=query if policy=='bm25' else normalize_search_text(query)
                ranking=ranker.rank(rank_query,len(chunks));similarities=None
            else:
                qv=np.asarray(await cached(query));similarities=vectors@qv/(norms*max(np.linalg.norm(qv),1e-12))
                ranking=np.argsort(-similarities,kind='stable')
            selected_indices=distinct_page_indices(chunks,ranking,top_k)
            documents={d['code']:d for d in bank['documents']}
            hits=[]
            for index in selected_indices:
                c=chunks[index];meta=c.get('metadata',{});doc=documents[c['document']]
                hits.append({'chunk_id':chunk_ids[c['chunk_id']],'text':c['text'],'summary':'',
                    'chunk_index':c['chunk_id'],'document_id':ids[c['document']],'filename':c['filename'],
                    'source_sha256':doc['source_sha256'],'page':c['source_pdf_page'],
                    'similarity':float(similarities[index]) if similarities is not None else None,
                    'retrieval_method':policy,'source_kind':c.get('source_kind','semantic'),
                    'table_name':meta.get('table_name'),'quality_status':meta.get('quality_status'),
                    'evidence_status':'source_text_unverified'})
            return await rag._expand_page_evidence(query,hits,session)

        async def simple_rag_query(question, session):
            hits = await baseline_search(question, session, 'dense', settings.VECTOR_TOP_K)
            sources = agent._extract_sources('vector_search', {'chunks': hits})
            answer = await agent._answer_from_observations(question,
                [h['text'] for h in hits], sources)
            return {'answer': answer, 'sources': sources, 'method': 'simple_dense_rag',
                    'sql_info': None, 'reasoning_trace': [{'action': 'vector_search',
                        'action_input': question, 'success': bool(hits),
                        'observation': 'One frozen dense retrieval; no agent planning or search repair'}]}
        with BoundedCloudMeter(args.budget, args.output, max_new_attempts=args.max_new_attempts) as meter:
            for i, question in enumerate(selected):
                row=next((r for r in records if r['id']==question['id']),None)
                if row is None:
                    row = {'id': question['id'], 'arms': {}}
                    records.append(row)
                # Counterbalance execution order without changing questions/scorer.
                # Latin rotation distributes time/order across any frozen arm set.
                shift=i%len(policies);order=policies[shift:]+policies[:shift]
                for policy in order:
                    if policy in row['arms']:continue
                    async def scoped_search(query, session, **kwargs):
                        if policy in ('bm25','bm25_thai','dense'):
                            return await baseline_search(query,session,policy,kwargs.get('top_k',5))
                        return await original_search(query, session, **{**kwargs, 'ranking_policy': policy})
                    rag.vector_search = scoped_search
                    agent._agent_query = simple_rag_query if policy == 'simple_rag' else original_agent_query
                    meter.phase.update(stage='paired_answer', id=question['id'], arm=policy)
                    started = time.perf_counter()
                    with trace_model_calls() as calls:
                        try:
                            async with AsyncSessionLocal() as db:
                                full = await asyncio.wait_for(agent.agent_query(question['question_th'], db), 180)
                        except Exception as exc:
                            full = {'answer': '', 'sources': [], 'error_type': type(exc).__name__}
                    row['arms'][policy] = {'id': question['id'], 'answer': full['answer'], 'full_result': full,
                        'seconds': time.perf_counter()-started, 'model_calls': calls}
                    save(args.output/'paired_answers.json', records)
                    save(args.output/'summary.json', summarize(records, labels, bank['documents'], len(selected),
                                                               planned_ids=[q['id'] for q in selected],arms=policies,
                                                               answerable_ids=answerable_ids,scope=args.evaluation_scope))
                    print(f'Paired {i+1}/{len(selected)} {question["id"]} {policy}: {full.get("answer_capture", {}).get("status", "error")}', flush=True)
                from scripts.bounded_cloud_meter import BudgetExhausted
                try:
                    meter.check_capacity()
                except BudgetExhausted as exc:
                    save(args.output/'stopped.json', {'reason': str(exc), 'remaining_questions': len(selected)-i-1})
                    break
                stop_after=getattr(args,'stop_after_pairs',None)
                if stop_after is not None and i+1>=stop_after:
                    save(args.output/'PREFIX_REVIEW_CHECKPOINT.json',{
                        'n_completed_prefix_pairs':i+1,'n_planned_pairs':len(selected),
                        'reason':'Preregistered prefix review; remaining frozen questions remain planned; no completed outcome retried',
                        'resume_requires_unchanged_frozen_application':True})
                    break
    finally:
        rag.get_embedding, rag.vector_search = original_embedding, original_search
        graph_service.list_all_graphs = original_graphs
        agent._agent_query = original_agent_query
        await engine.dispose()
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('reference', 'labels', 'pdf_paths', 'embedding_cache', 'query_cache', 'selection_answers', 'budget', 'output'):
        parser.add_argument('--'+name.replace('_', '-'), type=Path, required=True)
    parser.add_argument('--max-new-attempts', type=int, default=None,
                        help='Optional run cap; global ledger limits always remain applicable')
    parser.add_argument('--expected-pairs', type=int, default=20, help='Explicit frozen selection size; no silent expansion')
    parser.add_argument('--corpus-json', type=Path, help='Explicit frozen alternative corpus; original PDF/page provenance must be preserved')
    parser.add_argument('--ranking-policies', nargs='+',choices=['bm25','bm25_thai','dense','simple_rag','hybrid_current','lexical_first'],
                        default=['hybrid_current','lexical_first'])
    parser.add_argument('--evaluation-scope',choices=['development','new_issuer_final'],default='development')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--resume',action='store_true',help='Continue only missing arms from the same frozen run/owned DB')
    parser.add_argument('--stop-after-pairs',type=int,help='Pause at an explicit prefix boundary for review; full manifest selection and denominators remain unchanged')
    args = parser.parse_args()
    if args.max_new_attempts is not None and args.max_new_attempts < 1: raise ValueError('Attempt cap must be positive')
    if args.output.exists() and not args.resume: raise ValueError('Preserve existing experiment; choose a new output path')
    if args.resume and not args.output.exists():raise ValueError('Resume requires an existing run')
    if len(args.ranking_policies)!=len(set(args.ranking_policies)):raise ValueError('Duplicate ranking policy')
    bank, labels = load(args.reference), load(args.labels)
    ids = [r['id'] for r in load(args.selection_answers)]
    if len(ids) != args.expected_pairs or len(set(ids)) != args.expected_pairs or args.expected_pairs < 1:
        raise ValueError('Selection must match explicit planned pair count with unique IDs')
    by_id = {q['id']: q for q in bank['items']}
    selected = [by_id[qid] for qid in ids]
    paths = load(args.pdf_paths)
    sources = {'documents': [{**d, 'path': paths[d['code']]} for d in bank['documents']]}
    for doc in sources['documents']:
        if sha(Path(doc['path'])) != doc['source_sha256']: raise ValueError('PDF hash mismatch')
    budget = load(args.budget)
    if args.run and budget.get('deadline_local') and datetime.datetime.now(datetime.timezone.utc) >= datetime.datetime.fromisoformat(budget['deadline_local']):
        raise ValueError('Original deadline reached; no new cloud experiment')
    from scripts.benchmark_large_retrieval import corpus
    chunks = load(args.corpus_json) if args.corpus_json else corpus(sources)
    registry = {d['code']:d for d in bank['documents']}
    if len({c['chunk_id'] for c in chunks}) != len(chunks): raise ValueError('Duplicate corpus chunk ID')
    for chunk in chunks:
        if chunk.get('source_kind') not in (None,'semantic','table_csv'):
            raise ValueError('Frozen corpus includes ineligible audit/quality evidence')
        doc = registry[chunk['document']]
        if not 1 <= chunk['source_pdf_page'] <= doc['source_page_count']: raise ValueError('Invalid corpus source page')
        if chunk.get('filename') != doc['source_file']: raise ValueError('Corpus source filename differs from PDF registry')
    with np.load(args.embedding_cache) as cache:
        if str(cache['fingerprint']) != fingerprint([c['text'] for c in chunks]): raise ValueError('Corpus cache fingerprint mismatch')
        vectors = cache['vectors']
    with np.load(args.query_cache) as cache:
        if str(cache['fingerprint']) != fingerprint([q['question_th'] for q in bank['items']]): raise ValueError('Query cache fingerprint mismatch')
        queries = cache['vectors']
    if args.resume:
        old=load(args.output/'manifest.json')
        expected={str(getattr(args,name)):sha(getattr(args,name)) for name in
            ('reference','labels','pdf_paths','embedding_cache','query_cache','selection_answers')}
        if old['inputs_sha256']!=expected or old['selected_ids']!=ids or old['arms']!=args.ranking_policies:
            raise ValueError('Frozen resume inputs/selection/policies changed')
        if old.get('alternative_corpus_sha256')!=(sha(args.corpus_json) if args.corpus_json else None):raise ValueError('Frozen corpus changed')
        for name,digest in old['code_sha256'].items():
            if name.startswith('backend/') and sha(name)!=digest:raise ValueError('Frozen application/scorer changed: '+name)
        save(args.output/f'resume_{os.getpid()}.json',{'original_manifest_sha256':sha(args.output/'manifest.json'),
            'reason':'Operational checkpoint I/O recovery; unchanged app/scorer/labels/corpus and inference conditions',
            'driver_sha256':sha(__file__),'save_helper_sha256':sha('scripts/evaluate_comprehensive.py'),
            'already_saved_outputs':sum(len(r['arms']) for r in load(args.output/'paired_answers.json'))})
        records=asyncio.run(run(args,bank,chunks,vectors,queries,selected,labels))
        for arm in args.ranking_policies:save(args.output/(arm+'_answers.json'),[r['arms'][arm] for r in records if arm in r['arms']])
        save(args.output/'summary.json',summarize(records,labels,bank['documents'],len(selected),planned_ids=ids,
            arms=args.ranking_policies,answerable_ids={q['id'] for q in selected if q.get('answerable',True)},scope=args.evaluation_scope))
        return
    args.output.mkdir(parents=True)
    root = Path(__file__).resolve().parents[1]
    code = ['backend/services/agent.py', 'backend/services/answer_capture.py', 'backend/services/rag.py',
            'backend/services/retrieval_rank.py', 'backend/services/llm.py', 'backend/eval/contracts.py',
            'backend/eval/contract_replay.py', 'backend/eval/comprehensive.py', 'scripts/run_capture_paired.py',
            'scripts/bounded_cloud_meter.py', 'backend/services/tools.py', 'backend/models.py', 'backend/database.py']
    code += ['backend/services/embedding.py', 'backend/services/chunker.py']
    code += ['scripts/benchmark_heldout.py', 'backend/eval/numeric.py',
             'backend/eval/score_layers.py', 'backend/services/answer_verifier.py',
             'scripts/evaluate_comprehensive.py']
    for name in code:
        target = args.output/'frozen_code'/name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root/name).read_bytes())
    save(args.output/'manifest.json', {'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'code_sha256': {name: sha(root/name) for name in code},
        'inputs_sha256': {str(getattr(args, name)): sha(getattr(args, name)) for name in
            ('reference', 'labels', 'pdf_paths', 'embedding_cache', 'query_cache', 'selection_answers')},
        'alternative_corpus_sha256': sha(args.corpus_json) if args.corpus_json else None,
        'alternative_corpus_path': str(args.corpus_json) if args.corpus_json else None,
        'pdfs_sha256': {d['code']: d['source_sha256'] for d in bank['documents']},
        'selected_ids': ids, 'arms': args.ranking_policies, 'same_generator_and_scorer': True,
        'evaluation_scope':args.evaluation_scope,
        'baseline_conditions':'bm25:legacy unscoped regex; bm25_thai:normalized Thai word-tokenized unscoped keyword; dense:unscoped cosine; app arms include company scope. Full-agent baselines share the configured retrieval budget; simple_rag uses one dense retrieval at that same configured budget and the same generator/capture. All share corpus, page expansion and context budget; system comparison, not fusion-only ablation',
        'retrieval_page_budget_configured':__import__('backend.config',fromlist=['get_settings']).get_settings().VECTOR_TOP_K,
        'max_new_attempts': args.max_new_attempts, 'original_budget': budget,
        'n_chunks': len(chunks), 'human_confirmed': False,
        'scope': ('New issuer final transfer test; full native report text; not full-report production OCR' if args.evaluation_scope=='new_issuer_final' else
                 'Development mixed native and recorded production OCR; explicit original-page map; not full-report production ingestion'
                  if args.corpus_json else 'Development native text; no OCR, unseen or production DB inference; no new ranking config')})
    save(args.output/'reference_locked.json', bank)
    save(args.output/'numeric_labels_locked.json', labels)
    if args.run:
        records = asyncio.run(run(args, bank, chunks, vectors, queries, selected, labels))
        for arm in args.ranking_policies:
            save(args.output/(arm+'_answers.json'), [r['arms'][arm] for r in records if arm in r['arms']])
        save(args.output/'summary.json', summarize(records, labels, bank['documents'], len(selected), planned_ids=ids,
            arms=args.ranking_policies,answerable_ids={q['id'] for q in selected if q.get('answerable',True)},scope=args.evaluation_scope))
    else:
        save(args.output/'preflight.json', {'passed': True, 'sdk_attempts': 0, 'n_selected': len(selected)})


if __name__ == '__main__':
    main()
