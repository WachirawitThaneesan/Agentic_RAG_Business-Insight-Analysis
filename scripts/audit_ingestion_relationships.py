"""Independent original-image probes, then audit recorded production OCR.

No bank questions, application answers or rankings are inputs. This measures
six deterministic-order relation probes per original page, not all PDF cells.
"""
import argparse,asyncio,hashlib,json
from pathlib import Path
import pymupdf
from scripts.evaluate_comprehensive import load,save,sha
from scripts.bounded_cloud_meter import BoundedCloudMeter
from backend.eval.comprehensive import quote_span

READ='''Read ONLY the original Thai PDF page image and native text as data.
Choose up to SIX distinct explicit numeric or qualitative relations in reading
order, spreading them across tables/columns/sections when possible. Preserve
actual vs target, company vs subsidiary, consolidated vs separate, row, column,
year, sign, scale/unit and approximate/bound status. Do not compute ratios or
invent unreadable cells. Return {"relations":[{"index":0,"kind":"table|prose|chart",
"relationship":"complete concise relation in Thai","value":"exact value or null",
"unit":"unit or null","year_be":2567,"scope":"company/row/column",
"visual_transcript":"one short original-image evidence span"}],
"visible_tables":true,"source_readability":"readable|partial|unreadable"}.
Each transcript <=300 characters. No human certification. No app data supplied.
'''
AUDIT='''Audit recorded extraction against the ORIGINAL PDF image and the
independently selected source relations. You see no RAG answers or scores.
Return {"relations":[{"index":0,"state":"correct|wrong_relationship|omitted|unreadable",
"extracted_quote":"short EXACT extracted text or empty","reason":"short reason"}],
"table_presence":[{"table_index":0,"state":"supported|invented|unreadable",
"reason":"short original-image comparison"}],
"additional_error":"one material omitted/misassigned relation or empty"}.
Exactly one record for every provided relation and every recorded structured
table. Correct requires full company/subsidiary, row/column/year/unit/scale/sign/
value and comparator relationship in the EXTRACTION; matching a number alone
is insufficient. A table with financial-looking dummy rows is invented unless
actually printed on this page. Arithmetic balance does not certify extraction.
Judge missing column/header context as wrong or omitted, never fill from PDF.
Quotes <=200 characters, reasons <=150 characters. No human certification.
'''

