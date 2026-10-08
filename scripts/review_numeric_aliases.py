"""Blind PDF-only alias/alternate-evidence review; never receives predictions."""
import argparse
import asyncio
from copy import deepcopy
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from decimal import Decimal
import pymupdf

from scripts.evaluate_comprehensive import load, save, sha
from scripts.bounded_cloud_meter import BoundedCloudMeter
from backend.services.answer_capture import _number_tokens
from backend.services.retrieval_rank import search_tokens, normalize_search_text

PROMPT='''Blindly review this original-PDF numeric reference relation. You see no
system answers, rankings or scores. The primary page and alternative pages were
pooled by literal reference-value matching against the ORIGINAL PDF, not by
application retrieval. Preserve the requested subject/measure, sign, scale,
year, actual-versus-target status and comparator; do not broaden the quantity.
Return JSON {"company_aliases":["..."],"measure_aliases":["..."],
"pages":[{"page":1,"supports_full_question":true,"visual_transcript":"...",
"reason":"..."}]} with one page record per supplied physical page.
Aliases must denote exactly the same company/subsidiary/owner and quantity in
the QUESTION/reference, based on PDF evidence. Include ordinary complete Thai
wordings (e.g. จำนวนสาขา... for a branch count) and real bilingual names only.
Never treat บริษัทฯ as a specific named entity alias, equate different
subsidiaries, strip a parenthetical qualifier changing the measure, or accept
a page just because the same number occurs. A alternative page must independently
establish ALL company/measure/value/unit/year/comparator relationships required
by the question. Do not substitute report year for a target/event year. Short
The question's introductory report year identifies the report edition; it does
not override the separately supplied REFERENCE.year_be target/event period.
visual transcripts must preserve relationships, not transcribe full pages.
HARD OUTPUT LIMIT: Each visual_transcript is ONLY the one relevant relation,
at most 300 characters. NEVER copy the page or unrelated paragraphs. Reasons
are at most one short sentence. The entire JSON should be under 1500 words.
If the frozen reference itself conflicts with the PDF, flag supports=false;
do not repair value/year/entity to make any result pass. No human certification.
'''


