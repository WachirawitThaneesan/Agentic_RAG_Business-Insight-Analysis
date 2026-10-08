# ผลการรับช่วงแผนประเมิน Thai Business RAG — 7 ตุลาคม 2026

**สถานะ:** รันชุด final transfer และส่งหลักฐานครบตามขอบเขตที่วัด; quality targets ยังไม่ครบ

การทำ evaluation จบไม่ได้แปลว่าระบบตอบถูก 100% คะแนนทั้งหมดเป็น AI provisional, human_confirmed=false และไม่ใช่คะแนน thesis ที่มีผู้ตรวจอิสระรับรอง

## งานที่ทำจริง

- แก้ app capture: หน่วยประกอบ/อันดับเปอร์เซ็นต์, comparator ในคำว่า งบประมาณ, equipment IDs, categorical ratings และ feedback ที่ระบุ JSON ที่ผิดจริง
- แก้ scorer ให้ใช้เฉพาะ actual claim→source links ที่แอปส่ง เก็บ returned sources แยก; ไม่ใช้ judge-proposed links เป็น citation ของแอป
- แก้ numeric grading จากฟิลด์ที่ bind กับคำตอบจริง โดยคง sign/value/unit/scale/year/page/comparator และแยก literal-name grading จาก AI semantic identity supplement
- รุ่น v9–v11 ตรวจภาพ PDF แก้ comparator/unit และ alternate evidence/aliases โดยรักษา raw labels/scores เก่า การแก้เกิดหลังเห็นผล development จึงไม่อ้างว่าเป็น blind independent review
- 50 matched questions × 2 rankings รันจริง; ชุด v1 ที่มี capture errors และ failed audit/probes ยังเก็บไว้ ชุด v2 ใช้ app protocol เดียวกันทั้ง 50 คู่
- ตรวจ live upload กับ scraped-file preparation บน 8 หน้าใน DB ทดลองใหม่ ผล hash/page checkpoints ตรงกันและใช้ cloud calls=0 การตรวจนี้ไม่ใช่ fresh OCR accuracy
- ใช้หลักฐาน real Typhoon/Gemini ingestion 32 หน้าจากรอบเดิมร่วมกับ staging/restart/idempotency/rollback; ไม่รวมเป็น fresh unseen OCR
- Freeze code/scorer/inputs ก่อน final inference; 3 รายงานไทยใหม่มี 133 คำถาม (118 answerable, 15 controls), 114 numeric tuples และ 1,980 cached corpus embeddings

## ผล development 50 คู่

| Ranking | Capture | Numeric coverage | Literal numeric accuracy (measured subset) | Factual verified support macro | Faithfulness verified support macro | Actual link precision | Complete lower bound |
|---|---:|---:|---:|---:|---:|---:|---:|
| hybrid_current | 98.00% | 95.00% | 42.11% (8/19) | 96.52% | 99.57% | N/A | 62.00% |
| lexical_first | 98.00% | 95.00% | 31.58% (6/19) | 100.00% | 100.00% | N/A | 64.00% |

Complete lower bound เป็นขอบเขตล่างเมื่อยังมี unresolved; ไม่ใช้แทน measured complete-answer accuracy และ quote-unverifiable ไม่ได้พิสูจน์ว่า claim นั้นผิดจริง

## Final transfer บนรายงานใหม่

| System | Generated | Capture | Required numeric coverage | Literal numeric accuracy (measured subset) | Factual verified support macro | Faithfulness verified support macro | Actual link precision | Answerable complete lower bound |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bm25_thai | 133/133 | 91.73% | 90.35% | 17.48% (18/103) | 87.38% | 98.60% | N/A | 28.81% |
| dense | 133/133 | 94.74% | 92.98% | 11.32% (12/106) | 85.33% | 94.57% | N/A | 16.10% |
| simple_rag | 133/133 | 94.74% | 92.98% | 13.21% (14/106) | 81.18% | 92.47% | N/A | 18.64% |
| lexical_first | 133/133 | 93.23% | 92.98% | 20.75% (22/106) | 88.39% | 98.66% | N/A | 30.51% |

Controls แยกจาก answerable complete-success; ดู numerator/denominator/unknown ของแต่ละระบบใน METRICS.json

## Numeric failure decomposition

ใช้ labels/scorer ที่ล็อกไว้เหมือนเดิม เป็น post-test diagnosis ไม่มี cloud calls; จำนวน failed checks ซ้อนกันได้ ไม่ใช้ component score แทน strict numeric accuracy

| System | Bound numeric tuples with checks | Value+unit checks passed | Literal identity only failures | Physical page failures |
|---|---:|---:|---:|---:|
| bm25_thai | 73/114 | 54/73 | 16 | 32 |
| dense | 60/114 | 42/60 | 15 | 25 |
| simple_rag | 65/114 | 42/65 | 14 | 28 |
| lexical_first | 78/114 | 57/78 | 20 | 28 |

Literal identity only failures ไม่ได้พิสูจน์ว่าเป็น synonym ที่ถูกต้อง; ต้องตรวจแยกต่อไป ไม่มีการเปลี่ยน aliases/scorer จาก final outcomes

## Initial retrieval บนรายงานใหม่

| Ranking | Hit@1 | Hit@3 | Hit@5 | Hit@10 |
|---|---:|---:|---:|---:|
| bm25_thai | 49.15% (58/118) | 72.88% (86/118) | 80.51% (95/118) | 87.29% (103/118) |
| dense | 21.19% (25/118) | 38.14% (45/118) | 44.07% (52/118) | 55.93% (66/118) |
| simple_rag | 21.19% (25/118) | 38.14% (45/118) | 44.07% (52/118) | 55.93% (66/118) |
| lexical_first | 55.08% (65/118) | 77.97% (92/118) | 82.20% (97/118) | 91.53% (108/118) |

