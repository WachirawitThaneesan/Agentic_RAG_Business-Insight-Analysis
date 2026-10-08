"""Verify every reference span against hash-locked original physical PDF pages."""
import argparse
import re
from collections import Counter
import pymupdf
from scripts.evaluate_comprehensive import load,save,sha


def main():
    p=argparse.ArgumentParser();p.add_argument('--reference',required=True)
    p.add_argument('--sources',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();bank=load(args.reference);source=load(args.sources)
    pages={}
    for doc in source['documents']:
        if sha(doc['path'])!=doc['source_sha256']:raise ValueError('PDF hash mismatch')
        with pymupdf.open(doc['path']) as pdf:
            pages[doc['code']]=[re.sub(r'\s+',' ',page.get_text()).strip() for page in pdf]
    audit=[]
    for item in bank['items']:
        quote=item['reference_quote'];texts=pages[item['document']]
        audit.append({'id':item['id'],'source_pdf_page':item['source_pdf_page'],
            'document':item['document'],'quote_in_original_page':quote in texts[item['source_pdf_page']-1],
            'exact_quote_alternate_pages':[i+1 for i,text in enumerate(texts)
                if quote in text and i+1!=item['source_pdf_page']]})
    from pathlib import Path
    save(Path(args.output),{'reference_sha256':sha(args.reference),'n_questions':len(audit),
        'n_quote_matches':sum(r['quote_in_original_page'] for r in audit),
        'n_unique_pages':len({(r['document'],r['source_pdf_page']) for r in audit}),
        'questions_per_document':dict(Counter(r['document'] for r in audit)),
        'n_questions_with_alternate_exact_quote_pages':sum(bool(r['exact_quote_alternate_pages']) for r in audit),
        'review_level':'Mechanical original PDF-text span verification. Semantic entailment and human certification pending.',
        'details':audit})
    print('Verified',sum(r['quote_in_original_page'] for r in audit),'/',len(audit))

if __name__=='__main__':main()
