"""Fresh answer-only comparison on an existing isolated ingestion DB.

No upload, resume API, OCR or reference labels are involved. Saved prefix
answers are retained; each continuation uses a separate actual-call journal.
"""
import argparse
import asyncio
import os
from pathlib import Path
import re
import time
from sqlalchemy.engine import make_url
from scripts.evaluate_comprehensive import load, save, sha


async def run(a):
    from backend.config import get_settings
    manifest=load(a.source/'run_manifest.json')
    plan=load(a.source/'plan_locked.json')
    name=manifest['database_name']
    if not re.fullmatch(r'ragdb_ingest_smoke_v4_\d+',name):raise ValueError('Not an owned staging database')
    url=make_url(get_settings().DATABASE_URL).set(database=name)
    os.environ['DATABASE_URL']=url.render_as_string(hide_password=False)
    os.environ['DATABASE_URL_SYNC']=url.set(drivername='postgresql').render_as_string(hide_password=False)
    os.environ['DUCKDB_PATH']=manifest['duckdb_path']
    os.environ['GEMINI_MAX_RETRIES']='3'
    get_settings.cache_clear()
    from backend.database import AsyncSessionLocal, engine
    from backend.services.agent import agent_query
    from backend.services.rag import vector_search
    from backend.services import llm
    from backend.services.duckdb_warehouse import close_warehouse
    from scripts.bounded_cloud_meter import BoundedCloudMeter
    a.output.mkdir(parents=True,exist_ok=a.resume)
    answers=load(a.output/'answers.json') if a.resume else []
    traces=load(a.output/'model_call_traces.json') if a.resume else []
    if [q['id'] for q in answers]!=[q['id'] for q in plan['questions'][:len(answers)]]:
        raise ValueError('Saved answers do not match frozen question prefix')
    journal=a.output/a.journal
    if journal.exists():raise ValueError('Use a new journal name; never overwrite an actual-call journal')
    save(a.output/('method_lock_'+a.journal+'.json'),{'source_manifest_sha256':sha(a.source/'run_manifest.json'),
        'plan_sha256':sha(a.source/'plan_locked.json'),'database_name':name,'no_ocr_or_upload':True,
        'retained_prefix_count':len(answers),'script_sha256':sha(__file__),
        'code_sha256':{p:sha(p) for p in ['backend/services/agent.py','backend/services/answer_capture.py']},
        'no_reference_labels_in_generation':True,'quality_goal_completed':False})
    try:
        with BoundedCloudMeter(a.budget,journal,max_new_attempts=None) as meter:
            for q in plan['questions'][len(answers):]:
                meter.phase={'stage':'answer','id':q['id']}
                start=time.perf_counter()
                async with AsyncSessionLocal() as db:
                    hits=await vector_search(q['question'],db,top_k=5)
                    with llm.trace_model_calls() as calls:
                        result=await agent_query(q['question'],db)
                answers.append({**q,'answer':result['answer'],'full_result':result,'retrieval':hits,
                                'agent_elapsed_seconds':time.perf_counter()-start})
                traces.append({'id':q['id'],'calls':calls})
                save(a.output/'answers.json',answers);save(a.output/'model_call_traces.json',traces)
                print('Answered',q['id'],result.get('answer_capture',{}).get('status'),flush=True)
        save(a.output/'answer_only_summary.json',{'n_saved':len(answers),'n_planned':len(plan['questions']),
            'new_ocr_calls':0,'journal':str(journal),'human_confirmed':False,'quality_goal_completed':False})
    finally:
        close_warehouse();await engine.dispose()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['source','output','budget']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--journal',required=True);p.add_argument('--resume',action='store_true')
    asyncio.run(run(p.parse_args()))
