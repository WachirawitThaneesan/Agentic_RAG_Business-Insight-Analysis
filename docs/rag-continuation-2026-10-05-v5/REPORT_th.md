# ผลรับช่วง Thai Business RAG evaluation — 5 ตุลาคม 2026

สถานะ: `bounded_run_finished_targets_remaining` งานเพิ่มคุณภาพยัง **partial** และ Goal เดิมยัง `usageLimited` ผลตรวจทั้งหมดเป็น AI provisional, `human_confirmed=false` การเปลี่ยนแชทไม่ได้เริ่มงบหรือ deadline ใหม่

รอบนี้พบและแก้บั๊กหน่วยตารางจริง พร้อมตรวจ scorer และเฉลยที่ทำให้คะแนนเดิมสูงเกินจริง ระบบยังไม่ผ่านเกณฑ์สำหรับขยายเป็น 500–1,000 คำตอบหรือประกาศผล unseen คะแนนเก่าและผลที่ล้มเหลวถูกเก็บไว้ครบ

## ผลที่พิสูจน์ได้

| สิ่งที่วัด | ก่อน | หลัง | ขอบเขต |
|---|---:|---:|---|
| Retrieval Page Hit@5 | 373/498 = 74.90% | 415/498 = 83.33% | ผล paired ที่รับช่วงมา: v4, 4 รายงานที่ใช้พัฒนาแล้ว |
| nDCG@5 | 0.6276 | 0.7314 | ชุด retrieval เดียวกัน |
| MRR@5 | 0.5876 | 0.6977 | ชุด retrieval เดียวกัน |
| หน่วย/ค่า/ปี/หน้าของเซลล์ตาราง | 0/21 | 21/21 | OCR จริงชุดเดิม, CPAXT physical PDF หน้า 133 |
| คำตอบตารางที่ตรงรายการ/ปี/ค่า/หน่วย/หน้า | 0/3 | 3/3 | 3 development questions, คำตอบใหม่หลังแก้, AI visual review |
| Factual support แบบ macro ของคำตอบที่บันทึกแล้ว | 55.17% (v4) | 50.17% (v5) | 20 คำตอบเดิม เปลี่ยนเฉลย B0001 หนึ่งข้อ ไม่เปลี่ยนคำตอบ |
| Faithfulness support แบบ macro | 53.75% | 53.75% | quote membership และ AI entailment ต่อ actual captured context |

Retrieval กู้ได้ 61 ข้อ ถอยหลัง 19 ข้อ และเหลือ miss 83 ข้อ ผลต่าง +8.43 percentage points มี bootstrap CI แบบจัดกลุ่มตามหน้าหลักฐาน +4.08 ถึง +13.02 points เงื่อนไขของช่วงนี้คือ 4 รายงานเดิม ไม่ครอบคลุมการ generalize ไปยังรายงานใหม่ เป้า Hit@5 90% ยังไม่ถึง รักษา `lexical_first` ที่เลือกไว้และคง `hybrid_current` สำหรับเปรียบเทียบ [หลักฐาน paired](../../TestFile/rag-continuation-2026-10-05-v5/evidence/historical_inputs/paired_lexical_first498/summary.json)

## การแก้โค้ดและตรวจตารางจริง

ในหน้า CPAXT 133 หัวตารางเขียน “บาท (THB)” แต่ทุกแถวระบุ “ล้านบาท” Typhoon/Gemini เก็บตัวเลข 21 ช่องและปี 2565–2567 ถูกทั้งหมด ระบบ DuckDB กลับให้หัวตารางมีลำดับเหนือหน่วยแถว จึงเก็บหน่วยผิดทุกช่อง และ guard ปฏิเสธคำตอบทั้ง 3 ข้อ

แก้ `duckdb_warehouse._cell_unit()` ให้หน่วยเงินที่ระบุในเซลล์ คอลัมน์ และแถวมีลำดับเหนือหน่วยรวม โดยเก็บตัวเลขเดิม ไม่คูณหรือแปลงค่า รองรับล้านบาท/พันบาทและบาทที่ระบุชัด พร้อมคงกฎเปอร์เซ็นต์และกำไรต่อหุ้น

