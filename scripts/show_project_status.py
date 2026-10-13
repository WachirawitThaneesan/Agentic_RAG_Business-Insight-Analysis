"""Read-only console for local completion progress or the published final snapshot."""
import argparse
import json
import os
from pathlib import Path
import time

REPO=Path(__file__).resolve().parents[1]
LOCAL=REPO/'TestFile/project_closure_2026-10-09'
PUBLIC=REPO/'TestFile/published_2026-10-13'
def read(p):
    try:return json.loads(p.read_text(encoding='utf-8-sig'))
    except (OSError,ValueError):return {}
def snapshot():
    m=read(LOCAL/'final_analysis_v2/RESULT_MANIFEST_v2.json') or read(PUBLIC/'RESULT_MANIFEST_v2.json')
    progress=read(LOCAL/'evaluation_completion_v2/PROGRESS.json') or m.get('assessment_completion',{})
    qa=read(LOCAL/'submission_completed_v2/DELIVERY_MANIFEST.json') or read(PUBLIC/'DELIVERY_MANIFEST.json')
    return {'stage':progress.get('stage','completed_assessment'),'usable':progress.get('usable_judgments',progress.get('usable',0)),
            'planned':1060,'remaining':progress.get('remaining_overlay',progress.get('remaining',1060)),
            'systems':m.get('systems',{}),'artifact_QA_complete':qa.get('visual_QA_complete',False),
            'report_pages':qa.get('report_pages'),'human_confirmed':False,'quality_goal_completed':False,'new_Gemini_calls':0}
def render(s):
    print('PROJECT STATUS | saved results only | refresh 5 seconds')
    print('='*74)
    print('Stage:',s['stage'])
    print(f"Usable assessments: {s['usable']}/1060 ({100*s['usable']/1060:.1f}%) | Remaining: {s['remaining']}")
    for k,v in s['systems'].items():
        print(f"{'S1 Full App' if k=='full_app' else 'S0 Dense RAG'}: strict {v['complete_answer_success']}/498 ({100*v['complete_answer_rate_all498']:.2f}%) | numeric {v['numeric_correct_relations']}/356 ({100*v['numeric_rate']:.2f}%)")
    print(f"Report/poster visual QA: {'COMPLETE' if s['artifact_QA_complete'] else 'IN PROGRESS'} | Report pages: {s['report_pages'] or 'pending'}")
    print('No new Gemini calls. AI-assisted judgments; no human confirmation.')
    print('Assessment completion is 100%; the >80% answer-quality goal is NOT met.')
    print('Published package: TestFile/published_2026-10-13 | Ctrl+C to close')
def main():
    p=argparse.ArgumentParser();p.add_argument('--once',action='store_true');p.add_argument('--json',action='store_true');a=p.parse_args()
    while True:
        s=snapshot()
        if a.json:print(json.dumps(s,ensure_ascii=False));return
        if not a.once:os.system('cls' if os.name=='nt' else 'clear')
        render(s)
        if a.once:return
        try:time.sleep(5)
        except KeyboardInterrupt:return
if __name__=='__main__':main()
