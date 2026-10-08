"""Freeze a new AI-provisional diagnostic bank after original-PDF review.

The previous reference bank and every measured score remain immutable. This
script incorporates explicit source-image adjudications; it never claims human
review or silently drops a question that is inconvenient for retrieval.
"""
from __future__ import annotations
import argparse, copy, csv, json
from pathlib import Path
from backend.eval.contracts import validate_numeric_label
from backend.eval.comprehensive import quote_span, is_abstention
from scripts.evaluate_comprehensive import load, save, sha, write_csv

# These decisions were made after opening the named original PDF pages. The
# earlier Gemini decisions remain in blind_labels_locked.json for comparison.
VISUAL_ADJUDICATIONS = {
    'B0143': ('PTTEP',179,'The page states ณ วันที่ 31 ธันวาคม 2567 and กรรมการเพศหญิง 2 คนจากกรรมการทั้งหมด 15 คน. The AI claim of a year mismatch contradicts its own cited year.'),
    'B0285': ('PTT',36,'The NGV public-transport paragraph explicitly says ในปี 2567 and รวม 506 ล้านบาท. The AI read 2557 from a different clause.'),
    'B0275': ('CPAXT',23,'The question says ตามรายงานปี 2567, a report-context year, and the page describes reducing apparel/appliance space and expanding fresh-food/cooking space.'),
    'B0295': ('CPAXT',26,'The page bullet การปรับปรุงบริการดิจิทัล says IT infrastructure supports digital payment; the AI attended to an unrelated floor-area paragraph. The question/reference are clarified to report context only.'),
}