async def run(a):
    from backend.config import get_settings
    from backend.services import llm
    from google.genai import types
    a.output.mkdir(parents=True,exist_ok=a.resume)
    bank=load(a.reference);labels=load(a.labels);paths=load(a.pdf_paths)
    selected={(r['id'],r['quantity_index']) for r in load(a.review_ids)} if a.review_ids else None
    items={q['id']:q for q in bank['items']}
    lock={'reference_sha256':sha(a.reference),'labels_sha256':sha(a.labels),'pdf_paths_sha256':sha(a.pdf_paths),
        'code_sha256':sha(__file__),'prompt_sha256':hashlib.sha256(PROMPT.encode()).hexdigest(),
        'policy':'Original PDF/labels only; all predictions withheld; no value/year/unit/comparator changes',
        'human_confirmed':False,'primary_only':a.primary_only,
        'review_ids_sha256':sha(a.review_ids) if a.review_ids else None}
    if (a.output/'method_lock.json').exists() and load(a.output/'method_lock.json')!=lock:raise ValueError('Resume lock changed')
    save(a.output/'method_lock.json',lock)
    (a.output/'reviewer_code_frozen.py').write_bytes(Path(__file__).read_bytes())
    texts={};pdfs={}
    for d in bank['documents']:
        p=Path(paths[d['code']]);assert sha(p)==d['source_sha256']
        pdfs[d['code']]=pymupdf.open(p);texts[d['code']]=[p.get_text() for p in pdfs[d['code']]]
    output=[];changed=[]
    try:
        with BoundedCloudMeter(a.budget,a.output,max_new_attempts=None) as meter:
            for i,label in enumerate(labels,1):
                if selected is not None and (label['id'],label['quantity_index']) not in selected:
                    output.append(deepcopy(label));continue
                code=label['document'];primary=label['source_pdf_page'];value=Decimal(str(label['value']))
                tokens=set(search_tokens(label['measure']))
                pool=[]
                for page,text in enumerate(texts[code],1):
                    if page==primary:continue
                    if value in _number_tokens(text):
                        norm=normalize_search_text(text).casefold()
                        pool.append((sum(norm.count(t) for t in tokens if len(t)>1),page))
                pages=[primary]+[page for _,page in sorted(pool,key=lambda t:(-t[0],t[1]))[:3]]
                if a.primary_only:pages=[primary]
                path=a.output/'reviews'/f"{label['id']}_{label['quantity_index']}.json"
                payload={'QUESTION':items[label['id']]['question_th'],'REFERENCE':label,'PAGES':
                         [{'page':p,'native':texts[code][p-1]} for p in pages]}
                saved=load(path) if path.exists() else None
                if saved is None:
                    contents=[PROMPT+'\nINPUT:\n'+json.dumps(payload,ensure_ascii=False)]
                    contents += [types.Part.from_bytes(data=pdfs[code][p-1].get_pixmap(dpi=135).tobytes('png'),mime_type='image/png') for p in pages]
                    raw=[];decision=None;error=None
                    meter.phase.update(stage='blind_reference_alias_review',id=label['id'],quantity_index=label['quantity_index'])
                    for attempt in range(3):
                        try:
                            await llm._get_throttle().wait()
                            response=await asyncio.wait_for(llm._get_genai_client().aio.models.generate_content(
                                model=get_settings().GEMINI_MODEL,contents=contents,
                                config=types.GenerateContentConfig(temperature=0,max_output_tokens=6000,
                                    thinking_config=types.ThinkingConfig(thinking_budget=0),response_mime_type='application/json')),150)
                            raw.append(response.text or '');decision=json.loads(raw[-1])
                            if {r['page'] for r in decision['pages']}!=set(pages) or len(decision['pages'])!=len(pages):raise ValueError('Incomplete page audit')
                            if any(type(r['supports_full_question']) is not bool or not isinstance(r.get('visual_transcript'),str) for r in decision['pages']):raise ValueError('Invalid review fields')
                            for key in ('company_aliases','measure_aliases'):
                                if not isinstance(decision[key],list) or any(not isinstance(v,str) or not v.strip() for v in decision[key]):raise ValueError('Invalid aliases')
                            if any(len(r['visual_transcript'])>500 for r in decision['pages']):raise ValueError('Transcript is not a concise relation')
                            error=None;break
                        except Exception as exc:
                            error=type(exc).__name__;decision=None
                            if getattr(exc,'code',None)==429 and attempt<2:await asyncio.sleep(30 if attempt==0 else 45)
                    saved={'input_sha256':hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest(),
                           'pooled_pages':pages,'raw_outputs':raw,'decision':decision,'error':error}
                    save(path,saved)
                revised=deepcopy(label);decision=saved['decision']
                if decision:
                    primary_supported=next(p['supports_full_question'] for p in decision['pages'] if p['page']==primary)
                    if primary_supported:
                        revised.pop('blind_recheck_reference_conflict',None)
                        for key in ('company_aliases','measure_aliases'):
                            rejected={'บริษัทฯ','บริษัท','กลุ่มบริษัท','บริษัทย่อย','บริษัทและบริษัทย่อย'} if key=='company_aliases' else set()
                            revised[key]=sorted(set((revised.get(key) or [])+[v for v in decision[key] if v.strip() not in rejected]))
                        revised['alternate_pdf_pages']=sorted(set(revised.get('alternate_pdf_pages',[])+[
                            p['page'] for p in decision['pages'] if p['page']!=primary and p['supports_full_question'] and p['visual_transcript'].strip()]))
                        revised['identity_review_sha256']=sha(path)
                    else:revised['blind_recheck_reference_conflict']=True
                output.append(revised)
                if revised!=label:changed.append({'id':label['id'],'quantity_index':label['quantity_index'],
                                                'company_aliases':revised.get('company_aliases'),
                                                'measure_aliases':revised.get('measure_aliases'),
                                                'alternate_pdf_pages':revised.get('alternate_pdf_pages')})
                save(a.output/'numeric_labels_v6_locked.json',output);save(a.output/'changes.json',changed)
                print(f'Blind numeric identity/evidence review {i}/{len(labels)} {label["id"]}: {"measured" if decision else "failed"}',flush=True)
    finally:
        for pdf in pdfs.values():pdf.close()
    save(a.output/'numeric_labels_v6_locked.json',output)
    save(a.output/'summary.json',{'n_labels':len(output),'n_changed':len(changed),
        'n_reference_conflicts':sum(bool(n.get('blind_recheck_reference_conflict')) for n in output),
        'values_units_years_comparators_unchanged':all(all(n[k]==old[k] for k in
            ('company','measure','value','unit','year_be','comparison_operator','source_pdf_page')) for n,old in zip(output,labels)),
        'human_confirmed':False,'predictions_supplied_to_reviewer':False})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','labels','pdf-paths','budget','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--review-ids',type=Path,help='Frozen subset of IDs/quantity indices; inherited labels preserved')
    p.add_argument('--primary-only',action='store_true',help='Primary relation/aliases only; no new alternate pages')
    p.add_argument('--resume',action='store_true');a=p.parse_args();asyncio.run(run(a))


if __name__=='__main__':main()
