"""Operational parallel scheduling of identical frozen future-arm judgments.

The original audit remains the authoritative reducer. Independent processes
use its unchanged audit code and publish exact-payload caches, without choosing
between judgments on the basis of their scores. Every shard/call is retained.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from scripts.evaluate_comprehensive import load, save, prepare, judge_payload, sha

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'TestFile/evaluation_completion_2026-10-07'
RUN=OUT/'final133_v2'
AUDIT=OUT/'final133_audit_v2'
SHARDS=OUT/'final_judge_shards'


def payload_sha(payload):
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()


def publish_once(source,target):
    """Atomic cache creation; an already-saved authoritative result wins."""
    target.parent.mkdir(parents=True,exist_ok=True)
    try:
        os.link(source,target)
        return True
    except FileExistsError:
        return False


def main():
    SHARDS.mkdir(exist_ok=False)
    records=load(RUN/'paired_answers.json')
    rows,_,_=prepare(load(AUDIT/'config_locked.json'))
    expected={}
    for row in rows:
        row['compact_judge_payload']=True;row['fragment_quotes']=True
        expected[row['key']]=payload_sha(judge_payload(row))
    del rows
    save(SHARDS/'expected_payload_sha256.json',expected)
    processes=[];streams=[]
    env=dict(os.environ,PYTHONUTF8='1',GEMINI_MIN_INTERVAL='5',GEMINI_RETRY_BASE_DELAY='20',GEMINI_MAX_RETRIES='3')
    pdfs=load(AUDIT/'config_locked.json')['cohorts'][0]['pdf_paths']
    save(SHARDS/'pdf_paths.json',pdfs)
    for arm in ('dense','lexical_first','simple_rag'):
        run=SHARDS/arm/'final133_v2';run.mkdir(parents=True)
        derived=[{**r,'arms':{arm:r['arms'][arm]}} for r in records]
        save(run/'paired_answers.json',derived)
        for name in ('reference_locked.json','numeric_labels_locked.json'):
            shutil.copy2(RUN/name,run/name)
        # Same arm records, questions, original PDFs and cohort key. No change
        # to model, prompts, schema, capture, scorer, labels or retries.
        output=SHARDS/arm/'audit'
        stream=(SHARDS/(arm+'.log')).open('w',encoding='utf-8');streams.append(stream)
        args=[sys.executable,'-m','scripts.audit_capture_run','--run-dir',str(run),
            '--pdf-paths',str(SHARDS/'pdf_paths.json'),'--budget',str(OUT/'resource_ledger.json'),
            '--output',str(output),'--fragment-quotes']
        processes.append((arm,subprocess.Popen(args,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT),output))
    save(SHARDS/'scheduling_disclosure.json',{
        'original_audit_unchanged':True,'scope':'Process concurrency and exact-payload cache publication only',
        'generation_regenerated':False,'model_prompt_schema_scorer_labels_changed':False,
        'selection_policy':'Import both measured and failed outcomes; existing original cache wins; never select by score',
        'possible_overlap':'A future-arm judgment already in flight in the original worker can also occur in a shard; both raw outcomes/calls remain saved',
        'code_sha256':sha(Path(__file__))})
    published=[];seen=set()
    while True:
        calls=load(AUDIT/'model_calls.json') if (AUDIT/'model_calls.json').exists() else []
        active=(calls[-1].get('arm'),calls[-1].get('id')) if calls else None
        for arm,process,output in processes:
            for path in (output/'judge_outputs').glob('*.json'):
                key=path.stem
                if key in seen:continue
                target=AUDIT/'judge_outputs'/path.name
                if target.exists():seen.add(key);continue
                # Do not publish over an original judgment being saved/in flight.
                if active==(arm,key.rsplit('__',1)[-1]):continue
                source_input=output/'judge_inputs'/path.name
                if not source_input.exists():continue
                if payload_sha(load(source_input))!=expected.get(key):
                    raise ValueError('Parallel payload differs from frozen original: '+key)
                result=load(path)
                if result.get('status') not in ('measured','judge_failed'):
                    raise ValueError('Incomplete shard judgment: '+key)
                publish_once(source_input,AUDIT/'judge_inputs'/path.name)
                if publish_once(path,target):
                    published.append({'key':key,'source':str(path.relative_to(ROOT)),
                        'payload_sha256':expected[key],'result_sha256':sha(path),'status':result['status']})
                    save(SHARDS/'published_caches.json',published)
                seen.add(key)
        if all(p.poll() is not None for _,p,_ in processes):break
        time.sleep(3)
    for stream in streams:stream.close()
    exits={arm:p.returncode for arm,p,_ in processes}
    save(SHARDS/'worker_exits.json',exits)
    print('Parallel checks finished',exits,'published',len(published),flush=True)
    if any(exits.values()):raise SystemExit(1)


if __name__=='__main__':main()
