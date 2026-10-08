"""Step 1: offline status audit, numeric drafts and an unfilled human review packet."""
from __future__ import annotations
import argparse, json, re
from collections import Counter, defaultdict
from pathlib import Path
import pymupdf
from backend.eval.contracts import VERSION, TARGETS, classify_claim, actual_citation_metrics
from backend.eval.numeric import mentions_in, years_in
from scripts.evaluate_comprehensive import load, save, sha, write_csv


def parsed_raw(saved):
    for text in reversed(saved.get('raw_outputs',[])):
        try:
            data=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip()))
            if isinstance(data,dict) and 'answer_claims' in data:return data
        except (ValueError,TypeError):pass
    raise ValueError('No raw judge decision to audit')


def numeric_drafts(bank):
    docs={d['code']:d for d in bank['documents']};drafts=[]
    for q in bank['items']:
        text=q['reference_answer'];years=years_in(text)
        quantities=[m for m in mentions_in(text) if m.unit and m.unit!='ปี'
            and not any(m.start==a and m.end==b for a,b,_ in years)]
        if not quantities:continue
        qyears=sorted({y for _,_,y in years_in(q['question_th'])})
        report_only=bool(re.search(r'ตามรายงาน|รายงาน(?:ประจำปี|ปี)|รายงานปี',q['question_th']))
        for n,m in enumerate(quantities):
            drafts.append({'id':q['id'],'quantity_index':n,'company':None,
                'company_candidates':[q['document']], 'measure':None,
                'measure_hint':q.get('topic') or q['question_th'],
                'value':str(m.value),'unit':m.unit,
                'quantity_lexeme':text[m.start:m.end],
                'year_be':None,'requested_year_candidates_be':qyears,
                'year_kind_hint':'report_context_only' if report_only else 'needs_source_check',
                'document':q['document'],'source_pdf_page':q['source_pdf_page'],
                'source_sha256':docs[q['document']]['source_sha256'],
                'evidence_quote':q.get('reference_quote',''),
                'question':q['question_th'],'reference_answer':q['reference_answer'],
                'tolerance':0,'rounding_decimals':None,'review_status':'draft_needs_blind_pdf_review',
                'official_score_eligible':False,
                'warning':'Report entity/year is not assumed to be the numeric fact entity/year.'})
    return drafts


