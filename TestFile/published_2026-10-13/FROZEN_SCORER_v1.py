"""Paired/clustered summaries from frozen first outcomes and source judgments only."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import random
import re
import statistics

HERE=Path(__file__).resolve().parent
METRICS=['faithfulness','factual_precision','factual_recall','factual_f1',
    'claim_relevance_precision','answer_relevancy_rubric','context_precision_ap','context_recall']
def fraction(a,b):return a/b if b else None
def f1(p,r):return None if p is None or r is None else 2*p*r/(p+r) if p+r else 0
def percentile(values,p):
    values=sorted(values)
    if not values:return None
    position=(len(values)-1)*p;lo=int(position);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(position-lo)
def metrics(j):
    claims=j['answer_claims'];refs=j['reference_claims'];ctx=sorted(j['context_relevance'],key=lambda c:c['context_index'])
    rel=[int(c['useful']) for c in ctx];precision=fraction(sum(c['factual']=='supported' for c in claims),len(claims))
    recall=fraction(sum(c['answer_covered'] for c in refs),len(refs))
    return {'faithfulness':fraction(sum(c['faithfulness']=='supported' for c in claims),len(claims)),
        'factual_precision':precision,'factual_recall':recall,'factual_f1':f1(precision,recall),
        'claim_relevance_precision':fraction(sum(c['relevant'] for c in claims),len(claims)),
        'answer_relevancy_rubric':j['relevancy']['score']/2,
        'context_precision_ap':fraction(sum(sum(rel[:i+1])/(i+1) for i,v in enumerate(rel) if v),sum(rel)) if sum(rel) else 0 if rel else None,
        'context_recall':fraction(sum(c['context_covered'] for c in refs),len(refs))}
def main():
    labels=HERE/'final_bank_source_lock_v1/source_labels530.json'
    bank=json.loads(labels.read_text(encoding='utf-8'));items={i['id']:i for i in bank['items']}
    paired=HERE/'final_paired_v24_v1';judges=HERE/'final_source_judgments_v1'
    assert (paired/'FIRST_OUTCOMES_COMPLETE.json').exists() and (judges/'JUDGMENTS_COMPLETE.json').exists()
    OUT=HERE/'final_analysis_v1';assert not OUT.exists();OUT.mkdir()
    rows=[]
    for path in sorted((paired/'first_outcomes').glob('*.json')):
        record=json.loads(path.read_text(encoding='utf-8'));item=items[record['id']];full=record['first_outcome']
        decision_path=judges/'judgments'/path.name
        judged=json.loads(decision_path.read_text(encoding='utf-8'))
        judgment=judged.get('judgment') if judged['status']=='first_validated_judgment_retained' else None
        numeric_n=sum(n.get('answer_required',True) for n in item['numeric_requirements'])
        scores=metrics(judgment) if judgment else {k:None for k in METRICS}
        numeric_correct=sum(n['matches'] for n in judgment['numeric_relations']) if judgment else 0
        claims=judgment['answer_claims'] if judgment else []
        citations=judgment['actual_citation_audit'] if judgment else []
        supported_claims={c['claim_index'] for c in citations if c['verdict']=='supported'}
        capture_errors=full.get('answer_capture',{}).get('errors',[])
        stated_pages={int(page) for page in re.findall(r'(?:PDF\s*(?:หน้า|page)|หน้า\s*PDF)\s*(\d+)',full.get('answer',''),re.I)}
        emitted_sources=full.get('sources',[])
        cited_pages={emitted_sources[c['source_index']].get('page') for c in citations if c['verdict']=='supported'
            and 0<=c['source_index']<len(emitted_sources)}
        prose_page_consistent=bool(stated_pages) and stated_pages.issubset(cited_pages)
        complete=bool(judgment) and bool(claims) and not full.get('abstained') and not full.get('error_type') and not capture_errors
        if complete:
            complete=(all(c['faithfulness']=='supported' and c['factual']=='supported' and c['relevant'] for c in claims)
                and all(c['answer_covered'] for c in judgment['reference_claims'])
                and judgment['relevancy']['score']==2 and len(supported_claims)==len(claims)
                and numeric_correct==numeric_n and not judgment['unannotated_answer_assertions']
                and prose_page_consistent)
        rows.append({'id':record['id'],'system':record['system'],'issuer':item['issuer'],'category':item['category'],
            'answerable':item.get('answerable',True),'metrics':scores,'complete_answer':bool(complete),
            'numeric_required':numeric_n,'numeric_correct':numeric_correct,'abstained':bool(full.get('abstained')),
            'model_error':bool(full.get('error_type')),'capture_errors':capture_errors,'judge_status':judged['status'],
            'wall_seconds':record['wall_seconds'],'tool_actions':[t.get('action') for t in full.get('reasoning_trace',[])],
            'prose_page_consistent':prose_page_consistent,
            'control_assessment':judgment['control_assessment'] if judgment else None,
            'evidence_cluster':item['issuer']+'/'+','.join(map(str,item.get('evidence_pages',[])))})
    assert len(rows)==1060
    summary={'status':'AI_assisted_measured_results_pending_stratified_visual_QA','human_confirmed':False,
        'main_denominator_per_system':498,'control_denominator_per_system':32,'systems':{},'paired':{},
        'quality_goal_completed':False,'source_labels_sha256':hashlib.sha256(labels.read_bytes()).hexdigest()}
    for system in ('simple_dense_rag','full_app'):
        main=[r for r in rows if r['system']==system and r['answerable']]
        controls=[r for r in rows if r['system']==system and not r['answerable']]
        assert len(main)==498 and len(controls)==32
        ms={}
        for key in METRICS:
            values=[r['metrics'][key] for r in main if r['metrics'][key] is not None]
            ms[key]={'assessed_mean':statistics.mean(values) if values else None,'assessable_n':len(values),
                'missing_or_na_n':498-len(values),'conservative_all498_mean':sum(values)/498}
        summary['systems'][system]={'rag_metrics':ms,'complete_answer_success':sum(r['complete_answer'] for r in main),
            'complete_answer_rate_all498':sum(r['complete_answer'] for r in main)/498,
            'numeric_correct_relations':sum(r['numeric_correct'] for r in main),
            'numeric_required_relations':sum(r['numeric_required'] for r in main),
            'numeric_rate':fraction(sum(r['numeric_correct'] for r in main),sum(r['numeric_required'] for r in main)),
            'false_refusals':sum(r['abstained'] for r in main),'model_errors':sum(r['model_error'] for r in main),
            'capture_error_questions':sum(bool(r['capture_errors']) for r in main),
            'unassessed_judgments':sum(r['judge_status']!='first_validated_judgment_retained' for r in main),
            'controls':{'appropriate_abstentions':sum(bool(r['control_assessment'] and r['control_assessment']['appropriate_abstention']) for r in controls),
                'unsupported_requested_assertions':sum(bool(r['control_assessment'] and r['control_assessment']['unsupported_requested_assertion']) for r in controls),
                'truthful_irrelevant_substitutions':sum(bool(r['control_assessment'] and r['control_assessment']['truthful_irrelevant_substitution']) for r in controls),
                'unassessed':sum(r['control_assessment'] is None for r in controls)},
            'latency_seconds':{'n':len(main)+len(controls),'p50':percentile([r['wall_seconds'] for r in main+controls],.5),'p95':percentile([r['wall_seconds'] for r in main+controls],.95)},
            'actual_tools':dict(Counter(a for r in main+controls for a in r['tool_actions']))}
    by_id={}
    for row in rows:
        if row['answerable']:by_id.setdefault(row['id'],{})[row['system']]=row
    issuers=sorted({r['issuer'] for r in rows});rng=random.Random(20261009)
    for key in METRICS+['complete_answer']:
        diffs_by_report={}
        for issuer in issuers:
            diffs=[]
            for pair in by_id.values():
                if pair['full_app']['issuer']!=issuer:continue
                value=lambda r:float(r['complete_answer']) if key=='complete_answer' else r['metrics'][key] or 0.0
                diffs.append(value(pair['full_app'])-value(pair['simple_dense_rag']))
            diffs_by_report[issuer]=diffs
        boot=[]
        for _ in range(2000):
            selected=[rng.choice(issuers) for _ in issuers]
            values=[d for issuer in selected for d in diffs_by_report[issuer]];boot.append(statistics.mean(values))
        values=[d for report in diffs_by_report.values() for d in report]
        summary['paired'][key]={'S1_minus_S0_mean':statistics.mean(values),'report_cluster_bootstrap95':[percentile(boot,.025),percentile(boot,.975)],
            'cluster_n':4,'replicates':2000,'seed':20261009,'limitation':'Four reports; limited generalization. Missing/unassessed contributions counted0.'}
    (OUT/'RESULTS_BY_QUESTION.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUT/'RESULT_MANIFEST_v1.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Measured first-outcome analysis retained; human/visual QA and final report/poster verification still required.')
if __name__=='__main__':main()
