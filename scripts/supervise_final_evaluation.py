"""Finish judging/package after the already-dispatched frozen generation run."""
import datetime
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.evaluate_comprehensive import load,save,sha

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'TestFile/evaluation_completion_2026-10-07'
RUN=OUT/'final133_v2'
PDFS=Path(r'C:\Users\nonga\Documents\Codex\2026-10-05\step2-rag-evaluation-continuation\outputs\plan_completion_authorized_v1\heldout_fact_dedup_v4\pdf_paths.json')


def state(stage,**extra):
    save(OUT/'RUN_STATE.json',{'status':'in_progress','stage':stage,
        'updated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'quality_goal_completed':False,'human_confirmed':False,**extra})


def main():
    last=None
    while True:
        records=load(RUN/'paired_answers.json') if (RUN/'paired_answers.json').exists() else []
        outputs=sum(len(r['arms']) for r in records)
        if outputs!=last:
            state('final transfer inference',generated_outputs=outputs,planned_outputs=532)
            print('Final transfer outputs',outputs,'/532',flush=True);last=outputs
        if len(records)==133 and all(len(r['arms'])==4 for r in records):break
        time.sleep(10)
    state('final actual claim/citation judge')
    env=dict(os.environ,PYTHONUTF8='1',GEMINI_MIN_INTERVAL='5',GEMINI_RETRY_BASE_DELAY='20',GEMINI_MAX_RETRIES='3')
    args=[sys.executable,'-m','scripts.audit_capture_run','--run-dir',str(RUN),
        '--pdf-paths',str(PDFS),'--budget',str(OUT/'resource_ledger.json'),
        '--output',str(OUT/'final133_audit_v2'),'--fragment-quotes']
    with (OUT/'final_judge.log').open('w',encoding='utf-8') as stream:
        code=subprocess.call(args,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
    if code:
        state('final judge operational failure',exit_code=code)
        raise SystemExit(code)
    state('final packaging')
    (OUT/'resources_observed/STOP').write_text('stop\n',encoding='utf-8')
    code=subprocess.call([sys.executable,'-m','scripts.package_evaluation_completion','--final'],cwd=ROOT,env=env)
    if code:state('packaging failure',exit_code=code);raise SystemExit(code)
    save(OUT/'RUN_STATE.json',{'status':'evaluation_scope_finished_targets_remaining',
        'stage':'Final transfer, actual-link audit and evidence package delivered',
        'updated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'quality_goal_completed':False,'human_confirmed':False,
        'final_generation_sha256':sha(RUN/'paired_answers.json'),
        'final_judge_summary_sha256':sha(OUT/'final133_audit_v2/contract_summary.json'),
        'report':str((ROOT/'docs/evaluation-completion-2026-10-07/REPORT_th.md').resolve())})
    print('Final evaluation scope delivered; quality targets remain',flush=True)


if __name__=='__main__':main()
