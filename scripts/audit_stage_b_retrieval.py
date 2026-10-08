"""Source/candidate/ranking diagnosis with unchanged alternate-page scorer."""
import argparse
from collections import Counter
from itertools import zip_longest
from pathlib import Path
from backend.eval.comprehensive import page_metrics
from scripts.evaluate_comprehensive import load, save, sha, write_csv


def run(a):
    bank=load(a.reference);records=load(a.retrieval);chunks=load(a.corpus)
    docs={d['code']:d for d in bank['documents']};items={q['id']:q for q in bank['items']}
    rows=[]
    for record in records:
        q=items[record['id']];debug=record['debug']['lexical_first']
        all_pages=[{'filename':c['filename'],'source_pdf_page':c['source_pdf_page']} for c in chunks]
        available=page_metrics(q,all_pages,docs,k=len(all_pages))
        lexical=debug['keyword_pages'];dense=debug['semantic_pages']
        def score(hits):return page_metrics(q,hits,docs,k=max(len(hits),1))
        union=[]
        for h in lexical+dense:
            if (h['filename'],h['source_pdf_page']) not in {(r['filename'],r['source_pdf_page']) for r in union}: union.append(h)
        interleaved=[];seen=set()
        for pair in zip_longest(lexical,dense):
            for h in pair:
                if h is None:continue
                key=(h['filename'],h['source_pdf_page'])
                if key not in seen:interleaved.append(h);seen.add(key)
        top=score(record['arms']['lexical_first'])
        pooled=score(union)
        row={'id':q['id'],'document':q['document'],'primary_page':q['source_pdf_page'],
            'in_index':available.get('complete_evidence'),'hit5':top.get('hit'),'required_recall5':top.get('recall'),
            'complete5':top.get('complete_evidence'),'lexical_first_rank50':score(lexical).get('first_relevant_rank'),
            'dense_first_rank50':score(dense).get('first_relevant_rank'),
            'union50_hit':pooled.get('hit'),'union50_complete':pooled.get('complete_evidence'),
            'union20_hit':score(lexical[:20]+dense[:20]).get('hit'),
            'candidate_union20_distinct_hit':score(interleaved[:20]).get('hit'),
            'candidate_union50_distinct_hit':score(interleaved[:50]).get('hit'),
            'candidate_union20_required_recall':score(interleaved[:20]).get('recall'),
            'candidate_union50_required_recall':score(interleaved[:50]).get('recall'),
            'numeric_route':debug['numeric_route'], 'scope_ids':debug['document_scope_ids']}
        row['cause']=('pass' if top.get('hit') else 'missing_index' if not available.get('hit') else
            'ranking_or_page_budget' if pooled.get('hit') else 'outside_saved_top50_or_scope_unknown')
        rows.append(row)
    a.output.mkdir(parents=True,exist_ok=False)
    save(a.output/'diagnostics.json',rows);write_csv(a.output/'diagnostics.csv',rows)
    write_csv(a.output/'remaining_misses.csv',[r for r in rows if not r['hit5']])
    save(a.output/'summary.json',{'n':len(rows),'causes':dict(Counter(r['cause'] for r in rows)),
        'union20_hits':sum(r['union20_hit'] for r in rows),'union50_hits':sum(r['union50_hit'] for r in rows),
        'union50_complete':sum(r['union50_complete'] for r in rows),
        'candidate_union20_distinct_hits':sum(r['candidate_union20_distinct_hit'] for r in rows),
        'candidate_union50_distinct_hits':sum(r['candidate_union50_distinct_hit'] for r in rows),
        'candidate_union20_required_recall':sum(r['candidate_union20_required_recall'] for r in rows)/len(rows),
        'candidate_union50_required_recall':sum(r['candidate_union50_required_recall'] for r in rows)/len(rows),
        'reference_sha256':sha(a.reference),'retrieval_sha256':sha(a.retrieval),'corpus_sha256':sha(a.corpus),
        'scope':'alternate evidence sets/required multi-page metrics unchanged; legacy union20/50 means per channel. candidate_union20/50_distinct interleaves lexical/dense ranks with page dedup and counts total pages; diagnostic pool coverage, not top5 accuracy',
        'new_sdk_attempts':0,'no_gold_used_by_ranking':True})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','retrieval','corpus','output'):p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())
