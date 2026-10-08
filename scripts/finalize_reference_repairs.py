"""Freeze disclosed AI-only corrections and reviewed evidence alternatives.

Supplemental decisions are based on inspected original PDF pages, not ranks.
Original labels/raw image reviews are never overwritten.
"""
import argparse
import re
from collections import Counter
from pathlib import Path
from scripts.evaluate_comprehensive import load,save,sha,write_csv


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('reference','review','image-review','sources','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    original=load(a.reference);flags={r['id']:r for r in load(a.review)}
    visual={r['id']:r for r in load(a.image_review/'decisions.json')}
    sources={d['code']:d for d in load(a.sources)['documents']}
    overrides={
        'B0033':{'question_th':'ตามรายงานปี 2567 คณะกรรมการ ปตท. อนุมัติงบลงทุน 5 ปี (2567-2571) รวมเป็นเงินเท่าใด?',
            'reference_answer':'89,203 ล้านบาท โดยมีมติอนุมัติวันที่ 21 ธันวาคม 2566',
            'reason':'Inspected PTT physical PDF p25: approval 21 December 2566, budget covers 2567-2571'},
        'B0035':{'reference_answer':'บริษัท โกลบอล รีนิวเอเบิล ซินเนอร์ยี จำกัด (GRSC) โดยดำเนินการจำหน่ายหุ้นแล้วเสร็จวันที่ 16 ตุลาคม 2567',
            'reason':'Inspected PTT physical PDF p25: approval 21 December 2566 differs from sale completion 16 October 2567'},
        'B0060':{'question_th':'ตามรายงานปี 2567 กระทรวงการคลังคาดการณ์ว่าเศรษฐกิจไทยในปี 2568 จะขยายตัวในอัตราร้อยละเท่าใด',
            'reason':'Forecast target year 2568 is explicit in CPAXT PDF p35; distinguish publication year'},
        'B0164':{'question_th':'ตามรายงานปี 2567 ของ CPAXT เศรษฐกิจโลกในปี 2568 มีแนวโน้มขยายตัวอย่างไร?',
            'reference_answer':'เศรษฐกิจโลกในปี 2568 มีแนวโน้มขยายตัวอย่างค่อยเป็นค่อยไป',
            'reason':'Inspected CPAXT p34/p130, report states forecast; do not assert CPAXT authored it'},
        'B0239':{'decision':'revise','reference_answer':'แอมโมเนีย (Ammonia) และไตรโซเดียม ฟอสเฟต (Sodium Triphosphate)',
            'reason':'AI visual review timed out; primary agent inspected EGCO physical PDF p38 boiler-water chemicals paragraph'},
        'B0240':{'decision':'revise','reference_answer':'บริษัท เคซอน แมนเนจเม้นท์ เซอร์วิส อิงค์ (คิวเอ็มเอส)',
            'reason':'AI visual review timed out; primary agent inspected EGCO physical PDF p38 business group item 2'},
        'B0461':{'reference_answer':'กำหนดทิศทาง นโยบาย และกลยุทธ์ด้านดิจิทัลของ ปตท.สผ.',
            'reason':'Keep requested minimal fact; do not make unrequested extra duties mandatory'},
        'B0080':{'question_th':'ตามรายงานปี 2567 โรงไฟฟ้าลินเดน หน่วยที่ 6 ของ EGCO ใช้เชื้อเพลิงผสมชนิดใดในเชิงปริมาณร้อยละ 40?',
            'reason':'Inspected EGCO PDF p90: hydrogen is in heading above 40 percent; decoded quote omitted heading'},
        'B0185':{'question_th':'ตามรายงานปี 2567 CPAXT กำหนดให้บุคลากรประเภทใดบ้างที่ต้องแจ้งข้อมูลความขัดแย้งทางผลประโยชน์?',
            'reference_answer':'พนักงานประจำของบริษัทฯ และบริษัทย่อยทุกคน และพนักงานชั่วคราวที่มีหน้าที่เกี่ยวข้องกับคู่ค้า ผู้จำหน่ายสินค้า ลูกค้า ผู้รับเหมา และผู้ให้บริการ',
            'reason':'Inspected CPAXT PDF pp161-162: sentence continues across physical pages; original answer truncated'},
        'B0155':{'reason':'Inspected EGCO PDF p174 row 1 has triangle and XX; footnote defines board chair and investment chair'},
        'B0469':{'decision':'quarantine','reason':'Inspected PTT physical PDF p78: reference quote is sidebar contents, not evidence of how risk management works'},
        'B0470':{'decision':'quarantine','reason':'Inspected PTT physical PDF p78: reference quote is sidebar contents, not evidence of how sustainability works'},
    }
    alternates={'B0002':[20,100],'B0058':[352],'B0095':[74],'B0164':[34],'B0193':[219]}
    alternate_decisions=[{'id':qid,'accepted_alternative_pages':pages,'review_level':'Primary-agent AI PDF-context review; human pending',
        'reason':'Same entity, requested fact and temporal context in original page and alternate; not mere duplicate quote'}
        for qid,pages in alternates.items()]
    alternate_decisions.extend([{'id':'B0148','rejected_alternative_pages':[153,155,156],
        'reason':'Same course text on different directors biographies; not evidence for Phumchai on p154'},
        *[{'id':qid,'rejected_alternative_pages':[80],'reason':'Original label unsupported navigation text; quarantined'}
          for qid in ('B0469','B0470')]])
    active=[];changes=[];quarantine=[]
    for old in original['items']:
        q=dict(old);r=visual.get(q['id']);notes=[];decision=r.get('decision') if r else 'not_flagged'
        if r and decision=='revise':
            q['question_th']=r['question_th'];q['reference_answer']=r['reference_answer']
            if r.get('native_quote_exact'):q['reference_quote']=r['native_quote']
        if r and r.get('visual_evidence_transcript'):q['visual_evidence_transcript']=r['visual_evidence_transcript']
        # Conservative scope repair: a report can document policies or past
        # events without establishing that they started in its publication year.
        if r and not flags[q['id']].get('time_consistent',True):
            for key in ('question_th','reference_answer'):
                q[key]=re.sub(r'^ในปี\s*2567\s*','ตามรายงานปี 2567 ',q[key])
            notes.append('Replace ambiguous event-year prefix with explicit report scope')
        override=overrides.get(q['id'])
        if override:
            for key in ('question_th','reference_answer'):
                if key in override:q[key]=override[key]
            decision=override.get('decision','revise');notes.append(override['reason'])
        if q['id'] in ('B0043','B0044','B0045'):
            q['question_th']=q['question_th'].replace('ในปี 2567 CPAXT มีสัดส่วนรายได้','ตามรายงานปี 2567 ของ CPAXT สัดส่วนรายได้')
            notes.append('Specify subsidiary measure as reported by CPAXT, not consolidated parent revenue')
        if q['id']=='B0185':
            q['required_evidence']=[{'document':'CPAXT','source_pdf_page':pg} for pg in (161,162)]
        if q['id'] in ('B0032','B0033','B0034','B0035','B0038','B0043','B0044','B0045','B0080','B0124','B0155','B0185'):
            import pymupdf
            source=sources[q['document']]
            if sha(source['path'])!=source['source_sha256']:raise ValueError('PDF hash mismatch')
            with pymupdf.open(source['path']) as pdf:
                q['reference_quote']=' '.join(pdf[q['source_pdf_page']-1].get_text().split())
                if q['id']=='B0185':q['reference_evidence']={'continuation_pdf_page':162,
                    'native_quote':' '.join(pdf[161].get_text().split())[:850]}
            notes.append('Retain full original page context so headings, date and table-code footnotes can be checked')
        if decision=='quarantine':
            quarantine.append({'original':old,'image_review':r,'supplemental_reason':notes});continue
        if q['id'] in alternates:
            q['evidence_options']=[[{'document':q['document'],'source_pdf_page':pg}]
                for pg in [q['source_pdf_page'],*alternates[q['id']]]]
            notes.append('Alternative singleton evidence pages reviewed; original target retained')
        q['reference_status']='Provisional AI PDF-reviewed diagnostic label; no human certification'
        active.append(q)
        if r or override or q['id'] in alternates:
            changed=any(q.get(k)!=old.get(k) for k in ('question_th','reference_answer','reference_quote','evidence_options','required_evidence'))
            changes.append({'id':q['id'],'decision':'revised' if changed else 'kept',
                'original':old,'revised':q,'image_review':r,'supplemental_notes':notes})
    bank={**original,'items':active,'parent_reference_sha256':sha(a.reference),
        'review_version':'2026-10-05-provisional-v2','human_certified_labels':0,
        'quarantined_ids':[q['original']['id'] for q in quarantine]}
    save(a.output/'reference_locked.json',bank);save(a.output/'changes.json',changes)
    save(a.output/'quarantined.json',quarantine);save(a.output/'alternate_page_decisions.json',alternate_decisions)
    save(a.output/'summary.json',{'original_n':500,'flagged_reviewed':len(visual),'active_n':len(active),
        'quarantined_n':len(quarantine),'change_decisions':dict(Counter(c['decision'] for c in changes)),
        'changed_question_n':sum(c['original']['question_th']!=c['revised']['question_th'] for c in changes),
        'changed_answer_n':sum(c['original']['reference_answer']!=c['revised']['reference_answer'] for c in changes),
        'human_certified_labels':0,'reference_sha256':sha(a.output/'reference_locked.json'),
        'scope':'AI-only provisional label repair. Question edits require new inference; not a rescore of old answers.'})
    write_csv(a.output/'label_changes.csv',[{'id':c['id'],'decision':c['decision'],
        'original_question':c['original']['question_th'],'revised_question':c['revised']['question_th'],
        'original_answer':c['original']['reference_answer'],'revised_answer':c['revised']['reference_answer'],
        'document':c['revised']['document'],'physical_pdf_page':c['revised']['source_pdf_page'],
        'notes':' | '.join(c['supplemental_notes'])} for c in changes])


if __name__=='__main__':main()
