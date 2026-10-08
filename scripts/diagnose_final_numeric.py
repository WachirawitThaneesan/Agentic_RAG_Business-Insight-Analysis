"""Offline component diagnostics; never replace the frozen strict numeric score."""
from collections import Counter
from pathlib import Path

from backend.eval.contract_replay import numeric_results
from scripts.evaluate_comprehensive import load,save

OUT=Path(__file__).resolve().parents[1]/'TestFile/evaluation_completion_2026-10-07'


def main():
    run=OUT/'final133_v2';records=load(run/'paired_answers.json')
    labels=load(run/'numeric_labels_locked.json');bank=load(run/'reference_locked.json')
    by_id={qid:[l for l in labels if l['id']==qid] for qid in {l['id'] for l in labels}}
    details=[];summary={}
    for arm in ('bm25_thai','dense','simple_rag','lexical_first'):
        rows=[]
        for record in records:
            generated=record['arms'][arm]
            for result in numeric_results(by_id.get(record['id'],[]),generated['full_result'],generated['answer'],
                    allow_provisional=True,document_registry=bank['documents']):
                rows.append({'id':record['id'],'arm':arm,**result})
        bound=[r for r in rows if r.get('checks')]
        failures=Counter(k for r in bound for k,v in r['checks'].items() if v is False)
        identity_only=sum(r['correct'] is False and {k for k,v in r['checks'].items() if v is False}<= {'company','measure'} for r in bound)
        summary[arm]={'n_required':len(rows),'n_bound_checks_available':len(bound),
            'n_strict_correct':sum(r['correct'] is True for r in rows),
            'n_strict_unknown':sum(r['correct'] is None for r in rows),
            'failed_check_counts_nonexclusive':dict(failures),
            'n_failure_only_in_literal_company_or_measure':identity_only,
            'n_signed_value_unit_checks_correct':sum(r['checks']['signed_value_and_explicit_unit'] for r in bound),
            'states':dict(Counter(r['state'] for r in rows))}
        details.extend(rows)
    dest=OUT/'final_numeric_components'
    save(dest/'summary.json',{'scope':'Post-test descriptive failure decomposition with unchanged locked labels/scorer; literal identity failures are not adjudicated synonyms; component passes do not substitute for strict tuple accuracy',
        'new_cloud_calls':0,'human_confirmed':False,'arms':summary})
    save(dest/'details.json',details)
    print(summary)


if __name__=='__main__':main()
