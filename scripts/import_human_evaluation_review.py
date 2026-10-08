"""Validate an explicitly completed human sheet and report reviewer/AI disagreement.

Blank/prepared rows cannot certify anything. Source AI decisions and scores
remain immutable. Human conclusions are retained as a separate version.
"""
from __future__ import annotations
import argparse,csv,json
from collections import Counter
from datetime import date
from pathlib import Path
from scripts.evaluate_comprehensive import load,save,sha

VERDICTS={'supported','wrong','insufficient_evidence','unverifiable'}
REFERENCE={'supported','corrected','unanswerable','ambiguous'}


def read_completed(path,expected_ids):
    with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    seen=set();complete=[]
    for r in rows:
        if r['id'] in seen or r['id'] not in expected_ids:raise ValueError('Duplicate/unknown review ID')
        seen.add(r['id'])
        if r.get('human_completed','').strip().lower() not in ('true','1','yes'):continue
        if not r.get('reviewer_name','').strip():raise ValueError('Completed review needs reviewer name')
        date.fromisoformat(r['review_date'])
        if r.get('reference_verdict') not in REFERENCE:raise ValueError('Invalid reference verdict')
        for field in ('faithfulness_verdict','factual_verdict'):
            if r.get(field) not in VERDICTS:raise ValueError('Invalid '+field)
        if not r.get('evidence_quote','').strip() or not r.get('reason','').strip():
            raise ValueError('Completed review needs evidence quote and reason')
        if r['reference_verdict']=='corrected' and not r.get('corrected_reference','').strip():
            raise ValueError('Corrected label needs replacement text')
        complete.append(r)
    return complete


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('sheet','audit','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    with (a.audit/'human_review_sheet.csv').open(encoding='utf-8-sig',newline='') as f:
        expected={r['id'] for r in csv.DictReader(f)}
    completed=read_completed(a.sheet,expected)
    claims=load(a.audit/'claim_statuses.json');disagreements=[]
    for r in completed:
        for field in ('faithfulness','factual'):
            states=Counter(c['state'] for c in claims if c['id']==r['id'] and c['dimension']==field)
            disagreements.append({'id':r['id'],'dimension':field,
                'human_answer_level_verdict':r[field+'_verdict'],'ai_claim_level_states':dict(states),
                'scope':'Answer-level human verdict and claim-level AI states are different units; no synthetic agreement percentage'})
    a.output.mkdir(parents=True,exist_ok=False)
    save(a.output/'completed_human_reviews.json',completed)
    save(a.output/'reviewer_ai_comparison.json',disagreements)
    summary={'n_expected_cases':len(expected),'n_human_completed':len(completed),
        'reference_verdicts':dict(Counter(r['reference_verdict'] for r in completed)),
        'n_source_scores_overwritten':0,'input_sheet_sha256':sha(a.sheet),
        'scope':'User-supplied human attestation; certifies only the reviewed cases'}
    save(a.output/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
