"""Freeze provisional numeric contracts, with logged Codex PDF-image checks."""
from __future__ import annotations
import argparse,json,re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from backend.eval.contracts import validate_numeric_label
from scripts.evaluate_comprehensive import load,save,sha,write_csv

VISUAL_CHECKS={
 'B0263':{'company':'โรงไฟฟ้าทีดับบลิวเอฟ','visual_evidence_transcript':'ในรอบปี 2567 โรงไฟฟ้าทีดับบลิวเอฟ มีค่าเฉลี่ยความพร้อมในการเดินเครื่องตลอดทั้งปีคิดเป็นร้อยละ 99.31'},
 'B0285':{'visual_evidence_transcript':'ในปี 2567 ปตท. ได้ให้การช่วยเหลือผ่านโครงการบัตรสิทธิประโยชน์ กลุ่มรถโดยสารสาธารณะ รวม 506 ล้านบาท'},
 'B0286':{'company':'รถยนต์ใช้ NGV ทั่วประเทศไทย','visual_evidence_transcript':'ณ สิ้นเดือนธันวาคม 2567 มีจำนวนรถยนต์ที่ใช้ NGV เป็นเชื้อเพลิงทั่วประเทศรวม 237,815 คัน (อ้างอิงข้อมูลจากกรมการขนส่งทางบก)',
     'reference_issue':'Question says PTT has vehicles; PDF reports national fleet, not PTT ownership'},
 'B0288':{'visual_evidence_transcript':'การช่วยเหลือราคา NGV สำหรับกลุ่มรถทั่วไป รวม 216 ล้านบาท สะสมตั้งแต่เดือนมกราคมถึงธันวาคม 2567'},
 'B0306':{'company':'กฟผ.','company_aliases':['การไฟฟ้าฝ่ายผลิตแห่งประเทศไทย'],
     'measure':'เพดานปริมาณทดลองนำเข้า LNG แบบตลาดจรของ กฟผ.',
     'visual_evidence_transcript':'เมื่อวันที่ 30 สิงหาคม 2562 กพช. ได้เห็นชอบแนวทางการทดลองนำเข้า LNG แบบตลาดจร (Spot) ของ กฟผ. ในปริมาณไม่เกิน 200,000 ตัน',
     'reference_issue':'Frozen reference names กบง.; image says กพช. Subject is กฟผ., and 200000 is an upper bound, not actual PTT imports'},
 'B0347':{'company':'ระบบการไฟฟ้าไทย','visual_evidence_transcript':'ความต้องการพลังไฟฟ้าสูงสุดของระบบการไฟฟ้าในปี 2567 อยู่ที่ 36,792 เมกะวัตต์'},
 'B0004':{'company':'PTTEP','measure':'สัดส่วนการผลิตก๊าซธรรมชาติในประเทศของ ปตท.สผ. ต่อการผลิตก๊าซธรรมชาติทั้งหมดของประเทศ',
     'visual_evidence_transcript':'ปตท.สผ. สามารถผลิตก๊าซธรรมชาติในประเทศได้ในปริมาณร้อยละ 82 ของการผลิตก๊าซธรรมชาติทั้งหมดของประเทศ'},
}


def qualifier(text,value):
    number=r'\d[\d,]*(?:\.\d+)?'
    target=Decimal(str(value).replace(',',''))
    for m in re.finditer('('+number+r')\s*[-–]\s*('+number+')',text):
        lo=Decimal(m[1].replace(',',''));hi=Decimal(m[2].replace(',',''))
        if lo<=hi and target in (lo,hi):return {'comparison_operator':'range','range_min':str(lo),'range_max':str(hi)}
    matches=[m for m in re.finditer(number,text) if Decimal(m[0].replace(',',''))==abs(target)]
    if not matches:return {'comparison_operator':'eq','qualifier_needs_review':True}
    prefix=text[max(0,matches[0].start()-50):matches[0].start()]
    operators=[(r'ไม่น้อยกว่า|ไม่ต่ำกว่า|อย่างน้อย','gte'),(r'ไม่เกิน|ไม่มากกว่า','lte'),
        (r'มากกว่า|เกิน','gt'),(r'น้อยกว่า|ต่ำกว่า','lt'),(r'ประมาณ|ราว','approx')]
    for pattern,operator in operators:
        if re.search('(?:'+pattern+r')(?:ร้อยละ|เปอร์เซ็นต์|\s)*$',prefix):return {'comparison_operator':operator}
    return {'comparison_operator':'eq'}


def run(a):
    a.output.mkdir(parents=True,exist_ok=False)
    labels=load(a.review/'numeric_labels_locked.json');changes=[]
    for d in labels:
        original=dict(d);d.update(qualifier(d['reference_answer'],d.get('value',0)))
        d['comparison_operator_provenance']='Frozen reference wording; human source confirmation pending'
        if d['id'] in VISUAL_CHECKS:
            d.update(VISUAL_CHECKS[d['id']]);d['decision']='supported'
            d['visual_transcript_present']=True;d['source_evidence_kind']='pdf_image_transcript'
            d['review_status']='provisional_ai_pdf_image_and_codex_visual_check'
        if d.get('reference_issue'):d['decision']='reference_conflict_needs_review'
        if d['decision']=='supported':validate_numeric_label(d)
        d['official_score_eligible']=False
        d['provisional_score_eligible']=d['decision']=='supported'
        if d!=original:changes.append({'id':d['id'],'quantity_index':d['quantity_index'],
            'before':original,'after':dict(d),'human_confirmed':False})
    save(a.output/'numeric_labels_locked.json',labels);write_csv(a.output/'numeric_labels.csv',labels)
    save(a.output/'label_changes.json',changes)
    write_csv(a.output/'human_numeric_review.csv',[{**{k:d.get(k) for k in
        ('id','quantity_index','company','measure','value','unit','year_be','year_kind',
         'comparison_operator','range_min','range_max','document','source_pdf_page','reference_issue')},
        'reviewer_name':'','review_date':'','human_verdict':'','evidence_quote':'','reason':'',
        'human_completed':False} for d in labels])
    summary={'n_quantities':len(labels),'n_questions':len({d['id'] for d in labels}),
        'decisions':dict(Counter(d['decision'] for d in labels)),
        'comparison_operators':dict(Counter(d['comparison_operator'] for d in labels)),
        'n_codex_visual_checked_quantities':sum(d['id'] in VISUAL_CHECKS for d in labels),
        'n_provisional_score_eligible':sum(d['provisional_score_eligible'] for d in labels),
        'n_human_confirmed':0,'n_official_score_eligible':0,'old_scores_unchanged':True}
    save(a.output/'summary.json',summary)
    save(a.output/'method_lock.json',{'source_sha256':sha(a.review/'numeric_labels_locked.json'),
        'code_sha256':sha(__file__),'contract_sha256':sha(Path('backend/eval/contracts.py')),
        'scope':'Provisional AI review, 7 logged root visual checks; no human certification'})
    print(json.dumps(summary,ensure_ascii=False))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--review',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);run(p.parse_args())


if __name__=='__main__':main()
