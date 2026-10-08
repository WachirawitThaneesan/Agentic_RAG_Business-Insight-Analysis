"""Offline final regrade from frozen, separately scoped judge decisions."""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from backend.eval.comprehensive import VERSION,validate_judgment,claim_metrics,fraction,f1
from scripts.evaluate_comprehensive import load,save,sha,prepare,summarize,write_csv


def run(args):
    rows,retrieval,_=prepare(load(args.config))
    cov_a={r['key']:r for r in load(args.answer_coverage/'reviews.json')}
    cov_c={r['key']:r for r in load(args.context_coverage/'reviews.json')}
    lineage={'method_version':VERSION,'scope':'Same-family AI judges; original diagnostic reports; not human-certified',
        'claim_audit':{'path':str(args.claim_audit),'sha256':sha(args.claim_audit/'details.json')},
        'relevance_audit':{'path':str(args.relevance_audit),'sha256':sha(args.relevance_audit/'details.json')},
        'answer_coverage_sha256':sha(args.answer_coverage/'reviews.json'),
        'context_coverage_sha256':sha(args.context_coverage/'reviews.json'),'code_sha256':sha(Path(__file__))}
    args.output.mkdir(parents=True,exist_ok=False)
    for row in rows:
        source=args.claim_audit/'judge_outputs'/f"{row['key']}.json"
        saved=load(source) if source.exists() else None
        row['judge_status']=saved['status'] if saved else 'not_measured_context_or_judge_unavailable'
        if saved and saved['status']=='measured':
            raw=re.sub(r'^```(?:json)?\s*|\s*```$','',saved['raw_outputs'][-1].strip())
            j=validate_judgment(json.loads(raw),context=row['context'],sources=row['sources'],reference=row['reference'])
            if not row['answerable']:j['reference_claims']=[]
            elif row['key'] not in cov_a or row['key'] not in cov_c:
                raise ValueError('Missing separate answer/context coverage for '+row['key'])
            else:
                for mode,lookup in [('answer',cov_a),('context',cov_c)]:
                    facts={f['index']:f for f in lookup[row['key']]['facts']}
                    if set(facts)!=set(range(len(j['reference_claims']))):raise ValueError('Coverage claim indices changed')
                    for index,rc in enumerate(j['reference_claims']):
                        field=mode+'_covered';rc[field+'_joint_ai']=rc[field]
                        rc[field]=facts[index]['covered'];rc[field+'_focused_ai']=facts[index]['ai_covered']
                        rc[field+'_focused_quote']=facts[index]['quote']
                        if facts[index].get('evidence_span'):rc[field+'_focused_span']=facts[index]['evidence_span']
            row['claims']=claim_metrics(j)
            if not row['answerable']:
                row['abstention_rule']='refusal marker and no noncalendar answer quantities on explicit unavailable-financial-scope control'
            if row['answerable']:
                row['coverage_status']='separate_answer_and_context_quote_audit'
                row['claims']['factual_recall_focused_ai']=fraction(sum(r['answer_covered_focused_ai'] for r in j['reference_claims']),len(j['reference_claims']))
                row['claims']['context_recall_focused_ai']=fraction(sum(r['context_covered_focused_ai'] for r in j['reference_claims']),len(j['reference_claims']))
                row['claims']['factual_f1_focused_ai']=f1(row['claims']['factual_precision_ai_judged'],row['claims']['factual_recall_focused_ai'])
            relevance_path=args.relevance_audit/'judgments'/f"{row['key']}.json"
            rv=load(relevance_path)
            expected={'QUESTION':row['question'],'RESPONSE':row['answer'],'ANSWERABLE':row['answerable'],
                'CLAIMS':[c['text'] for c in j['answer_claims']]}
            if rv['input']!=expected:raise ValueError('Relevance input changed')
            row['relevancy_joint_ai']=row['claims']['answer_relevancy_rubric']
            row['claims']['answer_relevancy_rubric']=rv['result']['score']/2 if rv['result'] else None
            rs=rv['result']['claim_relevant'] if rv['result'] else []
            row['claims']['claim_relevance_precision']=fraction(sum(rs),len(rs)) if rv['result'] else None
            if not j['answer_claims'] and (row['deterministic']['abstained'] or row['deterministic']['empty_response']):
                row['relevancy_ai_before_abstention_rule']=row['claims']['answer_relevancy_rubric']
                row['claims']['answer_relevancy_rubric']=0. if row['answerable'] else 1.
            saved['judgment']=j;saved['reused_claim_decision_sha256']=sha(source)
            save(args.output/'judge_outputs'/source.name,saved)

    save(args.output/'details.json',rows);save(args.output/'retrieval_details.json',retrieval)
    save(args.output/'summary.json',summarize(rows,retrieval));save(args.output/'method_lock.json',lineage)
    write_csv(args.output/'answer_per_question.csv',[{'cohort':r['cohort'],'arm':r['arm'],'id':r['id'],
        'question':r['question'],'answer':r['answer'],'judge_status':r['judge_status'],**r['deterministic'],**r.get('claims',{})} for r in rows])
    print('Final offline regrade',VERSION,'outputs',len(rows),'judged',sum(bool(r.get('claims')) for r in rows))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['config','claim-audit','relevance-audit','answer-coverage','context-coverage','output']:
        p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())

if __name__=='__main__':main()