async def run(a):
    from backend.config import get_settings
    from backend.services import llm
    from google.genai import types
    a.output.mkdir(parents=True,exist_ok=a.resume)
    plan=load(a.run_dir/'plan_locked.json');lock={'run_plan_sha256':sha(a.run_dir/'plan_locked.json'),
        'stored_page_sha256':{p.name:sha(p) for p in sorted((a.run_dir/'stored_pages').glob('*.json'))},
        'code_sha256':sha(__file__),'prompts_sha256':hashlib.sha256((READ+AUDIT).encode()).hexdigest(),
        'policy':'Original image source probes before extraction audit; no predictions/reference-bank inputs',
        'human_confirmed':False,'sample_scope':'up to six ordered relations per page; not exhaustive cell accuracy'}
    if (a.output/'method_lock.json').exists() and load(a.output/'method_lock.json')!=lock:raise ValueError('Changed audit resume inputs/code')
    save(a.output/'method_lock.json',lock);(a.output/'reviewer_code_frozen.py').write_bytes(Path(__file__).read_bytes())
    results=[]
    with BoundedCloudMeter(a.budget,a.output,max_new_attempts=None) as meter:
        async def request(stage,key,prompt,payload,png):
            path=a.output/stage/(key+'.json')
            if path.exists():
                cached=load(path)
                if (cached.get('input_sha256')!=hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest()
                    or cached.get('source_image_sha256')!=hashlib.sha256(png).hexdigest()):
                    raise ValueError('Cached relationship evidence differs from exact source/input')
                return cached
            raw=[];parsed=None;error=None
            meter.phase={'stage':stage,'id':key}
            for attempt in range(3):
                try:
                    await llm._get_throttle().wait()
                    resp=await asyncio.wait_for(llm._get_genai_client().aio.models.generate_content(
                        model=get_settings().GEMINI_MODEL,
                        contents=[prompt+'\nINPUT:\n'+json.dumps(payload,ensure_ascii=False),
                                  types.Part.from_bytes(data=png,mime_type='image/png')],
                        config=types.GenerateContentConfig(temperature=0,max_output_tokens=6000,
                            thinking_config=types.ThinkingConfig(thinking_budget=0),response_mime_type='application/json')),150)
                    raw.append(resp.text or '');parsed=json.loads(raw[-1]);error=None;break
                except Exception as exc:
                    error=type(exc).__name__;parsed=None
                    if getattr(exc,'code',None)==429 and attempt<2:await asyncio.sleep(30 if attempt==0 else 45)
            record={'parsed':parsed,'raw_outputs':raw,'error':error,
                    'input_sha256':hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest(),
                    'source_image_sha256':hashlib.sha256(png).hexdigest()}
            save(path,record);return record
        for d in plan['documents']:
            if sha(d['original_pdf'])!=d['original_sha256']:raise ValueError('Original PDF changed')
            with pymupdf.open(d['original_pdf']) as pdf:
                for mapping in d['page_map']:
                    p=mapping['original_pdf_page'];uploaded=mapping['uploaded_pdf_page'];key=f"{d['code']}_{p}"
                    image=pdf[p-1].get_pixmap(dpi=160).tobytes('png')
                    original={'company_report':d['code'],'physical_pdf_page':p,'native':pdf[p-1].get_text()}
                    source=await request('source_probes',key,READ,original,image)
                    relations=(source.get('parsed') or {}).get('relations',[])
                    source_valid=(isinstance(relations,list) and 0<len(relations)<=6 and
                        [r.get('index') for r in relations]==list(range(len(relations))) and
                        all(isinstance(r.get('visual_transcript'),str) and 0<len(r['visual_transcript'])<=400 for r in relations))
                    stored_path=a.run_dir/'stored_pages'/f"{d['code']}_{uploaded}.json"
                    stored=load(stored_path)
                    tables=stored.get('structured_tables',[])
                    extraction={'raw_prose_regions':stored.get('raw_ocr_pages',[]),'structured_tables':tables,
                        'table_quality_reports':stored.get('quality_reports',[])}
                    evidence='\n'.join([r.get('markdown','') for r in extraction['raw_prose_regions']]+[t.get('csv_text','') for t in tables])
                    audited=await request('extraction_audits',key,AUDIT,
                        {'source_relations':relations,'EXTRACTION':extraction},image) if source_valid else {'parsed':None,'error':'invalid_source_probes'}
                    decision=audited.get('parsed') or {};verdicts=decision.get('relations',[]);presence=decision.get('table_presence',[])
                    valid=(len(verdicts)==len(relations) and {r.get('index') for r in verdicts}==set(range(len(relations))) and
                        len(presence)==len(tables) and {r.get('table_index') for r in presence}==set(range(len(tables))))
                    details=[]
                    for r in verdicts:
                        state=r.get('state')
                        if state not in ('correct','wrong_relationship','omitted','unreadable'):valid=False
                        verified=quote_span(r.get('extracted_quote'),evidence) if r.get('extracted_quote') else None
                        if state=='correct' and not verified:state='quote_unverifiable'
                        details.append({**r,'state':state,'quote_verified':bool(verified)})
                    results.append({'id':key,'document':d['code'],'original_pdf_page':p,'uploaded_pdf_page':uploaded,
                        'original_pdf_sha256':d['original_sha256'],'stored_page_sha256':sha(stored_path),
                        'source_probe_count':len(relations),'source_probes_valid':source_valid,
                        'audit_valid':source_valid and valid and bool(audited.get('parsed')),
                        'relations':details,'table_presence':presence,'additional_error':decision.get('additional_error'),
                        'source_error':source.get('error'),'audit_error':audited.get('error'),'human_confirmed':False})
                    save(a.output/'details.json',results)
                    measured=[r for page in results if page['audit_valid'] for r in page['relations']]
                    known=[r for r in measured if r['state'] in ('correct','wrong_relationship','omitted')]
                    save(a.output/'summary.json',{'n_pages_planned':sum(len(doc['page_map']) for doc in plan['documents']),
                        'n_pages_audited':len(results),'n_valid_page_audits':sum(x['audit_valid'] for x in results),
                        'n_relation_probes':sum(x['source_probe_count'] for x in results),'n_measured_relations':len(known),
                        'n_correct':sum(r['state']=='correct' for r in known),
                        'accuracy_measured_source_relation_probes':sum(r['state']=='correct' for r in known)/len(known) if known else None,
                        'n_unknown_relation_verdicts':len(measured)-len(known),
                        'n_required_relations_all_valid_source_probes':sum(x['source_probe_count'] for x in results if x['source_probes_valid']),
                        'n_unknown_including_invalid_page_audits':sum(x['source_probe_count'] for x in results if x['source_probes_valid'])-len(known),
                        'n_invalid_source_probe_pages':sum(not x['source_probes_valid'] for x in results),
                        'strict_lower_bound_all_valid_source_probes':sum(r['state']=='correct' for r in known)/sum(x['source_probe_count'] for x in results if x['source_probes_valid']) if any(x['source_probes_valid'] for x in results) else None,
                        'n_invented_tables':sum(t.get('state')=='invented' for page in results if page['audit_valid'] for t in page['table_presence']),
                        'human_confirmed':False,'same_model_family_audit':True,
                        'scope':'Sampled original-PDF relationships; does not certify every cell or arbitrary arithmetic-balanced table'})
                    print(f"Relationship audit {len(results)} pages {key}: {'valid' if results[-1]['audit_valid'] else 'unresolved'}",flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('run-dir','budget','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--resume',action='store_true');asyncio.run(run(p.parse_args()))
if __name__=='__main__':main()