EDITS = {
    'B0286': {
        'question_th':'ตามรายงาน ปตท. ปี 2567 ณ สิ้นเดือนธันวาคม 2567 จำนวนรถยนต์ที่ใช้ NGV เป็นเชื้อเพลิงทั่วประเทศรวมกี่คัน?',
        'reference_answer':'ณ สิ้นเดือนธันวาคม 2567 จำนวนรถยนต์ที่ใช้ NGV เป็นเชื้อเพลิงทั่วประเทศรวม 237,815 คัน (อ้างอิงกรมการขนส่งทางบก)',
        'reason':'Clarify this is the national vehicle fleet, not vehicles owned by PTT.'},
    'B0306': {
        'question_th':'ตามรายงาน ปตท. ปี 2567 เมื่อวันที่ 30 สิงหาคม 2562 กบง. เห็นชอบแนวทางทดลองนำเข้า LNG แบบตลาดจรเพื่อทดสอบการแข่งขันเสรี โดยหน่วยงานใดเป็นผู้นำเข้าและกำหนดเพดานปริมาณเท่าใด?',
        'reference_answer':'กบง. เห็นชอบแนวทางทดลองนำเข้า LNG แบบตลาดจร (Spot) ของ กฟผ. ในปริมาณไม่เกิน 200,000 ตัน เมื่อวันที่ 30 สิงหาคม 2562',
        'reason':'Original PDF image says กบง. The source describes กฟผ. as importer, approval in 2562, and an upper bound, not actual PTT imports.'},
    'B0295': {
        'question_th':'ตามรายงานประจำปี 2567 CPAXT ปรับปรุงบริการดิจิทัลอย่างไรเพื่อสร้างความพึงพอใจให้ลูกค้า?',
        'reference_answer':'รายงานปี 2567 ระบุการนำโครงสร้างพื้นฐาน IT ใหม่มาสนับสนุนการชำระเงินแบบดิจิทัลสำหรับลูกค้า เพื่อสร้างความพึงพอใจในการใช้บริการ',
        'reason':'Report-context wording avoids assigning an unevidenced event date to the digitization activity.'},
}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('parent-reference','numeric-labels','ai-review','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    parent=load(a.parent_reference);items=copy.deepcopy(parent['items'])
    byid={q['id']:q for q in items};reviews=load(a.ai_review/'blind_labels_locked.json')
    if len(reviews)!=22 or len({r['parsed']['id'] for r in reviews if r.get('parsed')})!=22:
        raise ValueError('Need all 22 blind review decisions')
    docs={d['code']:d for d in parent['documents']}
    decisions=[]
    for old in reviews:
        raw=old['parsed'];qid=raw['id'];q=byid[qid]
        if raw['verdict']=='supported':
            decision='accepted_ai_provisional';reason=raw['reason_th']
        elif qid in VISUAL_ADJUDICATIONS:
            code,page,reason=VISUAL_ADJUDICATIONS[qid]
            if (q['document'],q['source_pdf_page'])!=(code,page):raise ValueError('Visual page mismatch: '+qid)
            image=a.ai_review/'page_images'/f'{code}_{page:04d}.png'
            if sha(image)!=old['image_sha256']:raise ValueError('Image changed: '+qid)
            decision='accepted_after_codex_original_pdf_visual_adjudication'
        else:
            raise ValueError('Unadjudicated disputed reference: '+qid)
        if old['pdf_sha256']!=docs[q['document']]['source_sha256']:
            raise ValueError('Source PDF changed: '+qid)
        decisions.append({'id':qid,'document':q['document'],'physical_pdf_page':q['source_pdf_page'],
            'ai_blind_verdict':raw['verdict'],'final_provisional_verdict':decision,
            'reason':reason,'source_pdf_sha256':old['pdf_sha256'],
            'source_image_sha256':old['image_sha256'],'native_quote_verified':bool(old.get('quote_span')),
            'human_confirmed':False})
    changes=[]
    for qid,edit in EDITS.items():
        before=copy.deepcopy(byid[qid]);q=byid[qid]
        for key in ('question_th','reference_answer'):q[key]=edit[key]
        q['reference_status']='AI-provisional revised after original PDF visual audit; human certified=0'
        q['label_revision_reason']=edit['reason']
        changes.append({'id':qid,'before':before,'after':copy.deepcopy(q),'reason':edit['reason'],
            'physical_pdf_page':q['source_pdf_page'],'source_pdf_sha256':docs[q['document']]['source_sha256']})
    bank=copy.deepcopy(parent);bank['items']=items
    bank['review_version']='2026-10-05-provisional-ai-pdf-v4'
    bank['parent_reference_sha256']=sha(a.parent_reference)
    bank['label_review']='22 sampled calibration references reviewed in original PDF images and native text by AI; 4 Gemini verdicts were overruled after Codex visual inspection; 3 questions clarified from image evidence; no human certification'
    bank['human_certified_labels']=0
    bank['ai_review_policy']={'status':'provisional','human_confirmed':0,
        'model_family_dependency':'Gemini label/judge shares family with app Gemini generator',
        'sampled_calibration_cases':22,'visual_adjudications':sorted(VISUAL_ADJUDICATIONS),
        'parent_scores_unchanged':True}
    if len(items)!=498 or len(byid)!=498:raise ValueError('Wrong diagnostic denominator')
    if [x['id'] for x in items]!=[x['id'] for x in parent['items']]:raise ValueError('Order changed')
    save(a.output/'reference_v4_locked.json',bank)
    save(a.output/'label_changes.json',changes)
    write_csv(a.output/'label_changes.csv',[{'id':c['id'],'question_before':c['before']['question_th'],
        'question_after':c['after']['question_th'],'answer_before':c['before']['reference_answer'],
        'answer_after':c['after']['reference_answer'],'reason':c['reason']} for c in changes])
    save(a.output/'ai_reference_decisions.json',decisions)
    numeric=copy.deepcopy(load(a.numeric_labels))
    for d in numeric:
        if d['id'] not in EDITS:continue
        revised=byid[d['id']]
        d['question']=revised['question_th'];d['reference_answer']=revised['reference_answer']
        if d['id']=='B0286':
            d['company']='รถยนต์ใช้ NGV ทั่วประเทศไทย'
            d['visual_evidence_transcript']='ณ สิ้นเดือนธันวาคม 2567 มีจำนวนรถยนต์ที่ใช้ NGV เป็นเชื้อเพลิงทั่วประเทศรวม 237,815 คัน อ้างอิงข้อมูลกรมการขนส่งทางบก'
        if d['id']=='B0306':
            d['company']='กฟผ.';d['year_be']=2562;d['comparison_operator']='lte'
            d['visual_evidence_transcript']='เมื่อวันที่ 30 สิงหาคม 2562 กบง. ได้เห็นชอบแนวทางทดลองนำเข้า LNG แบบตลาดจรของ กฟผ. ปริมาณไม่เกิน 200,000 ตัน'
            d['reference_issue_resolved']='The original image says กบง.; the earlier AI vision transcript saying กพช. was wrong.'
        d['decision']='supported_ai_pdf_visual_review'
        d['review_status']='provisional_ai_pdf_visual_adjudication'
        d['provisional_score_eligible']=True
        d['official_score_eligible']=False
        d['human_confirmed']=False
        d['reference_issue']='resolved in reference_v4_locked.json'
    if len(numeric)!=101:raise ValueError('Numeric label count changed')
    for d in numeric:
        if d.get('provisional_score_eligible') and not validate_numeric_label(d):
            raise ValueError('Numeric contract invalid: '+d['id'])
    save(a.output/'numeric_labels_v4_locked.json',numeric)
    claims=load(a.ai_review/'claim_calibration.json')
    abstention_repairs=[]
    for record in claims:
        if record['parsed'] is not None:continue
        payload=record['input']
        if payload['CANONICAL_CLAIMS'] or not is_abstention(payload['RESPONSE']):
            raise ValueError('Unhandled claim review failure: '+payload['id'])
        abstention_repairs.append({'id':payload['id'],'claim_count':0,
            'answerable_in_source':True,'required_fact_coverage':'missing',
            'decision':'deterministic_false_refusal_on_answerable_reference',
            'reason':'The recorded answer is an abstention. The blind PDF reference is accepted provisionally. No factual claim precision denominator is created.',
            'raw_ai_failures_preserved':True,'human_confirmed':False})
    save(a.output/'abstention_calibration.json',abstention_repairs)
    summary={'parent_reference_sha256':sha(a.parent_reference),
        'new_reference_sha256':sha(a.output/'reference_v4_locked.json'),
        'numeric_v4_sha256':sha(a.output/'numeric_labels_v4_locked.json'),
        'n_questions':len(items),'n_questions_changed':len(changes),
        'changed_ids':[c['id'] for c in changes],
        'n_ai_calibration_cases':len(decisions),'n_ai_false_verdicts_overruled':len(VISUAL_ADJUDICATIONS),
        'n_abstention_judge_schema_failures_reclassified':len(abstention_repairs),
        'n_numeric_provisional':sum(bool(x.get('provisional_score_eligible')) for x in numeric),
        'n_numeric_human_confirmed':0,'old_scores_unchanged':True,
        'scope':'Diagnostic bank, AI provisional; not an unseen thesis score'}
    save(a.output/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