def run(a):
    p=a.parent;o=a.output;o.mkdir(parents=True,exist_ok=False)
    for name in ('backend/eval/contracts.py','backend/eval/comprehensive.py',
        'backend/eval/numeric.py','backend/eval/score_layers.py','scripts/audit_evaluation_contract.py'):
        target=o/'frozen_code'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(Path(name).read_bytes())
    audit=p/'answer_consistent_audit';rows=load(audit/'details.json')
    bank=load(p/'labels_v3/reference_locked.json');byid={q['id']:q for q in bank['items']}
    conf=load(p/'answer_config.json')['cohorts'][0]
    records={r['id']:r for r in load(conf['answers']['app_gemini'])}
    docs={d['code']:d for d in bank['documents']}
    pdfs={k:Path(v) for k,v in conf['pdf_paths'].items()}
    for code,path in pdfs.items():
        if sha(path)!=docs[code]['source_sha256']:raise ValueError('Changed PDF '+code)
    claims=[];answers=[];groups=defaultdict(list);raws={}
    for row in rows:
        raw=parsed_raw(load(audit/'judge_outputs'/f"{row['key']}.json"));raws[row['id']]=raw
        states=[]
        for n,c in enumerate(raw['answer_claims']):
            d=classify_claim(c,context=row['context'],reference=row['reference']);states.append(d)
            for field in ('faithfulness','factual'):
                claims.append({'id':row['id'],'claim_index':n,'claim':c['text'],'dimension':field,**d[field]})
        full=records[row['id']].get('full_result',{})
        actual=full.get('claim_citations')
        captured_claims=full.get('answer_claims')
        expected_claims=[c['text'] for c in raw['answer_claims']]
        # Indices from an application and an AI decomposition must never be
        # assumed to identify the same claims without a captured mapping.
        aligned=isinstance(captured_claims,list) and captured_claims==expected_claims
        decisions=[{'claim_index':n,'source_index':x['source_index'],
            'verdict':'supported' if c['faithfulness']=='supported' else c['faithfulness'],
            'quote':x.get('quote','')} for n,c in enumerate(raw['answer_claims'])
            for x in c.get('citations',[]) if type(x.get('source_index')) is int]
        citation=actual_citation_metrics(raw['answer_claims'],row['sources'],actual if aligned else None,
            support_decisions=decisions)
        citation['captured_application_mapping_aligned_with_audit']=aligned
        proposed=[x for c in raw['answer_claims'] for x in c.get('citations',[])]
        answers.append({'id':row['id'],'n_claims':len(states),'actual_citation':citation,
            'n_judge_proposed_support_links':len(proposed),
            'legacy_returned_source_support_utilization':row['claims']['citation_source_precision'],
            'declared_citation_scope':'Structured claim mapping only; legacy prose pages are a separate location check'})
        if any(d[f]['state']=='contradicted_ai_needs_review' for d in states for f in ('faithfulness','factual')):
            group='contradicted_ai'
        elif any(d[f]['state']=='quote_unverifiable' for d in states for f in ('faithfulness','factual')):
            group='quote_unverifiable'
        elif states and all(d[f]['state']=='supported_quote_verified' for d in states for f in ('faithfulness','factual')):
            group='supported'
        else:group='insufficient_or_abstention'
        groups[group].append(row)
    save(o/'claim_statuses.json',claims);write_csv(o/'claim_statuses.csv',claims)
    save(o/'actual_citation_audit.json',answers)
    drafts=numeric_drafts(bank);save(o/'numeric_label_drafts.json',drafts)
    write_csv(o/'numeric_label_drafts.csv',drafts)
    save(o/'targets_locked.json',{'method_version':VERSION,'targets':TARGETS,
        'scope':'Proposed engineering targets, not universal thesis pass thresholds',
        'measurement':'Locked definitions, per-metric denominator, report-level unseen split',
        'evaluation_coverage_target':.95,'human_validation':'pending; no fabricated certification',
        'uncertainty':'Report judge failures, unavailable metrics and intervals separately; no removing hard failures'})
    selected=[]
    for group in ('supported','contradicted_ai','quote_unverifiable','insufficient_or_abstention'):
        bydoc=defaultdict(list)
        for row in groups[group]:bydoc[byid[row['id']]['document']].append(row)
        pick=[]
        while len(pick)<6 and any(bydoc.values()):
            for code in sorted(bydoc):
                if bydoc[code] and len(pick)<6:pick.append(bydoc[code].pop(0))
        selected.extend((group,row) for row in pick)
    human=[];blind=['# ตรวจเฉลยจาก PDF ก่อนดูคำตอบระบบ','',
        'กรอกชื่อผู้ตรวจ วันที่ และคำตัดสินด้วยตนเอง AI ยังไม่ได้รับรองเฉลยเหล่านี้',
        'ขั้นแรกเปิด PDF/ภาพ ตรวจบริษัท รายการ ค่า ปี หน่วย และหน้า โดยยังไม่เปิด calibration sheet',
        'ปีรายงานไม่ใช่ปีเหตุการณ์โดยอัตโนมัติ ยอมรับคำพ้องเมื่อข้อเท็จจริงเดียวกัน และบันทึกหน้าทางเลือก','']
    calibration=['# ตรวจคำตอบและปรับเทียบ AI judge','',
        'ใช้หลังตรวจเฉลยจาก PDF แล้ว เลือก: รองรับ / ผิด / หลักฐานไม่พอ / ตรวจไม่ได้',
        'Faithfulness ดูเฉพาะ context ที่โมเดลได้รับ; Factuality เทียบ PDF เดิม',
        'อย่าเรียกคำอ้างที่หาไม่พบว่าเป็นคำตอบผิดทันที ให้ระบุว่าข้อมูลขาดหรือผู้ตรวจคัดคำอ้างผิด',
        'ไฟล์ context.txt เป็นหลักฐานทั้งหมดที่ใช้สร้างคำตอบจริง','']
    for group,row in selected:
        q=byid[row['id']];code=q['document'];page=q['source_pdf_page']
        image=o/'review_pages'/f'{code}_{page:04d}.png'
        if not image.exists():
            image.parent.mkdir(exist_ok=True)
            with pymupdf.open(pdfs[code]) as pdf:pdf[page-1].get_pixmap(dpi=150).save(image)
        case=o/'review_cases'/row['id'];case.mkdir(parents=True)
        (case/'context.txt').write_text(row['context'],encoding='utf-8')
        save(case/'original_inputs.json',{'question':q,'sources':row['sources'],
            'answer':row['answer'],'raw_judge':raws[row['id']]})
        blind.extend([f"## {q['id']} — {code}, physical PDF page {page}",q['question_th'],
            '','เฉลยที่เสนอ: '+q['reference_answer'],'',f'[เปิด PDF]({pdfs[code]})',
            f'[ภาพหน้า PDF]({image})','', 'คำตัดสิน: ______  เฉลยแก้ไข/หน้าทางเลือก/เหตุผล: ______',''])
        calibration.extend([f"## {q['id']}",q['question_th'],'','คำตอบระบบ: '+row['answer'],'',
            f'[หลักฐานที่โมเดลได้รับจริง]({case / "context.txt"})','',
            'Faithfulness: ______  Factuality: ______  ความครบถ้วน: ______  Citation: ______',
            'คำอ้างสั้นจาก PDF/context และเหตุผล: ______',''])
        human.append({'id':q['id'],'sampling_group':group,'document':code,'physical_pdf_page':page,
            'reviewer_name':'','review_date':'','reference_verdict':'','corrected_reference':'',
            'accepted_alternate_pages':'','faithfulness_verdict':'','factual_verdict':'',
            'required_fact_coverage':'','actual_citation_verdict':'','evidence_quote':'','reason':'',
            'human_completed':False})
    (o/'human_reference_review.md').write_text('\n'.join(blind),encoding='utf-8')
    (o/'human_judge_calibration.md').write_text('\n'.join(calibration),encoding='utf-8')
    write_csv(o/'human_review_sheet.csv',human)
    summary={'method_version':VERSION,'n_saved_answers':len(rows),
        'claim_counts_by_dimension':{f:dict(Counter(c['state'] for c in claims if c['dimension']==f))
            for f in ('faithfulness','factual')},
        'n_actual_claim_citation_mappings':sum(x['actual_citation']['n_actual_links'] is not None for x in answers),
        'n_numeric_draft_quantities':len(drafts),'n_numeric_draft_questions':len({d['id'] for d in drafts}),
        'n_human_review_cases_prepared':len(human),'n_human_completed':0,
        'n_provisional_ai_contradictions_human_confirmed':0,
        'new_model_calls':0,'old_scores_unchanged':True,'retrieval_and_generation_unchanged':True}
    save(o/'summary.json',summary)
    save(o/'method_lock.json',{'method_version':VERSION,'source_details_sha256':sha(audit/'details.json'),
        'source_reference_sha256':sha(p/'labels_v3/reference_locked.json'),
        'source_config_sha256':sha(p/'answer_config.json'),
        'code_sha256':{'backend/eval/contracts.py':sha(Path('backend/eval/contracts.py')),
            'scripts/audit_evaluation_contract.py':sha(__file__)},
        'scope':'Offline reinterpretation of observations, not a new experiment or score improvement'})
    print(json.dumps(summary,ensure_ascii=False))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    run(p.parse_args())


if __name__=='__main__':main()