ผล v6 ถูกเก็บไว้ การตรวจ v7 ใช้ไฟล์ OCR เดิมแบบ byte-identical โหลดลง DuckDB สำเนาใหม่ แล้วเรียก full agent ใหม่ 3 คำถาม เพิ่ม 6 SDK calls และไม่มี OCR ใหม่ ไฟล์ฐานเดิมมี SHA256 เท่าเดิม ก่อนแก้เลขถูก 21/21 แต่ tuple ผิด 21/21 หลังแก้ tuple ถูก 21/21 คำตอบคือ 10,831 ล้านบาท ปี 2567, สินทรัพย์รวม 540,371 ล้านบาท ปี 2566 และสินทรัพย์สิทธิการใช้ 41,079 ล้านบาท ปี 2567 ทุกคำตอบอ้างหน้า sample 1 ซึ่ง map ไป original 133

ผลนี้เป็น targeted development validation การแก้ใช้ข้อมูลหน้านี้ จึงใช้ยืนยันผล unseen ไม่ได้ และยังไม่ได้วัด complete success หรือ actual claim-citation precision ของ 3 คำตอบนี้ [เซลล์ก่อน–หลัง](../../TestFile/rag-continuation-2026-10-05-v5/evidence/ingestion_table1_v7_unit_repair/cell_comparison.json), [คำตอบและ visual review](../../TestFile/rag-continuation-2026-10-05-v5/evidence/table_answer_visual_review3.json)

## Scorer, numeric และ citation

เพิ่ม offline contract replay จาก raw AI judgments และคำตอบ/context ที่จับไว้จริง เวอร์ชัน v2.2 ตรวจทั้ง file hashes และ question/reference prefix ของแต่ละ bank item เพื่อป้องกันการนำ audit เฉลยเก่ามาประเมินด้วย bank รุ่นใหม่ silently

| มิติ | ผล v5 ของ saved 20 | Coverage / ข้อจำกัด |
|---|---|---|
| Faithfulness claims | supported quote 35/56 = 62.50% micro; macro 53.75% | อีก 21 claims quote ตรวจไม่พบ ไม่ถือว่าเป็น hallucination อัตโนมัติ |
| Factual claims | supported quote 19/56 = 33.93% micro; macro 50.17% | AI contradicted 10, insufficient 1, quote-unverifiable 26 |
| Strict numeric จาก captured app output | N/A | 8 tuples ต้องใช้ แต่ app ไม่เก็บ structured annotations |
| Numeric จาก AI review sidecar | 2/4 = 50% ในส่วนที่วัดได้ | วัด 4/8 tuples = 50% coverage, อีก 4 ยัง unresolved |
| Actual claim→citation precision / recall | N/A | mapping ไม่มีครบทั้ง 20 ข้อ; ตัด 59 judge-proposed links ออกจาก metric |
| Complete answer success ตาม contract ใหม่ | N/A | unresolved 20/20; lower bound 0/20 เป็นขอบเขตล่าง ไม่ใช่ measured accuracy 0% |

Numeric sidecar ถอดจากข้อความคำตอบและบันทึก provenance/answer quote แยก ไม่เติมบริษัท รายการ ปี หน่วย หรือหน้าจาก gold ลงใน app output กรณีไม่สามารถผูก tuple ได้ยังคง N/A ผล 2/4 เป็น AI review diagnostic และไม่ใช่ strict app accuracy ที่ครบ coverage [replay v5](../../TestFile/rag-continuation-2026-10-05-v5/evidence/contract_replay20_v5_visual/summary.json), [sidecar](../../TestFile/rag-continuation-2026-10-05-v5/evidence/numeric_answer_annotations_ai_review.json)

พบอีกว่า scorer เดิมใช้ returned sources 200 records แต่ captured generation prompts มี page blocks 87 blocks และ scope ต่างกันทุกคำถาม Source usefulness ที่ประเมินทั้ง returned list จึงใช้แทน relevancy ของ actual prompt ไม่ได้ ค่า 90% ที่ handoff เดิมเรียกว่า context relevancy เป็น **answer relevancy rubric** ต้องแก้ชื่อเมื่อรายงาน ไม่ใช่ผล context relevance 90% [audit](../../TestFile/rag-continuation-2026-10-05-v5/evidence/context_scope_audit20.json)

## เฉลยที่แก้รุ่นใหม่

ภาพ PTT physical page 3 ระบุวิสัยทัศน์ “ปตท. แข็งแรงร่วมกับสังคมไทย และเติบโตในระดับโลกอย่างยั่งยืน” เฉลย B0001 เดิมนำข้อความพันธกิจมาใส่เป็นวิสัยทัศน์ Native text วางหัวข้อสลับกันและ judge เดิมยอมรับตามเฉลยที่ผิด

