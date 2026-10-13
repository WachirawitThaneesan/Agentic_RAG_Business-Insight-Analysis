"""Verify release bytes and recompute published aggregates without APIs or databases."""
import gzip, hashlib, json, statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def read(n):return json.loads((ROOT/n).read_text(encoding='utf-8'))
def main():
    hashes=read('RELEASE_SHA256.json')
    for n,h in hashes.items():assert hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==h,n
    m=read('RESULT_MANIFEST_v2.json');r=read('RESULTS_BY_QUESTION.json')
    assert len(r)==1060 and len({(x['id'],x['system']) for x in r})==1060
    assert m['assessment_completion']['remaining']==0 and not m['human_confirmed'] and not m['quality_goal_completed']
    with gzip.open(ROOT/'ASSESSMENT_DECISIONS_v2.json.gz','rt',encoding='utf-8') as f:d=json.load(f)
    assert len(d)==1060 and sum(x['completion_overlay'] for x in d)==348 and sum(x['adjudicated'] for x in d)==34
    for system,s in m['systems'].items():
        rows=[x for x in r if x['system']==system and x['answerable']];controls=[x for x in r if x['system']==system and not x['answerable']]
        assert len(rows)==498 and len(controls)==32
        assert sum(x['complete_answer'] for x in rows)==s['complete_answer_success']
        assert sum(x['numeric_correct'] for x in rows)==s['numeric_correct_relations']
        assert sum(x['numeric_required'] for x in rows)==s['numeric_required_relations']==356
        assert s['unassessed_judgments']==0 and all(x['judge_status']=='first_validated_judgment_retained' for x in rows+controls)
        for k,v in s['rag_metrics'].items():
            values=[x['metrics'][k] for x in rows if x['metrics'][k] is not None]
            assert v['assessable_n']==len(values) and abs(v['assessed_mean']-statistics.mean(values))<1e-12
            assert abs(v['conservative_all498_mean']-sum(values)/498)<1e-12
        sens=m['source_validity_sensitivity'];filtered=[x for x in rows if x['id'] not in sens['excluded_question_ids']];sv=sens['systems'][system]
        assert len(filtered)==sv['main_n']==495
        assert sum(x['complete_answer'] for x in filtered)==sv['strict_complete']
        assert sum(x['numeric_correct'] for x in filtered)==sv['numeric_correct']
        assert sum(x['numeric_required'] for x in filtered)==sv['numeric_required']==353
    delivery=read('DELIVERY_MANIFEST.json')
    assert delivery['visual_QA_complete'] and delivery['report_pages']==24
    for n,h in delivery['files'].items():assert hashlib.sha256((ROOT/'artifacts'/n).read_bytes()).hexdigest()==h,n
    assert len(list((ROOT/'artifacts/report_previews').glob('page-*.png')))==24
    assert not any(p.name.endswith(('.duckdb','.log')) or p.name.startswith('.env') for p in ROOT.rglob('*'))
    print(f'PASS: {len(hashes)} release hashes; 1060 paired assessments; all primary metrics and sensitivity; 24 report previews; unchanged deliverable hashes.')
if __name__=='__main__':main()
