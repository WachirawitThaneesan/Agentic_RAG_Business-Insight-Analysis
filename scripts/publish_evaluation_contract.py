"""Publish Step 1 contracts and immutable audit evidence; never manufacture scores."""
from __future__ import annotations
import argparse,hashlib,json,shutil,zipfile
from pathlib import Path
from backend.eval.contracts import VERSION,TARGETS
from scripts.evaluate_comprehensive import load,save,sha,write_csv


def run(a):
    root=a.root;repo=a.repo;audit=root/'offline_audit_locked';numeric=root/'numeric_labels_final'
    summary=load(audit/'summary.json');numbers=load(numeric/'summary.json')
    if summary['n_saved_answers']!=50 or numbers['n_quantities']!=101:raise ValueError('Incomplete audit')
    docs=repo/'docs/evaluation-contract-2026-10-05-v2'
    raw=repo/'TestFile/evaluation-contract-2026-10-05-v2'
    if docs.exists() or raw.exists():raise ValueError('Publication exists; use new version')
    docs.mkdir(parents=True);raw.mkdir(parents=True)
    for folder,names in ((audit,['summary.json','claim_statuses.csv','actual_citation_audit.json',
        'targets_locked.json','human_reference_review.md','human_judge_calibration.md','human_review_sheet.csv']),
        (numeric,['numeric_labels.csv','numeric_labels_locked.json','human_numeric_review.csv'])):
        for name in names:shutil.copyfile(folder/name,docs/name)
    # Freeze current scoring code, including scripts that construct this package.
    for name in ('backend/eval/contracts.py','backend/eval/tests/test_contracts.py',
        'scripts/audit_evaluation_contract.py','scripts/review_numeric_contracts.py',
        'scripts/finalize_numeric_contracts.py','scripts/import_human_evaluation_review.py',
        'scripts/publish_evaluation_contract.py'):
        target=root/'frozen_code_final'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((repo/name).read_bytes())
    usage=[]
    for name in ('numeric_pdf_review','numeric_pdf_review_v2','numeric_pdf_review_v3','numeric_pdf_review_v4'):
        calls=load(root/name/'model_calls.json') if (root/name/'model_calls.json').exists() else []
        good=[c for c in calls if c['status']=='success']
        tokens={k:sum((c.get('usage') or {}).get(k) or 0 for c in good) for k in
            ('prompt_token_count','candidates_token_count','thoughts_token_count')}
        usage.append({'run':name,'sdk_attempts':len(calls),'sdk_successes':len(good),
            'sdk_errors':len(calls)-len(good),**tokens,
            'cost_usd':None,'cost_reason':'Actual billed charges unavailable; no cost invented'})
    write_csv(docs/'model_usage.csv',usage)
    save(docs/'numeric_review_summary.json',numbers)
    save(docs/'step1_status.json',{'version':VERSION,'code_and_audit_preparation':'completed',
        'human_review':'pending','human_completed':0,'human_cases_prepared':22,
        'reference_conflicts_pending':['B0286','B0306'],
        'n_official_numeric_labels_human_confirmed':0,
        'old_scores_unchanged':True,'new_answer_generation_runs':0,
        'application_retrieval_changed_in_this_step':False,
        'measured_target_improvement_claimed':False})
    readme='''# ข้อ 1 — เกณฑ์ตรวจและความน่าเชื่อถือของเฉลย

## เป้าหมายสำหรับ thesis ที่เสนอ

ตัวเลขเหล่านี้เป็นเป้าหมายเชิงวิศวกรรมของโครงการ ไม่ใช่เกณฑ์ผ่าน thesis สากล
ต้องเห็นผลบนรายงานไทยใหม่ที่กันไว้ระดับทั้งรายงาน และให้ผู้ตรวจจริงตรวจเฉลย/ตัวอย่างคำตัดสิน
คะแนนบนชุดที่ปรับระบบแล้วเป็น diagnostic เท่านั้น คะแนนเฉลี่ยไม่ใช่เปอร์เซ็นต์คำถามถูกทั้งหมด

| Metric | ผลเดิมที่วัด | เป้าหมาย |
|---|---:|---:|
| Page Hit@5 | 74.9% (373/498) | ≥90% |
| Factual precision | 69.5% (42 ข้อที่มี claims) | ≥95% |
| Factual recall | 50.7% (50 ข้อ) | ≥85% |
| Context recall | 63.6% (50 ข้อ) | ≥90% |
| Response relevancy rubric | 65.0% (50 ข้อ) | ≥90% |
| Faithfulness แบบตรวจคำอ้าง | 65.0% (42 ข้อที่มี claims) | ≥95% |
| Citation precision ของลิงก์ที่อ้างจริง | ยังวัดไม่ได้จากข้อมูลเดิม | ≥95% |
| Citation recall ระดับข้อกล่าวอ้าง | ต้องเก็บ mapping ที่อ้างจริงก่อน | ≥90% |
| Strict numeric accuracy | ยังไม่มีตัวหารที่พร้อมใช้ในตัวอย่าง 50 ข้อนี้ | ≥95% |
| Complete answer success | 20% (10/50), เกณฑ์เดิม | ≥75% |

Coverage ของการตรวจและ mapping ที่ใช้วัดต้อง ≥95% และเปิดเผยส่วนที่ตรวจไม่ได้ ห้ามตัดคำถามยาก/คำตอบว่างออกเพื่อให้คะแนนสูงขึ้น
รายงาน N/A พร้อมเหตุผล ใช้ตัวหารเดิมสำหรับ lower bound และเผยจำนวน wrong / insufficient / unverifiable แยก
Precision@5 ไม่ควรกำหนดเป้าหมาย 95% ถ้ามีเฉลยเพียงหน้ารองรับเดียวต่อคำถาม เพราะแม้พบทุกข้อ ค่านั้นจะได้ประมาณ 20%
เกณฑ์ joint success เป็นเป้าหมายแยก ไม่ได้คำนวณจากการคูณค่าเฉลี่ยแต่ละ metric

## เปลี่ยนอะไรในข้อ 1

1. แยก supported_quote_verified / contradicted_ai_needs_review / insufficient_evidence / quote_unverifiable
   AI ตัดสินว่าขัดแย้งยังไม่ใช่คำตัดสินจากมนุษย์ และตรวจคำอ้างไม่พบไม่ได้พิสูจน์ว่าคำตอบผิด
2. ใช้บริบทจริงที่โมเดลได้รับตรวจ faithfulness และใช้ PDF/เฉลยต้นฉบับตรวจ factuality แยกกัน
3. เฉลยตัวเลขมี entity/company, measure/row, value/sign, explicit unit/scale, event year กับ report scope, physical PDF page, PDF hash และหลักฐาน
4. เพิ่ม comparison_operator สำหรับค่าตรง เพดาน ขั้นต่ำ ค่าประมาณ และช่วงค่า ไม่ตี 'ไม่เกิน 200000' ว่าเป็นปริมาณจริง 200000
5. ปัดเศษ/แปลงหน่วยได้ตาม policy ที่ล็อกต่อ label เท่านั้น ค่า tolerance เริ่มต้นเป็น 0 ไม่เดาอัตราแลกเปลี่ยน
6. Citation precision หารด้วยลิงก์ที่แอปอ้างจริง; citation recall วัด claims ที่มี citation รองรับ
   Sources ที่ค้นมาและลิงก์ที่ AI ผู้ตรวจเสนอให้ใช้เป็นอีก observation ห้ามเอามานับว่าแอปอ้างจริง
   index ของ claims ต้องผูกกับข้อความที่บันทึกจริง ห้ามสมมติว่าลำดับจากแอปกับ AI judge ตรงกัน
7. เตรียม human review 22 กรณีจากผ่าน/ขัดแย้ง/กำกวม/หลักฐานไม่พอ พร้อมภาพ PDF และ context จริง และใบตรวจตัวเลข 101 ค่า

## ตรวจข้อมูลเก่าแล้วพบอะไร

คำตอบเดิม 50 ข้อมีข้อกล่าวอ้าง 105 รายการ (ตัวหารระดับ claim ต่างจากค่าเฉลี่ยระดับคำถาม)

| Dimension | รองรับและตรวจคำอ้างได้ | AI ตัดสินว่าขัดแย้ง รอคนตรวจ | หลักฐานไม่พอ | ตรวจคำอ้างไม่ได้ |
|---|---:|---:|---:|---:|
| Faithfulness | 70 | 0 | 1 | 34 |
| Factuality | 63 | 14 | 7 | 21 |

ตรวจคำอ้างไม่พบรวม 55 dimension-observations: 43 หาไม่พบในข้อความที่ตรวจ, 10 ไม่มี quote, 2 quote อยู่ในเฉลยแต่ไม่มีใน actual context
การมี quote เป็นสมาชิกของ source ไม่ได้พิสูจน์ entailment โดยลำพัง ส่วนความสัมพันธ์ยังเป็นการตัดสิน AI/คน
ข้อมูลเดิม 50/50 ข้อไม่มี mapping claim→citation ที่แอปแสดงจริง จึงยังไม่ผลิตคะแนน citation precision แบบใหม่
คะแนน 9.8% เดิมเป็น returned-source support utilization ที่หารด้วย sources ทั้งหมด ไม่ใช่คะแนนความถูกต้องของ citation ที่ผู้ใช้เห็น

## เฉลยตัวเลขและประเด็นที่ต้องแก้ก่อนรับรอง

ตรวจ 101 ค่า จาก 94 คำถาม บนภาพ PDF 51 หน้า โดยไม่ส่งคำตอบระบบ/อันดับค้นหาให้ AI ผู้ตรวจ
101 เป็นจำนวน candidate quantities ไม่ใช่จำนวนคำตอบที่ระบบตอบถูก และยังไม่ครอบคลุมทุกชนิดตัวเลข เช่น วันที่/หน่วยที่ parser ไม่รู้จัก
หลังตรวจโดย AI และตรวจภาพเพิ่ม 7 ค่า: 99 ค่าเป็น provisional supported, อีก 2 ค่ายังมีประเด็นกับเฉลย/ขอบเขตคำถาม

- B0286: 237815 คันเป็นรถ NGV ทั่วประเทศ ไม่ใช่รถที่ ปตท. เป็นเจ้าของ ต้องยืนยันขอบเขตคำถามให้ชัด
- B0306: เพดาน LNG ไม่เกิน 200000 ตันเป็นการทดลองนำเข้าของ กฟผ. ในปี 2562; ภาพต้นฉบับระบุ กพช. แต่ reference เดิมระบุ กบง.
- ทั้ง 101 ค่ายังไม่มีมนุษย์รับรอง; official_score_eligible=false ห้ามเรียก 99/101 ว่า answer accuracy
- อุปสรรค API 429 และรอบตรวจที่ล้มเหลวเก็บไว้ทั้งหมด รอบสุดท้ายลองใหม่เฉพาะหน้าที่ล้มเหลว
- Native quote ที่ตรวจได้กับ image transcript เป็นสองวิธีแสดงหลักฐาน ถ้าข้อความ PDF เสียรูป ใช้ภาพที่มี hash พร้อม transcript โดยยังต้องคนตรวจ
- original bank, answers และคะแนนเดิมไม่ได้ถูกเขียนทับ; สองกรณีที่พบใหม่ยังไม่ได้เปลี่ยน denominator ของคะแนนเดิม

## วิธีตรวจโดยคน (ยังค้างอยู่)

1. เปิด human_reference_review.md ตรวจเฉลยจากภาพ/PDF ก่อน โดยยังไม่ดูคำตอบระบบ
2. เปิด human_judge_calibration.md ตรวจคำตอบกับ context ที่โมเดลได้รับจริงและต้นฉบับ
3. กรอก human_review_sheet.csv: reviewer_name, วันที่ YYYY-MM-DD, reference_verdict, faithfulness_verdict, factual_verdict, evidence_quote, reason แล้วตั้ง human_completed=true
   verdicts ใช้ supported / wrong / insufficient_evidence / unverifiable; reference ใช้ supported / corrected / unanswerable / ambiguous
4. ถ้าเฉลยผิด กรอก corrected_reference; บันทึกหน้าทางเลือกและเกณฑ์ปัดเศษด้วย ใบตัวเลขแยกอยู่ใน human_numeric_review.csv
5. ใช้ scripts.import_human_evaluation_review นำเข้าเป็นผลรุ่นใหม่ ใบที่ยังว่างให้จำนวน human_completed=0

ชุดตรวจ 22 กรณีเลือกตามประเภทปัญหา ไม่ใช่ตัวอย่างสุ่มที่ใช้ประมาณความแม่นยำทั้งประชากร
ไม่สร้างตัวเลข agreement จากหน่วยที่ต่างกัน: ใบคนตรวจเป็นระดับคำตอบ ส่วน AI status เป็นระดับ claim

## ทำซ้ำและขอบเขต

```powershell
.venv\\Scripts\\python.exe -m pytest backend/eval/tests -q
.venv\\Scripts\\python.exe -m scripts.audit_evaluation_contract --parent <saved-repair-root> --output <new-audit-directory>
.venv\\Scripts\\python.exe -m scripts.import_human_evaluation_review --sheet <completed-human-sheet.csv> --audit <audit-directory> --output <new-human-review-directory>
```

โค้ดเกณฑ์: backend/eval/contracts.py เป็นรุ่นใหม่แยกจาก comprehensive-rag-v1.5
contract ตรวจ bound numeric facts ที่จับรายการ/บริษัท/ปีแล้ว ไม่ค้นตัวเลขเดียวที่ปรากฏที่ไหนก็ได้ในคำตอบ
ถ้า annotations มาจาก AI ต้องรายงาน provenance ไม่อ้างว่าเป็นการตรวจ deterministic จากคำตอบโดยตรง
ภาพและ raw inputs/outputs, model calls, resources, code snapshots และ hashes อยู่ใน complete_step1_artifacts.zip
metrics แบบ claim เป็น custom implementation ตามหลัก RAG ไม่ใช่คะแนนที่รันจากแพ็กเกจ Ragas/ALCE โดยตรง
เกณฑ์ความผิดพลาดและ citation บางส่วนเป็นนิยามใหม่ จึงเปรียบเทียบกับคะแนนเก่าเป็นการปรับระบบไม่ได้จนกว่าจะรัน baseline/new ด้วยเกณฑ์เดียวกัน
ข้อ 2–6 ยังไม่ได้ทำในรอบนี้ การค้นหาและการสร้างคำตอบของแอปไม่ได้เปลี่ยน

อ้างอิงหลักการ: [Ragas factual correctness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/factual_correctness/), [Ragas faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/), [ALCE citation evaluation](https://arxiv.org/abs/2305.14627)
เป้าหมายเปอร์เซ็นต์เป็นข้อเสนอของโครงการ ไม่ได้คัดมาจากแหล่งเหล่านี้ว่าเป็นเกณฑ์ผ่านมหาวิทยาลัย
'''
    (docs/'README_th.md').write_text(readme,encoding='utf-8')
    shutil.copyfile(root/'software_tests_complete.xml',raw/'software_tests.xml')
    save(raw/'artifact_scope.json',{'version':VERSION,'old_scores_unchanged':True,
        'new_application_runs':0,'new_numeric_pdf_review':numbers,
        'human_completed':0,'numeric_official_labels':0})
    # Deduplicate identical page images in the archive, with an explicit
    # alias ledger. All JSON/calls/failed runs and code remain available.
    allowed={'.json','.csv','.md','.png','.py','.txt','.xml'}
    files=sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in allowed and '__pycache__' not in p.parts)
    ledger={};aliases={};images={}
    archive=raw/'complete_step1_artifacts.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:
            name=p.relative_to(root).as_posix();digest=sha(p);ledger[name]=digest
            if p.suffix.lower()=='.png' and digest in images:aliases[name]=images[digest];continue
            if p.suffix.lower()=='.png':images[digest]=name
            z.write(p,name)
        z.writestr('SHA256_MANIFEST.json',json.dumps(ledger,ensure_ascii=False,indent=2))
        z.writestr('IDENTICAL_IMAGE_ALIASES.json',json.dumps(aliases,indent=2))
    with zipfile.ZipFile(archive) as z:
        if z.testzip():raise ValueError('Archive CRC failure')
        for name,digest in ledger.items():
            if hashlib.sha256(z.read(aliases.get(name,name))).hexdigest()!=digest:raise ValueError('Archive hash mismatch')
    save(raw/'artifact_manifest.json',{'archive_sha256':sha(archive),'file_count':len(files),
        'deduplicated_image_count':len(aliases),'archive_mib':archive.stat().st_size/2**20,
        'all_hashes_verified':True,'crc_verified':True,
        'restore_images':'After unzip, copy each IDENTICAL_IMAGE_ALIASES key from its recorded value; both contents are identical',
        'excluded':['full PDFs','credentials','model weights','embeddings']})
    save(docs/'report_manifest.json',{p.name:sha(p) for p in docs.iterdir() if p.is_file()})
    print(json.dumps(load(raw/'artifact_manifest.json'),ensure_ascii=False))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--repo',type=Path,required=True);run(p.parse_args())


if __name__=='__main__':main()