ล็อก bank v5 โดยแก้ B0001 เพียงข้อเดียว อีก 497 items และ numeric labels 101 tuples คงเดิมทุก byte ที่เกี่ยวข้อง ปรับ factual verdict ของคำตอบเดิมเฉพาะ B0001 ด้วย visual AI adjudication และ replay ทั้ง 20 ข้อ ไม่มี generator/judge cloud call ใหม่ ค่า macro ที่ลดลงเกิดจากการแก้เฉลย ไม่ใช่ regression ของระบบ คำตอบยังได้รับ faithfulness support จาก context เก่าที่ทำให้เข้าใจผิด ซึ่งแสดงว่าความสอดคล้องกับ context และความถูกต้องตาม PDF เป็นคนละมิติ

การตรวจรอบรับช่วงเกิดหลังเข้าถึงผลประวัติแล้ว จึงไม่อ้างว่าเป็น independent blinded review และไม่มี human certification [change log และภาพ](../../TestFile/rag-continuation-2026-10-05-v5/evidence/labels_v5/change_log.json), [lineage](../../TestFile/rag-continuation-2026-10-05-v5/evidence/audit20_v5_visual_adjudication/lineage.json)

- v4 reference SHA256: `0b3bfe692d4716c66a998b4e084110b3fa6c8f30ec951d302a0b4488689ba115`
- v5 reference SHA256: `24e8d33d7fd441fccc4b2ab02f6ef9f47d84af8db03355bb78676b340cb195a5`
- numeric labels SHA256 ทั้ง v4/v5: `a19b85f9637508b7b7f35f33afd6c1a69d9bc56bcf684f2aa946734e89505d0e`

## เส้นทางอัปโหลดและ UI ที่รันจริง

ใช้ actual FastAPI upload/job → Typhoon text / Gemini table → PostgreSQL + DuckDB → local BGE-M3 retrieval → Gemini agent ในฐานข้อมูลทดลองใหม่ แยก uploads และ warehouse โดยปิด graph ใน process ประเมิน ตัว route และ frontend เป็นของ repository

รวม 5 original physical pages จาก 2 development reports: PTT 3/40 และ CPAXT 29/38/133 มี original/sample hashes และ page mapping ทุกหน้า ทั้ง 5 หน้า indexed; 4 หน้าแรกรวม 48 chunks, หน้าตารางอีก 5 chunks และ 7 structured rows (21 stored cells) PTT ยังเป็น partial เพราะ table warning จึงไม่เรียก ingestion ว่าสมบูรณ์ทุกมิติ

รอบแรกมี Typhoon timeout และ budget guard จึงได้ fallback responses ที่ไม่ใช่ model answers เก็บผลไว้และ retry เฉพาะหน้าที่ต้องทำใน DB เดิม ได้ 4 model-generated answers จริง: B0001 ยังตอบพันธกิจ, B0306 ยังสับสนปีเหตุการณ์ 2562 กับปีรายงาน 2567 และทำ `≤` หาย, B0053 ตอบค่า/ปี/หน่วยตรง, B0315 ทำ approximately หาย

Runner retry ออก exit 1 เพราะไม่รองรับ HTTP 409 “already complete” ตอนตรวจ resume เก็บ failed exit ไว้ แก้ runner แล้วตรวจ actual API แยกโดยไม่ regenerate คำตอบ พบ resume ไม่เพิ่ม rows และไม่จ่าย cloud ซ้ำ จึงแยก operational runner error ออกจากคุณภาพคำตอบ

เปิดแอปจริงบน test DB ถาม B0053 ได้ 10,831 ล้านบาท ปี 2567 และคลิก citation เปิด CPAXT sample หน้า 2 ตรง original หน้า 38 Screenshot ทั้งคำตอบและหน้าอ้างอิงถูกเก็บไว้ Server ชั่วคราวและ tabs ที่สร้างถูกปิดแล้ว [ingestion summary](../../TestFile/rag-continuation-2026-10-05-v5/evidence/ingestion_smoke4_audited_summary.json), [resume audit](../../TestFile/rag-continuation-2026-10-05-v5/evidence/ingestion_idempotency_audit.json), [UI screenshot](../../TestFile/rag-continuation-2026-10-05-v5/evidence/ui_ingestion_smoke4_v5/citation_CPAXT_sample2_original38.png)

ยังไม่ครบชุด ingestion stratified 30–50 หน้า, scraped-PDF path, production/staging reingest/migration และการเปรียบเทียบ native-text กับ production OCR อย่างควบคุมเงื่อนไขเดียวกัน การเปิดหน้า citation ถูกต้องหนึ่งกรณีไม่ยืนยัน entailment ของทุก claim

