"""Offline, label-aware diagnostic ablations. Never used to supply evidence.

Native text, query/corpus vectors and document-name scoping are the only ranking
inputs. Labels only score outputs afterwards. These are tuned diagnostics.
"""
import argparse
import re
from collections import Counter
from pathlib import Path
import numpy as np
from scripts.benchmark_large_retrieval import corpus
from scripts.evaluate_comprehensive import load, save, sha
from backend.services.retrieval_rank import bm25_rank, matched_document_aliases, without_document_aliases, unique_pages, remove_repeated_navigation
from backend.services.rag import _extract_keyword_terms, _reciprocal_rank_fusion


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','sources','vectors','query-vectors','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    bank=load(a.reference);chunks=corpus(load(a.sources))
    v=np.load(a.vectors)['vectors'];qv=np.load(a.query_vectors)['vectors']
    if len(qv)!=len(bank['items']):raise ValueError('Query count mismatch')
    from scripts.benchmark_heldout import _embed_texts
    # Cache identity checks never invoke a model for a valid cache.
    _embed_texts([c['text'] for c in chunks],'bge-m3',a.vectors)
    _embed_texts([q['question_th'] for q in bank['items']],'bge-m3',a.query_vectors)
    codes={d['code']:i+1 for i,d in enumerate(bank['documents'])}
    docs=[(codes[d['code']],d['source_file']) for d in bank['documents']]
    rows=[{**c,'document_id':codes[c['document']],'page':c['source_pdf_page'],'text':c['text']} for c in chunks]
    norm=np.maximum(np.linalg.norm(v,axis=1),1e-12);records=[];counts=Counter()
    cleaned_rows=remove_repeated_navigation(rows)
    for i,q in enumerate(bank['items']):
        query=q['question_th'];scope,aliases=matched_document_aliases(query,docs)
        candidates=[r for r in rows if not scope or r['document_id'] in scope]
        ranking_query=without_document_aliases(query,aliases)
        terms=_extract_keyword_terms(ranking_query)
        lexical=bm25_rank(' '.join(terms) or ranking_query,candidates)
        clean_candidates=[r for r in cleaned_rows if not scope or r['document_id'] in scope]
        clean_lexical=bm25_rank(' '.join(terms) or ranking_query,clean_candidates)
        scores=v@qv[i]/(norm*max(np.linalg.norm(qv[i]),1e-12))
        dense=[rows[int(j)] for j in np.argsort(-scores,kind='stable')
            if not scope or rows[int(j)]['document_id'] in scope][:50]
        numeric=bool(re.search(r'เท่าไร|เท่าไหร่|กี่|ร้อยละ|เปอร์เซ็นต์|%|จำนวน|มูลค่า|อัตรา|รายได้|กำไร|หนี้สิน|สินทรัพย์|เงินปันผล|คะแนน',query))
        original=(unique_pages([*lexical,*dense])[:5] if numeric else _reciprocal_rank_fusion(dense,lexical,5))
        # Weak lexical matches at the tail should not get fusion credit merely
        # by repeating a ubiquitous year/company term. Bound both page lists.
        bounded=_reciprocal_rank_fusion(unique_pages(dense)[:20],unique_pages(lexical)[:20],5)
        bounded_route=original if numeric else bounded
        variants={'alias_current':original,'bounded_qualitative':bounded_route,
            'fusion_all':bounded,'lexical_only':unique_pages(lexical)[:5]}
        def weighted(lex,weight):
            fused={}
            for ranking,w in ((unique_pages(dense),1),(unique_pages(lex),weight)):
                for rank,hit in enumerate(ranking):
                    key=(hit['document_id'],hit['page'])
                    prior=fused.setdefault(key,{'hit':hit,'score':0})
                    prior['score']+=w/(60+rank+1)
            return [r['hit'] for r in sorted(fused.values(),key=lambda r:r['score'],reverse=True)[:5]]
        for w in (1.5,2.0):variants[f'weighted_{w}']=original if numeric else weighted(lexical,w)
        variants['navigation_route']=(unique_pages([*clean_lexical,*dense])[:5] if numeric
            else weighted(clean_lexical,2.0))
        variants['navigation_lexical']=unique_pages([*clean_lexical,*dense])[:5]
        def is_gold(r):return r['document']==q['document'] and r['page']==q['source_pdf_page']
        ranks={arm:next((j+1 for j,r in enumerate(hits) if is_gold(r)),None) for arm,hits in variants.items()}
        for arm,rank in ranks.items():counts[arm]+=rank is not None
        gold_exists=any(is_gold(r) for r in rows)
        lr=next((j+1 for j,r in enumerate(unique_pages(lexical)) if is_gold(r)),None)
        dr=next((j+1 for j,r in enumerate(unique_pages(dense)) if is_gold(r)),None)
        reason=('missing_index' if not gold_exists else 'scope_excluded' if scope and codes[q['document']] not in scope
            else 'fusion_or_route' if (lr and lr<=5) or (dr and dr<=5) else 'lexical_or_dense_ranking')
        records.append({'id':q['id'],'document':q['document'],'page':q['source_pdf_page'],
            'scope':sorted(scope) if scope else None,'numeric_route':numeric,'lexical_page_rank':lr,
            'dense_candidate_page_rank':dr,'ranks':ranks,'reason':reason,
            'arms':{arm:[{'filename':h['filename'],'source_pdf_page':h['page']} for h in hits]
                for arm,hits in variants.items()}})
        if (i+1)%50==0:print(f'Diagnosed {i+1}/{len(bank["items"])} {dict(counts)}',flush=True)
    save(a.output/'diagnostics.json',records)
    save(a.output/'retrieval.json',[{'id':r['id'],'arms':r['arms']} for r in records])
    save(a.output/'summary.json',{'n':len(records),'hits5':dict(counts),
        'causes_among_alias_misses':dict(Counter(r['reason'] for r in records if not r['ranks']['alias_current'])),
        'reference_sha256':sha(a.reference),'script_sha256':sha(__file__),
        'scope':'Diagnostic ablations tuned on these reports; no gold supplied to ranking'})


if __name__=='__main__':main()
