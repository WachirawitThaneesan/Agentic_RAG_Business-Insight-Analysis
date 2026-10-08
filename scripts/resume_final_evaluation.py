"""Resume interrupted frozen checks with two workers and preserved journals."""
import datetime
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.evaluate_comprehensive import load,save,sha
from scripts.parallel_final_judge_checks import publish_once,payload_sha

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'TestFile/evaluation_completion_2026-10-07'
AUDIT=OUT/'final133_audit_v2'
SHARDS=OUT/'final_judge_shards'
RECOVERY=OUT/'interruption_recovery_v1'


def main():
    # Exclusive launcher marker prevents accidental duplicate resumption.
    marker=RECOVERY/'launcher_started.json'
    with marker.open('x',encoding='utf-8') as stream:
        stream.write(str(os.getpid())+'\n')
    expected=load(SHARDS/'expected_payload_sha256.json')
    env=dict(os.environ,PYTHONUTF8='1',GEMINI_MIN_INTERVAL='20',GEMINI_MAX_INTERVAL='60',
        GEMINI_RETRY_BASE_DELAY='20',GEMINI_MAX_RETRIES='3')
    save(OUT/'RUN_STATE.json',{'status':'in_progress','stage':'Resumed final claim/citation checks',
        'updated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'quality_goal_completed':False,'human_confirmed':False,'generated_outputs':532,
        'resume_saved_judgments':len(list((AUDIT/'judge_outputs').glob('*.json'))),
        'launcher_pid':os.getpid(),'accounting_limit':'SDK/token totals are lower bounds after interrupted unreadable writes'})
    pdfs=SHARDS/'pdf_paths.json'
    def start(run,output,log):
        stream=log.open('w',encoding='utf-8')
        args=[sys.executable,'-m','scripts.audit_capture_run','--run-dir',str(run),
            '--pdf-paths',str(pdfs),'--budget',str(OUT/'resource_ledger.json'),
            '--output',str(output),'--fragment-quotes','--resume']
        return subprocess.Popen(args,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT),stream
    main_process,main_log=start(OUT/'final133_v2',AUDIT,RECOVERY/'main_resume.log')
    # Leave an almost-finished dense arm to the main worker, so the second
    # process can cover the larger independent future arm without overlap.
    dense_saved=sum(1 for p in (AUDIT/'judge_outputs').glob('*__dense__*.json'))
    queue=(['dense'] if dense_saved<120 else [])+['simple_rag']
    current=None;worker=None;worker_log=None;exits={};published=[];seen=set()
    while main_process.poll() is None or worker is not None or queue:
        if worker is None and queue:
            current=queue.pop(0)
            # Skip a future arm already completely checked by the main worker.
            if sum(1 for p in (AUDIT/'judge_outputs').glob('*__'+current+'__*.json'))==133:
                exits[current]='all_133_already_in_authoritative_cache';continue
            worker,worker_log=start(SHARDS/current/'final133_v2',SHARDS/current/'audit',RECOVERY/(current+'_resume.log'))
        if worker is not None:
            calls=load(AUDIT/'model_calls.json') if (AUDIT/'model_calls.json').exists() else []
            active=(calls[-1].get('arm'),calls[-1].get('id')) if calls else None
            output=SHARDS/current/'audit'
            for path in (output/'judge_outputs').glob('*.json'):
                if path.stem in seen:continue
                target=AUDIT/'judge_outputs'/path.name
                if target.exists():seen.add(path.stem);continue
                if active==(current,path.stem.rsplit('__',1)[-1]):continue
                input_path=output/'judge_inputs'/path.name
                if payload_sha(load(input_path))!=expected[path.stem]:raise ValueError('Frozen payload mismatch')
                result=load(path)
                if result['status'] not in ('measured','judge_failed'):raise ValueError('Incomplete result')
                publish_once(input_path,AUDIT/'judge_inputs'/path.name)
                if publish_once(path,target):
                    published.append({'key':path.stem,'result_sha256':sha(path),'payload_sha256':expected[path.stem],
                        'source':str(path.relative_to(ROOT)),'status':result['status']})
                    save(RECOVERY/'published_resume_caches.json',published)
                seen.add(path.stem)
            if worker.poll() is not None:
                exits[current]=worker.returncode;worker_log.close();worker=None
        save(RECOVERY/'progress.json',{'outcomes_saved':len(list((AUDIT/'judge_outputs').glob('*.json'))),
            'planned':532,'main_exit':main_process.poll(),'future_arm':current,'future_exits':exits})
        time.sleep(5)
    main_log.close()
    save(RECOVERY/'progress.json',{'outcomes_saved':len(list((AUDIT/'judge_outputs').glob('*.json'))),
        'planned':532,'main_exit':main_process.returncode,'future_arm':None,
        'future_exits':exits,'no_workers_remaining':True})
    save(SHARDS/'worker_exits.json',{'interrupted_original_worker_group':True,'resumed_future_workers':exits,
        'authoritative_main_exit':main_process.returncode,'no_workers_remaining':True})
    if main_process.returncode:raise SystemExit(main_process.returncode)
    (OUT/'resources_observed/STOP').write_text('stop\n',encoding='utf-8')
    code=subprocess.call([sys.executable,'-m','scripts.package_evaluation_completion','--final'],cwd=ROOT,env=env)
    if code:raise SystemExit(code)
    save(OUT/'RUN_STATE.json',{'status':'evaluation_scope_finished_targets_remaining',
        'stage':'All final outcomes accounted for; integrity/ZIP verified; quality targets remaining',
        'updated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'quality_goal_completed':False,'human_confirmed':False,
        'report':str((ROOT/'docs/evaluation-completion-2026-10-07/REPORT_th.md').resolve())})
    print('Final evidence delivered; quality objective remains partial',flush=True)


if __name__=='__main__':main()
