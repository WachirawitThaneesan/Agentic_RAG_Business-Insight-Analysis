# รับช่วงต่อ — Thai RAG evaluation

สถานะคุณภาพยัง partial; bounded continuation ส่งผลแล้ว Goal เดิม `usageLimited` ไม่ได้ completed Deadline เดิม 2026-10-05 11:32:17 +07:00 งบสะสมอยู่ใน `handoff_budget.json`: 127 attempts, input 1,289,312 / output 94,084 tokens, failed usage unknown 3, OCR 5/60, ranking 10/12 ไม่เริ่มเวลา/วงเงินใหม่เมื่อเปลี่ยนแชท

## จุดเริ่ม

- Repo `C:\Users\nonga\OneDrive\Desktop\Project_2\Agentic_RAG_Business-Insight-Analysis`, branch `auto1`, HEAD `5060072892320ddf9a1ea4a3b4c317b424c3b33a`
- ใช้ checkout dirty เดิม งานก่อนหน้าและงานรอบนี้ยังไม่ commit ห้าม reset/checkout ทับ
- ผลรอบนี้ `C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\outputs`
- อ่าน `REPORT_th.md`, `DECISIONS.md`, `CODE_LOCK_FINAL.json`, goal เดิมใน `docs/goals/2026-10-05-01-rag-evaluation-continuation.md`
- ไม่มี experiment/server ที่รอบนี้สร้างค้างรัน ฐานข้อมูลทดลองยัง retained ไม่ลบ production DB

## ทำต่อเรียงตาม dependency

1. **เก็บ actual output ที่ประเมินได้** ให้ application emit `answer_claims`, actual `claim_citations` อ้าง source indices ที่ stable และ structured numeric facts พร้อมบริษัท/รายการ/ปี/หน่วย/page/comparator จากการตอบจริง ตรวจความสอดคล้องกับ answer ก่อนยอมรับ ห้ามเติมข้อมูลจาก gold และห้ามใช้ judge-proposed links เป็น app citations กรณี guard เปลี่ยนคำตอบ ต้องไม่เก็บ annotations ของคำตอบที่ถูกปฏิเสธ
2. **แก้ scope ของ context evaluator** ให้วัด source usefulness จาก evidence blocks ที่ส่งจริง แยก returned source list, exact prompt และ page expansion เก็บ provenance ให้ทั้งสามส่วน ไม่ใช้คำว่า context relevancy แทน answer relevancy 90% เดิม
3. **ตรวจเฉลย/context PTT ต่อ** v5 แก้ B0001 แล้ว แต่ source native text/actual OCR ยังสับสน Vision/Mission ต้องแก้การผูกหัวข้อกับข้อความและทำ paired evaluation โดยรักษา rejection ของ uniform/first-two contexts ห้ามสรุปว่า OCR page text ตรงเพียงเพราะมีคำที่ต้องการ
4. **ทำ 20→50 paired ที่ schema ครบ** scorer v2.2 + bank v5 ใช้ baseline/candidate คำถามและเงื่อนไขเดียวกัน รายงาน errors, refusals, unresolved, regressions และ coverage ทั้งหมด ผ่าน ≥95% coverage/citation/numeric gate ก่อนขยาย cloud answers
5. **ขยาย production integration** ปัจจุบันมีเพียง selected 5 physical pages และ cached table repair ยังต้องทดสอบ stratified 30–50 หน้า, scraped PDF route, staging reingest/migration/rollback, chart/merged/multi-page และ native-vs-production paired comparison
6. **เตรียม final unseen** Bangchak/WHAUP/CPN ยังเป็น candidates ตรวจภาษา/issuer family จาก PDF ทั้งรายงาน สร้าง references จาก original images โดยไม่ใช้ extraction ที่ทดสอบเป็น truth ล็อก labels/code/model/scorer ก่อน inference หลังดูผลห้าม tune แล้วเรียกชุดเดิม unseen ขยาย 100–150 และ 500/1,000 เมื่อ gates พร้อม

ถ้ารับช่วงหลัง deadline ให้ทำ offline verification/replay/docs ต่อได้ แต่ไม่เริ่ม cloud experiment ภายใต้งบนี้ ชุด 30-attempt integration ใช้ 27 และ follow-up unit repair cap6 ใช้ครบแล้ว การเปิด experiment ใหม่ต้องระบุ scope/cap และตรวจ original global ledger/deadline ก่อน dispatch

## คำสั่งที่ทำได้ทันทีโดยไม่จ่าย API

ตัวอย่างนี้ใช้ชื่อ output ใหม่และไม่แก้ artifacts เก่า รันจาก repo เดิม:

```powershell
$env:PYTHONUTF8='1'
$ragOut='C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\outputs'
$ragReplay='C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\work\rescore20_v5_next'
if (Test-Path -LiteralPath $ragReplay) { throw 'Choose a new output path; preserve previous results' }
.venv\Scripts\python.exe -m scripts.replay_contract_v2 --audit "$ragOut\audit20_v5_visual_adjudication" --answers "$ragOut\historical_inputs\answer_smoke20\app_gemini_answers.json" --trace "$ragOut\historical_inputs\answer_smoke20_audit\generation_trace.json" --labels "$ragOut\labels_v5\numeric_labels_v5_locked.json" --policy "$ragOut\labels_v5\evaluation_policy.json" --reference "$ragOut\labels_v5\reference_v5_locked.json" --numeric-annotations "$ragOut\numeric_answer_annotations_ai_review.json" --output $ragReplay
```

สำหรับ storage replay ที่ไม่มี model calls:

```powershell
.venv\Scripts\python.exe -m scripts.replay_table_unit_repair --source "$ragOut\ingestion_table1_v6" --truth "$ragOut\table_truth_locked.json" --output 'C:\Users\nonga\Documents\Codex\2026-10-05\rag-evaluation-continuation\work\table_storage_replay_next' --budget "$ragOut\handoff_budget.json"
```

ไม่มี `--run` จึงไม่เรียก cloud และไม่เขียน PostgreSQL ไฟล์ `cell_comparison.json` ควรเป็น before0/21→after21/21 ต้องมี repository dependencies แต่ไม่ต้องโหลด gold เข้า agent

ดู `COMMANDS.md` สำหรับ CLI flags ที่ตรวจแล้วและคำสั่ง regression ทั้งชุด ก่อนเปลี่ยน code ให้อ่าน current hash lock; replay ไม่ใช่ new generation และไม่พิสูจน์คะแนน unseen