## ทรัพยากรและการทดสอบ

| รายการ | เพิ่มในแชทนี้ | สะสมตามงบเดิม |
|---|---:|---:|
| SDK / HTTP attempts | 33 (success 32, timeout 1) | 127/600 |
| Known input tokens | 131,036 | 1,289,312/2,000,000 |
| Known output tokens | 12,279 | 94,084/300,000 |
| Failed calls ที่ usage ไม่ครบ | 1 | 3; reserves input 300,000 / output 98,304 |
| Unique paid physical OCR pages | 5 | 5/60 |
| Ranking configurations | 0 | 10/12 |

Deadline เดิม **2026-10-05 11:32:17 +07:00** Cloud USD cost, runner peak RSS, GPU memory และ cloud-provider memory ไม่ได้วัดใน continuation ให้เป็น N/A จำนวน tokens ข้างต้นเป็น known usage; ห้ามตี failed calls เป็น zero-cost

ชุด integration แรกใช้ 27 attempts ของ cap 30 หลังพบ row-unit bug เปิด follow-up validation แยก cap 6 และใช้ครบ 6 โดยไม่เปลี่ยนวงเงินรวม/deadline Successful Gemini requests ระบุ `thinking_budget=0`; meter ปรับ reservation ตาม request ที่จับได้ แต่ returned thinking usage ยังเป็น null และ failed-usage reservations ยังคงอยู่ ความหมายของ budget 0 อ้างอิง [Google Gemini thinking documentation](https://ai.google.dev/gemini-api/docs/generate-content/thinking) บันทึกก่อน–หลังไว้ใน [reservation correction](../../TestFile/rag-continuation-2026-10-05-v5/evidence/budget_reservation_correction.json)

Model-call tracing แยก per-attempt SDK latency ออกจาก generate time ที่รวม pacing/backoff เก็บ errors/retries/cancellation และคืน context หลัง cancellation/nested calls ถูกต้อง ตัวเลขเวลาของ SDK/HTTP รวมกันใช้แทน benchmark wall time ไม่ได้ เช่น v6 table run wall time 32.50 วินาที และ API upload/ingestion 16.36 วินาที [resource ledger](../../TestFile/rag-continuation-2026-10-05-v5/evidence/RESOURCE_LEDGER.json)

Final focused regression **239 passed**, มี Pydantic deprecation warning เดิมหนึ่งรายการ ครอบคลุม scorer, tracing, retrieval/context, table unit/provenance, signed values/scales/year, ingestion/resume และ agent guards [JUnit](../../TestFile/rag-continuation-2026-10-05-v5/evidence/tests/regression_final.xml) Diff check เฉพาะ production files ที่รอบนี้แก้ผ่าน; global checkout ยังมี trailing blank line เดิมใน test_page_context.py

## งานค้างและสิ่งที่ส่งมอบ

Gate ก่อนขยายยังไม่ผ่าน: ไม่มี 50 paired ที่ coverage ≥95%, actual claim citations และ numeric output annotations ยังขาด จึงไม่เพิ่ม 500–1,000 answers และไม่ทำ final unseen test เพื่อผลิต headline จาก schema ที่ยังประเมินไม่ครบ

Bangchak/WHAUP/CPN มี hashes/page counts ตรง ดาวน์โหลดคนละไฟล์กับ 11 development reports และ sparse probes พบภาษาไทย แต่ยังไม่ได้ตรวจภาษาเต็มรายงาน/issuer-family independence, สร้าง labels หรือสอบ จึงคงเป็น candidates ที่ยังไม่ใช้ tune ไม่มี unseen accuracy

ส่ง `METRICS.csv`, `NEXT_ACTION.md`, `COMMANDS.md`, raw evidence, frozen code/labels, resource ledger และ SHA256/ZIP verification พร้อม publish รุ่นใหม่ใน repo แยกจากคะแนนเก่า Source snapshot รันร่วมกับ dependency/config ของ repo เดิม; ไม่รวม credentials, .env หรือ model weights และไม่ได้ทำ commit/deploy/ลบ production DB

ลำดับถัดไปคือ capture actual claims/citation links และ bound numeric annotations ใน app, จับ exact prompt contexts ให้ scorer ใช้ scope เดียวกัน แล้วทำ 50 paired ก่อนขยายหรือ freeze final unseen ดู [คำสั่งและงานรับช่วง](../../TestFile/rag-continuation-2026-10-05-v5/evidence/NEXT_ACTION.md)