118 answerable questions; 15 controls excluded. ใช้ frozen native corpus/query vectors ไม่มี cloud calls; incomplete page qrels จำกัดการตีความ precision/nDCG และนี่คือ initial query ไม่ใช่ทุก agent follow-up retrieval

## ขอบเขตและข้อจำกัด

- Corpus final เป็น full native report text ไม่ใช่ full-report Typhoon/Gemini OCR; ทุก arm ใช้ corpus/embeddings/questions/models ชุดเดียวกัน ระบบ keyword/dense full agent, simple dense RAG หนึ่ง retrieval และ improved scoped system เป็น system comparison ไม่ใช่ fusion-only ablation
- ไม่มี performance-driven tuning หลังเห็น transfer predictions มี technical adapter repair หลัง partial run แรก: nullable cosine similarity และ follow-up query cache จากนั้น restart ทุก arm/ทุกคำถาม เก็บ first attempt และรายการ 7 คำถามที่มี repeat exposure จึงไม่อ้างว่าเป็น pristine never-exposed question test
- ระหว่าง final v2 มี Windows/OneDrive file-lock ทำให้ checkpoint save หยุด ตรวจ hash และความเท่ากันของ 184 outputs เดิม แล้วกู้ pending output ที่ 185 จากไฟล์เดิม จากนั้น resume เฉพาะ outputs ที่ขาด ไม่ regenerate 185 คำตอบที่จ่ายไปแล้ว; เปลี่ยนเฉพาะ I/O/resume orchestration ดู FINAL_IO_REPAIR_DISCLOSURE.json
- Judge scheduling ใช้ separate processes สำหรับ future arms แล้ว import เฉพาะ cache ที่ payload ตรงกับ original ทุก field; เก็บทั้ง measured/failed outcomes, original cache ที่มีอยู่ชนะเสมอ ไม่เลือกคะแนนที่สูงกว่า หากมี overlap เก็บทั้ง raw outcomes/calls ดู final_judge_shards/scheduling_disclosure.json
- หลัง worker interruption พบ latest ledger/dense journal บางไฟล์เป็น zero bytes: เก็บไฟล์เสียและ journals ก่อน resume, กู้ latest valid global checkpoint ที่ SDK=2909 โดยไม่ reset usage, เพิ่มเฉพาะ flush/fsync ก่อน atomic checkpoint replace (11 tests passed) แล้วลดเหลือสอง workers ไม่มี model/prompt/schema/scorer/label change ดู interruption_recovery_v1; usage ที่อาจหายก่อน checkpoint ไม่ทราบ ดังนั้น SDK/token totals เป็น lower bounds และ cost ยัง N/A
- Resume ไม่เขียน aggregate JSON ที่สร้างใหม่ได้ซ้ำทุก cached row; raw outcomes/SDK ledgers ใหม่ยัง checkpoint ทันที และจุดสุดท้ายเขียน aggregates ครบ การแก้เป็น I/O scheduling เท่านั้น เก็บ old code/method locks และตรวจ metric reproduction หลังจบ ดู CACHE_CHECKPOINT_IO_DISCLOSURE.json
- Report/issuer names และไฟล์ต่างจาก development; ultimate ownership-family independence ไม่ได้รับรอง
- คำถามมี variants ที่ใช้ข้อเท็จจริง/หน้าเดียวกัน; Wilson intervals ใน raw metrics เป็น question-level independence approximation เท่านั้น ไม่ใช่ issuer-population CI หรือหลักฐานความทั่วไปจากเพียงสามรายงาน และไม่รายงาน measured complete rate เมื่อยังมี unresolved
- Numeric labels เป็น inventory ที่ล็อกไว้ ไม่ครอบคลุมตัวเลขทุกตัวในทุกคำตอบ semantic identity supplement ตรวจเพียงความหมาย entity/measure โดยไม่เติม annotation ให้แอปหรือแก้ value/unit/year/page/comparator และแสดง literal scores เดิมแยก
- Ingestion relationship audit เดิมยังมี 53 unknown verdicts/หนึ่ง invalid source-probe page และ TOC ที่ถอดเป็น table (ไม่มี CSV numeric cells) ไม่อ้างว่าตรวจทุก cell ผ่าน
- ไม่ขยาย 500–1,000 cloud answers ระหว่างที่ quality targets ยังไม่ผ่าน งานนี้ไม่มี commit/push/deploy หรือการลบ production DB

## ทรัพยากร

SDK attempts ที่บันทึกได้สะสม 3311 (lower bound หากมี accounting_recovery); known input 54,347,114; known output 1,802,576; failed attempts ที่ usage ไม่ครบ 324; paid OCR unique pages สะสม 66
เพิ่มจาก parent snapshot: {"sdk_attempts": 1883, "known_input_tokens": 35493382, "known_output_tokens": 838440, "failed_calls_without_complete_usage": 192, "paid_ocr_pages_new": 0}
Cloud USD cost/cloud memory = N/A ไม่ถือ failed calls ว่าใช้ฟรี RSS/GPU ที่สังเกตเป็น partial concurrent observations ไม่ใช่ isolated peak หรือ controlled speed benchmark

## หลักฐาน

- Raw results: `TestFile/evaluation_completion_2026-10-07/`
- `FINAL_DISPATCH_GATE.json`, `FINAL_CODE_AND_INPUT_FREEZE.json`, per-run frozen code/labels, raw SDK traces/judge inputs/outputs, versioned label changes, resource ledger และ tests JUnit
- METRICS.json เก็บ denominators/missingness และแยก scope ของผล; metrics CSV เป็นข้อมูลสรุป ไม่ใช่ Ragas official scores
