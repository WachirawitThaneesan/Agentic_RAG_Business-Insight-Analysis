"""Score frozen searchable payloads with the unchanged Stage A cell scorer."""
import argparse
import csv
import io
from collections import Counter
from pathlib import Path
from scripts.evaluate_comprehensive import load, save, sha
from scripts.evaluate_gemini_ocr_stage_a import score_fact


def run(a):
    facts=load(a.reference)['facts'];tables={}
    for c in load(a.corpus):
        if c.get('source_kind')!='table_csv' or not c['metadata'].get('recorded_region_directory'):continue
        m=c['metadata'];raw=list(csv.reader(io.StringIO(m['csv_text'])))
        table={**m,'page':c['source_pdf_page'],'rows':raw[1:]}
        tables.setdefault((c['document'],c['source_pdf_page']),[]).append(table)
    rows=[]
    for f in facts:
        code,page=f['page_id'].rsplit('_',1)
        rows.append({'id':f['id'],'page_id':f['page_id'],**score_fact(f,tables.get((code,int(page)),[]))})
    a.output.mkdir(parents=True,exist_ok=False)
    save(a.output/'details.json',rows)
    save(a.output/'summary.json',{'n_required':len(rows),'n_correct':sum(x['correct'] for x in rows),
        'states':dict(Counter(x['state'] for x in rows)),
        'reference_sha256':sha(a.reference),'corpus_sha256':sha(a.corpus),'scorer_sha256':sha('scripts/evaluate_gemini_ocr_stage_a.py'),
        'scope':'frozen searchable table payloads after shared production normalization and row eligibility; references used only for scoring'})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','corpus','output'):p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())
