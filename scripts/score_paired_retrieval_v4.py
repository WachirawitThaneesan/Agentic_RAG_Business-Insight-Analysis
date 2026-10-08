"""Score two saved retrieval runs against the same locked PDF-page labels."""
from __future__ import annotations
import argparse, csv, json
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from backend.eval.comprehensive import page_metrics, wilson
from scripts.evaluate_comprehensive import load, save, sha, write_csv

def mean(rows,key):
    values=[x[key] for x in rows if x.get(key) is not None]
    return sum(values)/len(values) if values else None

def metrics(bank, records):
    items=bank['items'];byid={x['id']:x for x in items};docs={x['code']:x for x in bank['documents']}
    if len(records)!=len(items) or {x['id'] for x in records}!=set(byid):
        raise ValueError('Retrieval must have exactly one prediction per question')
    scores=[]
    for record in records:
        q=byid[record['id']]
        for arm,hits in record['arms'].items():
            for k in (1,3,5,10):
                if k>len(hits) and k>5 and arm=='app_hybrid':continue
                m=page_metrics(q,hits,docs,k=k,depth=len(hits))
                if m['status']!='measured':continue
                scores.append({'id':record['id'],'document':q['document'],'gold_page':q['source_pdf_page'],
                    'arm':arm,'k':k,**m})
    summary={}
    for arm,k in sorted({(x['arm'],x['k']) for x in scores}):
        rows=[x for x in scores if (x['arm'],x['k'])==(arm,k)]
        count=sum(x['hit'] for x in rows)
        summary[f'{arm}@{k}']={'n':len(rows),'hits':count,'hit_rate':count/len(rows),
            'hit_95_wilson':wilson(count,len(rows)),
            'mean_recall':mean(rows,'recall'),'mean_precision':mean(rows,'precision'),
            'mean_ndcg':mean(rows,'ndcg'),'mean_mrr':mean(rows,'mrr'),
            'complete_evidence_count':sum(x['complete_evidence'] for x in rows),
            'by_document':{doc:{'n':len(part),'hits':sum(x['hit'] for x in part)}
                for doc in sorted({x['document'] for x in rows})
                if (part:=[x for x in rows if x['document']==doc])}}
    return scores,summary

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','baseline','candidate','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--baseline-arm',default='app_hybrid')
    p.add_argument('--candidate-arm',default='app_hybrid')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    bank=load(a.reference);base=load(a.baseline);cand=load(a.candidate)
    base_rows,base_summary=metrics(bank,base);new_rows,new_summary=metrics(bank,cand)
    if len({x['id'] for x in base})!=498:raise ValueError('Expected reviewed 498 bank')
    b={x['id']:x for x in base};c={x['id']:x for x in cand};byid={x['id']:x for x in bank['items']}
    docs={x['code']:x for x in bank['documents']};deltas=[]
    for qid in [x['id'] for x in bank['items']]:
        question=byid[qid]
        old=page_metrics(question,b[qid]['arms'][a.baseline_arm],docs,k=5)
        new=page_metrics(question,c[qid]['arms'][a.candidate_arm],docs,k=5)
        debug=c[qid].get('ranking_debug') or c[qid].get('debug',{}).get(a.candidate_arm,{})
        lex=debug.get('keyword_pages',[]);dense=debug.get('semantic_pages',[])
        union=[];seen=set()
        for hit in [*lex,*dense]:
            key=(hit.get('filename'),hit.get('source_pdf_page'))
            if key not in seen:seen.add(key);union.append(hit)
        candidate_m=page_metrics(question,union,docs,k=len(union)) if union else None
        deltas.append({'id':qid,'document':question['document'],
            'gold_page':question['source_pdf_page'],'question':question['question_th'],
            'baseline_hit5':old['hit'],'candidate_hit5':new['hit'],
            'baseline_complete5':old['complete_evidence'],
            'candidate_complete5':new['complete_evidence'],
            'baseline_first_rank':old['first_relevant_rank'],
            'candidate_first_rank':new['first_relevant_rank'],
            'keyword_first_rank':(page_metrics(question,lex,docs,k=len(lex))['first_relevant_rank'] if lex else None),
            'semantic_first_rank':(page_metrics(question,dense,docs,k=len(dense))['first_relevant_rank'] if dense else None),
            'candidate_union_has_evidence':candidate_m['hit'] if candidate_m else None,
            'numeric_route':debug.get('numeric_route'),
            'old_top5':json.dumps(b[qid]['arms'][a.baseline_arm],ensure_ascii=False),
            'new_top5':json.dumps(c[qid]['arms'][a.candidate_arm],ensure_ascii=False)})
    changes=Counter('recovered' if x['candidate_hit5']>x['baseline_hit5'] else
        'regressed' if x['candidate_hit5']<x['baseline_hit5'] else 'unchanged' for x in deltas)
    # Many generated questions reuse a source page. Resample page groups,
    # not individual questions, for a conditional interval on these reports.
    grouped=defaultdict(list)
    for row in deltas:grouped[(row['document'],row['gold_page'])].append(row)
    groups=list(grouped.values());rng=np.random.default_rng(20261005);bootstrap=[]
    for _ in range(2000):
        selected=[groups[int(i)] for i in rng.integers(0,len(groups),size=len(groups))]
        rows=[x for group in selected for x in group]
        bootstrap.append(sum(x['candidate_hit5']-x['baseline_hit5'] for x in rows)/len(rows))
    ci=[float(x) for x in np.quantile(bootstrap,[.025,.975])]
    summary={'reference_sha256':sha(a.reference),'baseline_retrieval_sha256':sha(a.baseline),
        'candidate_retrieval_sha256':sha(a.candidate),
        'baseline_arm':a.baseline_arm,'candidate_arm':a.candidate_arm,
        'n_question_ids':len(deltas),'paired_change_counts':dict(changes),
        'n_primary_evidence_page_groups':len(groups),
        'paired_hit5_delta':sum(x['candidate_hit5']-x['baseline_hit5'] for x in deltas)/len(deltas),
        'paired_hit5_delta_page_group_bootstrap_95':ci,
        'interval_scope':'Clustered by primary source document/page, conditional on these four used diagnostic reports; not unseen-document generalization',
        'baseline':base_summary,'candidate':new_summary,
        'diagnostic_reports_only':True,'human_certified':0,
        'same_question_labels_and_scorer':True}
    save(a.output/'summary.json',summary)
    save(a.output/'paired_questions.json',deltas)
    write_csv(a.output/'paired_questions.csv',deltas)
    write_csv(a.output/'baseline_metrics.csv',base_rows)
    write_csv(a.output/'candidate_metrics.csv',new_rows)
    write_csv(a.output/'recovered.csv',[x for x in deltas if x['baseline_hit5']==0 and x['candidate_hit5']==1])
    write_csv(a.output/'regressed.csv',[x for x in deltas if x['baseline_hit5']==1 and x['candidate_hit5']==0])
    write_csv(a.output/'remaining_misses.csv',[x for x in deltas if x['candidate_hit5']==0])
    print(json.dumps({'paired':summary['paired_change_counts'],
        'baseline_hit5':base_summary[a.baseline_arm+'@5'],
        'candidate_hit5':new_summary[a.candidate_arm+'@5']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
