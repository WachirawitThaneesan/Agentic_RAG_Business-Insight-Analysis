> **Current update — 8 October 2026:** See [Evaluation Progress and Next Steps](EVALUATION_NEXT_STEPS_2026-10-08.md) and the [full498 English report](GEMINI_RAG_FULL498_REPORT_2026-10-08.md). All498 original outputs now have valid AI judgments; eight conservative RAG scores exceed80%. Numerical and complete-answer targets remain future work. Historical estimates, active-worker statements, and earlier no-push restrictions below are superseded where applicable; the user explicitly authorized publication to `auto1`. Docling remains deferred.

# แผนปรับปรุงและประเมิน Thai Business RAG — ส่งต่อให้ GPT-6.1 Sol

**คำสั่งผู้ใช้ล่าสุด 8 ตุลาคม 2026:** ให้ปิด evaluation ของ OCR Gemini ก่อนเริ่ม local Docling. Gemini ยังคงใช้ targets ในแผนนี้; เฉพาะ local Docling ให้ปรับ metrics ให้ดีที่สุดโดยไม่ใช้ >90% เป็นเงื่อนไขบังคับจบรอบ. คงวิธีให้คะแนนและการเปิดเผย failures/unknowns ตามจริง ดู `docs/EVALUATION_CHAT_ROADMAP_2026-10-08.md` สำหรับขอบเขตและ checkpoint ล่าสุด

วันที่จัดทำ: 2026-10-05 (Asia/Bangkok)  
สถานะเอกสาร: **แผนหลักพร้อมสถานะผลจริง ณ ส่งต่อ; งานยังไม่ครบทุกขั้น**  
ผู้ใช้อนุญาตให้ AI ตรวจ PDF แทนผู้ตรวจมนุษย์ และให้ตัดสินใจทำงานต่อได้โดยไม่ต้องถามระหว่างที่ผู้ใช้พักผ่อน

## 1. เป้าหมายและขอบเขต

ปรับระบบให้ค้นหลักฐาน ตอบข้อเท็จจริง และอ้างอิงได้ดีขึ้นมากที่สุดภายใต้เกณฑ์ที่ล็อกไว้ พร้อมผลทดลองที่ตรวจย้อนหลังและทำซ้ำได้ ทุกคะแนนต้องเกิดจากการรันจริง เป้าหมายเปอร์เซ็นต์เป็น **engineering targets ของโครงการ** ไม่ใช่เกณฑ์ผ่าน thesis สากล และไม่รับประกันว่าจะถึงทั้งหมดในคืนเดียว

ลำดับหลัก: **0 เตรียมการ → 1 ตรวจเฉลย/เกณฑ์ → 2 Retrieval → 3 Context/ตาราง → 4 คำตอบ/Citation → 5 เส้นทางอัปโหลดจริง → 6 รายงานไทยใหม่ → 7 สรุปและส่งมอบ**

ทำทีละขั้นที่มี dependency แต่ให้ทำงานที่ไม่ติดอุปสรรคต่อได้ เช่น หาก API ใช้ไม่ได้ ให้ทำ retrieval แบบ local, tests, การตรวจ artifacts และรายงานต่อ ไม่ต้องหยุดรอให้ผู้ใช้ตอบ เรื่องที่ตัดสินใจเองให้บันทึกเหตุผลสั้น ๆ ใน decision log

**ขอบเขตคืนแรก:** จบการตรวจที่ค้าง วัด baseline เดียวกัน ทดลองแก้ที่มีเหตุผล ตรวจ regression และเก็บผลที่ดีที่สุดที่พิสูจน์ได้ ขั้นที่ติดงบ เวลา หรือข้อมูลให้แสดงสถานะจริงพร้อมคำสั่งรับช่วง ห้ามเขียนว่าทำครบเพียงเพราะถึงเวลาส่งรายงาน

## 2. ตำแหน่งงานที่ต้องใช้

| ชื่อย่อในแผน | Absolute path |
|---|---|
| REPO | `C:\Users\nonga\OneDrive\Desktop\Project_2\Agentic_RAG_Business-Insight-Analysis` |
| TASK | `C:\Users\nonga\Documents\Codex\2026-09-25\i-would-currently-rate-the-project` |
| ORIGINAL | `TASK\outputs\comprehensive_eval_2026-10-04_v1` |
| REPAIR | `TASK\outputs\evaluation_repair_2026-10-05` |
| CONTRACT | `TASK\outputs\evaluation_contract_2026-10-05_v2` |
| NEW (สร้างและมีผลแล้ว) | `TASK\outputs\ranking_evidence_2026-10-05_v3` |

`TASK`, `REPO` ฯลฯ ในตารางเป็นชื่อย่อสำหรับอ่าน ไม่ใช่ environment variables ที่มีอยู่แล้ว ต้องขยายเป็น path จริงก่อนใช้

- Branch ล่าสุดที่ตรวจ: `auto1`; ตรวจอีกครั้งก่อนเริ่ม ห้าม checkout ทับงานที่ยังไม่ commit
- ใช้ Python ของ repo: `REPO\.venv\Scripts\python.exe`; ตั้ง `PYTHONUTF8=1` สำหรับ output ภาษาไทย
- มีงานแก้ไขและไฟล์ untracked จำนวนมากจากรอบก่อน เป็นงานที่ต้องเก็บไว้ ไม่ใช่ขยะให้ล้าง
- อ่าน `AGENTS.md` ที่พบใน path งานหากมี ก่อนแก้ไข; ในรอบจัดทำแผนนี้ไม่พบตาม parent paths และ `docs`
- Production ที่ผู้ใช้เลือก: **Typhoon สำหรับข้อความ, Gemini สำหรับตารางและ agent/คำตอบ, BGE-M3 สำหรับ embeddings**; ไม่กลับไปใช้ Qwen2.5 ในเส้นทาง online
- อ่านชื่อ provider/model จาก config จริงโดยไม่พิมพ์ key หรือ credential contents ลง log; model ฝั่ง Codex ที่ทำงานนี้คือ GPT-6.1 Sol ตามที่ผู้ใช้เลือก ไม่ใช่การเปลี่ยนโมเดลในแอป RAG ให้เป็น Sol

## 3. สถานะจริง ณ จุดส่งต่อ 2026-10-05

สถานะงานรวม: **ยังไม่เสร็จทั้งแผน**; จุดส่งต่ออยู่หลัง retrieval 498 ข้อ และ answer smoke 20 ข้อ อ่าน `docs/HANDOFF_2026-10-05.md` กับ `docs/goals/2026-10-05-01-rag-evaluation-continuation.md` ก่อนทำงานต่อ

### 3.1 ผลใหม่ที่รันจริงแล้ว

| ขั้น/สิ่งที่วัด | ผลล่าสุด | ข้อจำกัด/หลักฐานใน NEW |
|---|---|---|
| 0 เตรียม run | มี manifest, baseline code snapshot, input hashes | `run_manifest.json`; deadline เดิม 2026-10-05 11:32:17 +07:00 |
| 1 เฉลย/เกณฑ์ | ตรวจ AI 22 กรณี; frozen v4 498 ข้อ; แก้ wording 3 ข้อ; numeric 101 ค่า | `labels_v4/summary.json`; human confirmed = 0; AI provisional |
| 2 Page Hit@5 | **373/498 (74.9%) → 415/498 (83.3%)** | same v4 labels/corpus; `paired_lexical_first498`; กู้ 61 ถอย 19 เหลือ miss 83 |
| nDCG@5 / MRR@5 | .6276 → .7314 / .5876 → .6977 | diagnostic 4 reports ที่ใช้พัฒนาแล้ว |
| Ranking ที่เลือก | `lexical_first` เป็น default ใน rag.py; `hybrid_current` ยังเลือกได้ | retrieval tests 11 passed; ยังไม่ถึงเป้า Hit@5 90% |
| 3 Context | ทดลอง 2 แบบแล้วไม่รับเข้า production | quote-in-prompt baseline 10/20; uniform 7/20; first-two 10/20; revert แล้ว |
| 4 คำตอบ smoke | generate 20/20; judge 20/20 | `answer_smoke20`, `smoke20_eval_judged`; scorer ยัง comprehensive-rag-v1.5 |
| Factual precision / recall | macro **55.17% / 76.67%** | ชุด 20 ข้อ; ไม่ใช่ paired comparison กับชุดเก่า 50 ข้อ |
| Context recall / relevancy | macro **51.67% / 90.0%** | quote-in-prompt 10/20 เป็นคนละ metric |
| Faithfulness quote-verified | macro **53.75%** | raw AI verdict สูงกว่ามาก; quote หาไม่ได้ไม่เท่ากับพิสูจน์ว่าผิดจริง |
| Complete success เกณฑ์เก่า | **3/20 = 15%** | ไม่ใช่ complete success ตาม contract ใหม่ |
| Strict numeric / actual claim citation | ยังประเมินไม่ครบ | numeric scorable 1/20; 19 needs review; source-list proxy ใช้แทน claim citation ไม่ได้ |
| 5 เส้นทางอัปโหลดจริง | ยังไม่รันรอบใหม่ | ห้ามอ้างว่า native PDF benchmark พิสูจน์ Typhoon/Gemini ingestion |
| 6 รายงานใหม่ | ดาวน์โหลด Bangchak, WHAUP, CPN แล้ว | เป็น candidates เท่านั้น ยังไม่ตรวจภาษา/สร้าง labels/สอบ held-out |
| 7 สรุปสุดท้าย | ยังไม่เสร็จ | มี checkpoint/handoff; `REPORT_th.md` ฉบับจบงานยังไม่มี |

ผลเดิม 50 คำตอบ (precision 69.5%, recall 50.7%, context recall 63.6%, relevancy 65%, complete 10/50) ยังคงเดิมใน ORIGINAL/REPAIR/CONTRACT ห้ามนำมาคำนวณ delta กับ smoke20 ซึ่งเป็นคนละ subset และ scorer coverage ต่างกัน ผล 95% จาก branch ทดลองเก่าก็ไม่ใช่ผล strict evaluation ของ current app

### 3.2 ข้อค้นพบและงานค้าง

- ตรวจ calibration แล้วพบ AI reviewer ตัดสิน label ผิด 4 กรณี จึงเปิดภาพ PDF ตรวจและ override พร้อมหลักฐาน; B0306 หน้าจริง PTT p.40 ระบุ **กบง.** ไม่ใช่ กพช.
- PTT ยังอ่อน: Hit@5 73/131; native PDF text มีอักขระไทยเพี้ยน ควรตรวจ/แก้ extraction บนหน้าที่จำเป็นก่อนเพิ่ม weight sweeps
- สอง context candidates ถูก revert เพราะไม่เพิ่ม coverage; ห้ามรับช่วงแล้วคิดว่ายังเปิดใช้อยู่
- ต้องต่อ scorer contract v2, numeric labels และ actual claim→citation mapping เข้ากับคำตอบที่แอปส่งจริง ก่อนขยายเป็น 500–1,000 คำตอบ
- model-call tracing เพิ่มแล้ว; ต้องตรวจ regression ของ tracing โดยเฉพาะ errors/retries/cancellation
- ผลใหม่ทั้งหมดยัง diagnostic และ AI-reviewed ไม่ใช่ independent human confirmation หรือ final unseen thesis score
- Goal เดิม ณ ส่งต่อเป็น `usageLimited` ไม่ใช่ completed; ไม่มี experiment ที่เริ่มไว้ค้างรันตาม checkpoint นี้
- ใช้ cloud ไป 94 SDK attempts; reported input 1,158,276 / output 81,805 tokens; failed review calls 2 ครั้งไม่มี usage ครบ; cost USD unknown; paid OCR ใหม่ 0 หน้า
- กำหนดเวลาเดิม **11:32:17 เวลาไทย 5 ต.ค. 2026** และงบเดิมต้องตามไปแชทใหม่ ห้ามเริ่มนับใหม่จากศูนย์

รายละเอียด คำสั่งตรวจจุดรับช่วง ผลที่ถูกปฏิเสธ และไฟล์จริงอยู่ใน handoff; อ่านก่อนรันใหม่

## 4. เป้าหมายคะแนนและวิธีตัดสิน

คง targets เดิมใน `backend/eval/contracts.py` และบันทึกเวอร์ชันเกณฑ์ก่อนรัน หากพบ bug ทางคณิตศาสตร์ให้แก้เป็น scorer รุ่นใหม่ รันทั้ง baseline และ candidate ด้วยรุ่นเดียวกัน และเก็บผลเก่าไว้

| Metric | เป้าหมายหลัก | หน่วย/ข้อควรระวัง |
|---|---:|---|
| Page Hit@5 | ≥90% | จำนวนคำถามที่พบอย่างน้อยหนึ่งหน้าที่รองรับ / คำถาม answerable ทั้งหมด |
| Required-evidence Recall@5 | ≥90% | สัดส่วนหลักฐานจำเป็นที่พบ; ใช้ AND สำหรับหลายหน้าที่ต้องใช้ร่วมกัน และ OR สำหรับหน้าทางเลือก |
| Factual precision | ≥95% | claims ที่ถูกตาม PDF / claims ที่ตอบ; รายงานทั้ง micro และ macro |
| Factual recall | ≥85% | ข้อเท็จจริงที่จำเป็นและตอบถูก / ข้อเท็จจริงที่จำเป็นทั้งหมด |
| Context recall | ≥90% | ข้อเท็จจริงจำเป็นที่ actual model context รองรับได้ |
| Faithfulness | ≥95% | claims ที่ actual context รองรับ ทั้งตรวจตำแหน่ง quote และ entailment |
| Answer relevancy | ≥90% | คะแนน rubric 0/1/2 ที่ล็อกไว้ หารด้วยคะแนนเต็ม |
| Actual citation link precision | ≥95% | citation links ที่แอปอ้างจริงและรองรับ claim / links ที่อ้างจริงทั้งหมด |
| Citation claim recall | ≥90% | claims ที่ควรมีหลักฐานและมี citation ที่ถูก / claims ที่ต้องอ้างทั้งหมด |
| Strict numeric accuracy | ≥95% | ค่าและความสัมพันธ์ทั้งหมดถูก รวมบริษัท รายการ ปี หน่วย หน้า และ comparator |
| Complete answer success | ≥75% | ทุก gate ที่ applicable ผ่านต่อคำถาม; failed generation นับ fail |
| Evaluation coverage | ≥95% | จำนวนหน่วยที่ตรวจได้จริง / จำนวนหน่วย eligible; ต้องแสดง N/A และ failed judge |

ตัวชี้วัดเสริมที่ต้องรายงาน: Precision@1/3/5, Recall@1/3/5/10, MRR@5/10, nDCG@5/10, complete-evidence rate, context precision/AP, answer coverage, correct abstention rate, false refusal rate, hallucinated-answer rate บน unanswerable controls, exact/rounded numeric accuracy แยกกัน, OCR/cell relationship accuracy, time/calls/tokens/resources

- MRR/nDCG และ context precision: ใช้ดูการเปลี่ยนแปลงและ trade-off ก่อน อย่าเพิ่มเกณฑ์ผ่านตามใจหลังเห็นผล
- **ห้ามตั้ง Page Precision@5 ให้ต้องได้ 90% เมื่อหนึ่งคำถามมี gold page เดียว**: หากคืน 5 หน้าและมีหน้า relevant ที่ติด label เพียงหน้าเดียว เพดานตาม label จะเป็น 20% ต้องรายงานความครบของ relevance labels และแยก page precision จาก factual precision
- Qrels ที่ยังไม่ได้ตรวจทุกหน้าควรติดสถานะ `unjudged`; คะแนนแบบ incomplete-qrels ให้แสดงข้อจำกัด ตรวจ pooled candidates จากทุกวิธีแบบ blind ก่อนใช้เป็น final precision/nDCG
- Abstention ไม่มี factual claims ให้ precision เป็น N/A พร้อมวัด false refusal/recall; ไม่ให้ตอบว่าไม่ทราบทุกข้อแล้วได้คะแนนดี
- Complete success: answerable ต้องตอบข้อเท็จจริงจำเป็นครบ ทุก claim ถูก/faithful/relevant และมี citation ถูกตามสัญญา; คำถามตัวเลขต้องผ่าน strict numeric ด้วย ส่วน unanswerable ใช้ abstention rubric แยก ไม่บังคับ metric ที่ไม่ applicable
- Quote ที่หาเจอเป็นเพียงการตรวจตำแหน่งข้อความ ต้องตรวจด้วยว่าเนื้อความรองรับความสัมพันธ์จริง; quote ที่หาไม่เจอไม่เท่ากับพิสูจน์ว่า hallucination
- อัตราที่รายงานทุกอันต้องมี numerator/denominator, จำนวน missing/unsupported/error, dataset version, code hash และ scorer version
- รายงาน 95% CI เมื่อทำได้: Wilson สำหรับอัตราทวิภาค และ paired bootstrap โดยจัดกลุ่มคำถามจากหลักฐานเดียวกันสำหรับ delta; รายงานทั้ง micro/macro และตามบริษัท ไม่อ้างความทั่วไปจาก CI ของเพียง 4 รายงาน
- การผ่าน point target บนชุด diagnostic ไม่ใช่หลักฐานว่าผ่านบนรายงานที่ไม่เคยใช้พัฒนา

## 5. กติกาการทำงานอัตโนมัติและค่าใช้จ่าย

### 5.1 สิ่งที่ตัดสินใจและทำต่อได้

- ตรวจ/แก้โค้ดที่เกี่ยวข้อง รัน tests และ benchmarks สร้างฐานข้อมูลทดลองแยก อ่าน/เรนเดอร์ PDF สาธารณะที่มีอยู่ และดาวน์โหลดรายงานไทยสาธารณะจากเว็บไซต์เจ้าของรายงาน
- ใช้ AI ตรวจเฉลยแทนคนตามคำอนุญาตผู้ใช้ โดยบันทึก `reviewer_type=AI`, `human_confirmed=false`; ไม่ต้องรอคนเซ็น
- ใช้ Gemini/Typhoon ที่ตั้งค่าไว้แล้วภายใต้ run budget ด้านล่าง รวม calls ที่ล้มเหลวและ retries
- ใช้ cache ที่ตรวจ input/model fingerprint แล้ว การเปลี่ยนคำถาม 2 ข้อไม่ควรเรียก embedding ใหม่ครบ 498 ข้อ
- เริ่ม/ตรวจ local services ที่โครงการต้องใช้ หากทำได้ด้วยสิทธิ์ปัจจุบัน
- หากต้องเลือกค่าพารามิเตอร์ ให้เลือกรุ่นที่ง่ายและมี paired evidence ดีที่สุด บันทึกเหตุผลโดยไม่ถามผู้ใช้

### 5.2 ขอบเขตที่ต้องรักษา

- ไม่แก้ threshold/เฉลย/denominator เพื่อให้ผ่าน; เปลี่ยนเฉลยได้เมื่อมี PDF evidence พร้อม before/after และแยก version ก่อนเปรียบเทียบ
- ไม่ส่ง gold answer, gold page, question ID หรือ label-specific routing เข้า retriever/generator
- ไม่ลบฐานข้อมูล production, reset งานคนอื่น, force push, เปลี่ยน credentials/billing หรือ deploy; คำสั่งนี้ให้แก้และวัดใน local ก่อน งาน push ใช้คำสั่งผู้ใช้แยก
- ไม่ปิด quality gates เพื่อดึง raw/rejected OCR เป็นหลักฐานยืนยัน ห้ามแปลง source ที่ unresolved ให้เป็น confirmed เพียงเพราะตรงคำค้น
- ไม่เปลี่ยนโมเดล cloud ไปตัวแพงกว่าเอง และไม่ปิด offline restrictions เพื่อให้การทดสอบ local ผ่าน
- ไม่แตะไฟล์ key หรือแสดง secrets ใน output/รายงาน
- ไม่ให้หลาย process แก้ corpus/DB/run directory เดียวกันหรือแย่ง GPU ใน benchmark เวลา

### 5.3 งบเริ่มต้นสำหรับคืนแรก (ขอบเขตเสนอในแผน ไม่ใช่งบที่ผู้ใช้เคยระบุ)

ใช้ค่าต่อไปนี้เป็นค่าเริ่มต้นเมื่อผู้ใช้สั่งรันตามแผนโดยไม่ได้ให้ budget เพิ่ม:

| Resource | ขอบเขตเริ่มต้น |
|---|---|
| Cloud model attempts รวมทั้งคืน | ไม่เกิน 600 ครั้ง รวม failed/retry/OCR/judges/generation |
| Cloud input/output tokens | input ไม่เกิน 2,000,000 และ output ไม่เกิน 300,000 ที่ SDK รายงาน; ถึงข้อใดก่อนให้หยุดส่วน cloud |
| OCR ใหม่ที่มีค่าใช้จ่าย | เริ่ม 30–50 physical pages; ไม่เกิน 60 หน้าในคืนแรก ใช้เอกสารย่อยที่ได้จาก PDF จริงเพื่อทดสอบ upload และเก็บ mapping หน้าเดิม |
| Answer generation | 20 smoke → 50 paired → 100 ถ้ารุ่นนิ่ง; ขยาย 500–1,000 ตาม gate และ budget ที่เหลือ ไม่บังคับให้ครบด้วยคำถามซ้ำ |
| Retrieval | วัดครบ 498 ได้ด้วย local/cache; ไม่ต้องเรียก cloud เพื่อทุก ablation |
| Concurrency cloud | 1 ก่อน; เพิ่มไม่เกิน 2 เมื่อไม่มี rate-limit และไม่ปนกับวัด latency |
| Retry ต่อคำขอ | สูงสุด 3 attempts; backoff 30/45 วินาทีเมื่อ 429/ชั่วคราว; ห้าม retry ค่า schema เดิมวนไม่สิ้นสุด |
| Ranking experiments | สูงสุด 12 configurations ที่มีสมมติฐานชัด; เลือกไม่เกิน 3 เข้าทดสอบ production path |

เมื่อถึง budget ส่วน cloud ให้ทำ local/tests/analysis/package ต่อ และระบุว่าขาดผลใด ห้ามขยาย spending limit หรือซ่อน attempts ใช้เงินเท่าไรให้รายงานตาม billing/ราคาที่ตรวจได้จริง ถ้าไม่ทราบให้รายงาน calls/tokens และ `cost_usd=unknown` ไม่เดาตัวเงิน

ตั้ง run deadline **8 ชั่วโมงหลังเริ่ม Goal** เป็นขอบเขตปฏิบัติการคืนแรก บันทึก UTC/เวลาไทยไว้ใน run manifest ไม่ใช่คำรับประกันว่า Codex จะทำงานได้ครบ 8 ชั่วโมงเมื่อ quota หมดหรือเครื่องหยุดทำงาน

## 6. ขั้น 0 — สร้าง checkpoint และ baseline ที่เปรียบเทียบได้

1. ตรวจ branch, git status, local services, .venv และ output เดิม อ่านเฉพาะส่วนที่จำเป็น ไม่ dump JSON/PDF text ขนาดใหญ่ลงแชต
2. สร้าง run directory ใหม่, `RUN_STATE.json`, `DECISIONS.md`, `COMMANDS.log`, `NEXT_ACTION.md` และ lock ป้องกัน run ซ้อน
3. เก็บ HEAD, dirty diff, hashes ของโค้ดที่ใช้จริงและ dependency/model versions ก่อน inference; HEAD อย่างเดียวไม่เพียงพอเมื่อมี uncommitted edits
4. Snapshot `backend/services/rag.py` และ `retrieval_rank.py` ปัจจุบันเป็น baseline ของรอบนี้ ห้ามอ้างว่า baseline คือ HEAD เก่าเมื่อ code มี edits
5. ตรวจ SHA ของ PDFs และ embeddings/cache; ตรวจว่าเฉลย qid จำนวน 498 ไม่ซ้ำ และ source/page locatable
6. ใช้ isolated PostgreSQL database และ DuckDB path แยกเหมือน `benchmark_large_retrieval.py`; cleanup เฉพาะชื่อ DB ที่ process นี้สร้างและบันทึกไว้
7. รัน smoke/test ที่เกี่ยวข้อง ถ้าพังจาก environment ให้แยกจาก regression แล้วแก้เฉพาะเหตุจริง

**Exit evidence:** `run_manifest.json`, baseline code snapshot, input hashes, budget/deadline, test result และ checkpoint ที่ resume ได้

## 7. ขั้น 1 — ปิดงานเฉลยและเกณฑ์ด้วย AI PDF review

### 7.1 ตรวจ 22 กรณีที่เตรียมไว้

- เริ่มจาก `CONTRACT/offline_audit_locked` ซึ่งมี `human_review_sheet.csv`, `review_cases/<id>/original_inputs.json`, `context.txt` และภาพ PDF
- สร้างไฟล์ผล AI ใหม่ ห้ามกรอกใบมนุษย์แล้วตั้ง `human_completed=true`
- รอบ A: ตรวจ QUESTION/REFERENCE กับภาพ PDF และข้อความต้นฉบับโดยไม่ส่งคำตอบระบบ อันดับ retrieval หรือคะแนนให้ผู้ตรวจ รอบ B: เมื่อล็อก A แล้วค่อยตรวจคำตอบกับ actual context และ PDF truth แยกกัน
- เลือกดูภาพด้วยตัวเองเมื่อ native Thai text เสียรูป ตารางมี merged cells หรือ verdict ขัดแย้งกัน ใช้ skill PDF ตามความจำเป็น
- `review_ai_evaluation_packet.py` เป็น draft ที่ช่วยทำ 2 รอบได้ ตรวจ schema/resume/error-handling ก่อนใช้งาน; failed record ต้องคงไว้และ retry แบบรุ่นใหม่/มี parent hash ไม่เงียบข้ามเป็น completed
- ตัวตรวจ Gemini เป็น model family เดียวกับ generator ต้องเปิดเผยความไม่เป็นอิสระ การตรวจซ้ำด้วย Codex จากภาพช่วยตรวจทานได้ แต่ไม่อ้างว่าเทียบเท่ามนุษย์/รับประกันถูกทั้งหมด
- แยก `contradicted`, `insufficient_evidence`, `quote_unverifiable`, `supported` พร้อมเหตุผล ตรวจ claim decomposition ว่าทิ้งข้ออ้างที่สำคัญไปหรือไม่
- เก็บเกณฑ์ความครบคำตอบตรงสิ่งที่ถาม ไม่ถือว่าข้อมูลทุกบรรทัดใน PDF เป็น required answer

### 7.2 แก้สองข้อที่มีหลักฐานปัญหาแล้ว

| ID | ปัญหา | แนวแก้ที่ต้องยืนยันภาพก่อนล็อก |
|---|---|---|
| B0286 — PTT PDF หน้า 36 | 237,815 คันคือรถ NGV ทั่วประเทศไทย คำถามอาจทำให้เข้าใจว่าเป็นรถของ ปตท. | ชี้ว่า “ตามรายงาน ปตท. ปี 2567 ณ สิ้นเดือนธันวาคม 2567 จำนวนรถยนต์ใช้ NGV ทั่วประเทศ…” เก็บค่า/หน่วย/หน้าเดิม |
| B0306 — PTT PDF หน้า 40 | ตรวจภาพขยายซ้ำในรอบเริ่ม Goal แล้ว: ต้นฉบับระบุ **กบง.** ตรงกับเฉลยเดิม ข้อสรุปเดิมว่าเป็น กพช. ผิด; แนวทดลอง LNG เป็นของ กฟผ. เพดานไม่เกิน 200,000 ตัน ในปี 2562 | คง กบง.; ปรับ scope ให้ชัดว่า กฟผ. เป็นผู้ทดลอง ไม่กล่าวว่า ปตท. นำเข้า; คง comparator ≤ และแยกปีรายงาน 2567 กับปีเหตุการณ์ 2562 |

หาก 22 กรณีพบเฉลยผิดเพิ่ม ให้บันทึกหลักฐานก่อนแก้ และไม่รับหน้าทางเลือกเพียงเพราะ app ค้นเจอ ต้องรองรับทุกข้อเท็จจริงที่ถามจริง กรณีข้ามหน้า เช่น B0185 ต้องเก็บกลุ่มสองหน้าที่ใช้ร่วมกัน

### 7.3 Numeric contracts และ scorer

- ใช้ `backend/eval/contracts.py`, `numeric.py`, `comprehensive.py` เป็นฐาน
- Lock tuple: entity/company, measure/row, signed value, comparator, unit/scale, performance/event year, report year, table/header/column, physical PDF page, source SHA, evidence span/image transcript, tolerance/rounding rule
- เก็บ 101 quantity labels เป็น AI-reviewed ใน version ใหม่ ปลดการพึ่ง human-only gate ด้วย **explicit AI evaluation policy** / `allow_provisional=True` เฉพาะ run ที่ประกาศไว้ ไม่ตั้ง `human_confirmed` หรือ `official_score_eligible` ของข้อมูลเก่าให้จริง
- วันที่ เปอร์เซ็นต์ ช่วงค่า และหน่วยที่ parser ไม่รู้จักต้องมี coverage inventory; ไม่ถือว่า 101 ค่าครอบคลุมตัวเลขทั้งหมดใน 498 คำถาม
- ไม่จับเพียงเลขที่ปรากฏในคำตอบ ต้องผูกเลขกับรายการ/บริษัท/ปี/หน่วย; ไม่ยอมรับ 100 กับ -100, 100,000 หากไม่มี conversion ที่ถูก, บาทกับดอลลาร์, กำไรกับรายได้, 2566 กับ 2567, actual กับ forecast, ≤ กับ =
- Tests ที่จำเป็น: เครื่องหมาย/วงเล็บติดลบ, scale ที่แปลงได้จริง, scale ไม่ชัด, wrong row/year/company/page, bounds/ranges, rounding boundary, abstention, malformed judge output, missing actual citation mapping
- หาก scorer เปลี่ยน ให้ replay saved answers โดยไม่เปลี่ยนคำตอบ และแยกชื่อ “rescore” จาก “new generation”

**Exit evidence:** `reference_v4_locked.json`, before/after label changes, AI review ledger, numeric contracts, scorer tests, `evaluation_policy.json` ที่ระบุ human=0 และ schema ของ metrics/denominators ไม่มี silent unresolved pass

## 8. ขั้น 2 — ปรับ Retrieval จาก miss จริง และเทียบอย่างยุติธรรม

### 8.1 วินิจฉัยก่อนเปลี่ยน

สำหรับ miss ทั้ง 125 ข้อ บันทึกว่าหน้าหลักฐาน:

1. อยู่ใน corpus/index หรือไม่ และ source quality ยอมให้ใช้หรือไม่
2. หลุดเพราะ company scope, subsidiary/parent, report/year filter หรือไม่
3. อยู่ใน candidate union หรือไม่
4. ได้อันดับเท่าใดใน keyword, dense, fusion และ final page list
5. ถูก page dedup, numeric routing, section filter หรือ evidence expansion ตัดออกหรือไม่

ไฟล์หลัก: `backend/services/rag.py`, `retrieval_rank.py`, `scripts/benchmark_large_retrieval.py`, `diagnose_retrieval_ranking.py`

ข้อค้นพบเดิมที่ใช้เป็นสมมติฐาน:

- Qualitative RRF ให้ keyword weight 2.0 แต่ list keyword ยาวมาก อาจให้เครดิต weak match ที่ dense จัดไว้สูง
- Numeric route ใช้ regex ค่อนข้างกว้างและเอา lexical ก่อนทั้งหมด จึงเสี่ยงเสีย dense hit ที่ดี
- Offline cleaned/scoped keyword เคยได้ 414/500 แต่ candidate rules ต่างจาก production ต้องทำ comparison ใหม่
- B0115 ถาม PTTEP แต่หน้ารองรับอยู่ใน PTT PDF หน้า 84; cross-entity candidate patch ยังไม่ทำให้เข้า Top5
- ปีรายงาน/บริษัท/คำทั่วไปอาจครองคะแนน ส่วนข้อความภาษาไทยเสียรูปและตารางคนละ chunk เป็นปัญหาจริงอีกชั้น

### 8.2 ออกแบบ arms โดยไม่เอาผลเก่าปน

ทดลองสองระดับแยกกัน:

- **System comparison:** BM25, dense, hybrid ใช้ corpus, source-quality eligibility, query set, qrels และ retrieval depth เดียวกัน แต่แต่ละวิธีสร้างอันดับตามธรรมชาติของมัน
- **Fusion ablation:** สร้าง union ของ keyword/dense candidates ชุดเดียวแล้วเปลี่ยนเฉพาะ reranking/fusion เพื่อบอกได้ว่าผลมาจาก ranking ไม่ใช่ candidate pool ต่างกัน

เก็บ legacy unscoped BM25/dense เป็น baseline ชื่อชัดเจน อย่าเปลี่ยนความหมายชื่อเดิมเงียบ ๆ Dense vectors ต้องใช้เอกสาร/model/input เดียวกัน

### 8.3 ลำดับการทดลอง

1. Baseline code snapshot บน bank v4 ที่ล็อกแล้ว
2. Keyword ที่ normalize Thai + company-aware scope อย่างถูกต้อง; เปรียบเทียบการใช้/ลดน้ำหนัก year/report boilerplate โดยคงปีที่จำเป็นสำหรับเลือก table column
3. Union top candidates ของ keyword/dense ก่อนรวมอันดับ ใช้ candidate recall@20/50 ตรวจว่าคอขวดอยู่ก่อน ranking หรือไม่
4. Bounded RRF หรือ score/coverage-aware combination; จำกัด grid ให้มีเหตุผล ไม่ลองค่าจำนวนมากจนจำชุดคำถาม
5. ปรับ numeric routing ให้ดู intent จริงและสงวน semantic evidence ที่แข็งแรง ทดลองกับทั้ง recovered และ regressed cases
6. Company scope ที่รองรับข้อมูลบริษัทลูกในรายงานแม่ โดยไม่ให้คำย่อ ปตท. กลายเป็นตรงกับ ปตท.สผ. ทุกหน้า
7. Page aggregation และ nearby-page expansion เฉพาะเมื่อข้อความ/หัวตารางแสดงว่าต่อเนื่อง เก็บทุก page ที่ส่งและนับ retrieval budget ตามจริง ไม่ส่ง 10 หน้าแล้วเรียก Top5
8. พิจารณา local reranker เฉพาะ candidate recall ดีแต่ ranking ยังติด และเครื่องไหว ต้องวัด latency/memory/download requirements ก่อน ไม่จำเป็นต้องเปลี่ยนโมเดลหากวิธีง่ายกว่าดีกว่า

ใช้ `backend.eval.comprehensive.page_metrics` หรือ scorer รุ่นเดียวกันที่รองรับ alternate evidence sets และ multi-page requirements; script diagnostic เดิมมีส่วนที่ดู primary page อย่างเดียว ต้องแก้ก่อนใช้ตัดสิน

### 8.4 Gate รับการแก้ไข

- ทุก candidate ต้องวัดบน 498 คำถามรุ่นเดียวกันและเขียน `recovered.csv`, `regressed.csv`, `remaining_misses.csv`
- Primary: Hit@5 และ required Recall@5 ดีขึ้น; เป้าหมาย 90% Secondary: MRR/nDCG ไม่แย่ลงโดยไร้เหตุผล และไม่มี quality/provenance regression
- ตรวจทุก regression ที่เป็นตัวเลข/บริษัท/ปีผิดอย่างจริงจัง ไม่ซ่อนด้วย net score
- ถ้ามี trade-off ให้บันทึก per-category/per-company และเลือกด้วยกฎที่ประกาศก่อนดูผล ไม่เลือกตาม headline อย่างเดียว
- รันทดสอบ app `vector_search` ใน isolated DB เพื่อยืนยันว่า offline ablation ถูกนำไปใช้จริง เก็บ context output ด้วย
- ถ้าครบ 12 configurations/3 production candidates แล้วยังไม่ถึง 90% ให้เก็บรุ่นที่ดีที่สุดที่ตรวจแล้ว ระบุช่องว่าง และไปทำขั้น 3 ซึ่งอาจแก้สาเหตุด้านข้อมูล ไม่วนเพิ่ม weights อย่างไร้สมมติฐาน

**Exit evidence:** paired baseline/candidate retrieval JSON, all metrics, candidate/miss diagnoses, per-query ranking traces, production regression tests และเหตุผลเลือกวิธี

## 9. ขั้น 3 — ให้ actual context ครบและรักษาความสัมพันธ์ตาราง

1. ตรวจ `tools.py` excerpt selection และ `_expand_page_evidence` ว่าข้อมูลที่พบถูกตัดก่อนส่งโมเดลหรือไม่ เก็บ actual prompt/context ก่อน model call ไม่ใช้ returned sources แทนเมื่อทั้งสองต่างกัน
2. เลือกช่วงตอบคำถามพร้อมประโยคก่อน/หลัง ไม่เอาแต่ต้นหน้า; ลด duplicate text เพื่อคืนพื้นที่ context ให้หลักฐานจำเป็น
3. ตาราง: ส่งชื่อรายการ หัวคอลัมน์ ปี หน่วย/scale ชื่อบริษัทและ consolidated/separate statement รวมหมายเหตุและหน้าเดียวกันกับค่า หลีกเลี่ยง flatten ตารางจนเลขโยกแถว
4. สร้าง stable evidence IDs และ table-cell IDs ผูกกับ document hash, physical page และ bounding box/cell coordinates เมื่อมีจริง หากไม่มีตำแหน่งให้ระบุ `unknown` ไม่แต่งพิกัด
5. ข้ามหน้า: ตรวจหัวตาราง/ชื่อส่วนและ page continuity จากเนื้อหา เก็บ supporting pages ทั้งหมด; ปีบน report cover ไม่แทนปีในคอลัมน์
6. หาก native text เสียรูป ใช้ cached Typhoon/Gemini extraction ที่มี provenance ก่อน แล้วค่อย OCR เฉพาะหน้าที่จำเป็นภายใน budget
7. วัด context recall/precision บนคำถามเดิม โดยสลับ context policy อย่างเดียวก่อนสรุปสาเหตุการดีขึ้น

**Exit evidence:** before/after exact context, per-fact coverage, token budget/truncation log, table tuple tests และ source IDs ที่ย้อนถึง PDF ได้

## 10. ขั้น 4 — คำตอบครบและ citation ต่อข้อเท็จจริง

1. ให้ generator ส่งโครงสร้างภายใน เช่น `answer_claims[{id,text,evidence_ids}]`, `answer_text`, `unanswered_parts`; ตรวจ JSON schema แล้วค่อย render ภาษาที่อ่านง่าย
2. Evidence IDs ต้องมาจาก context ที่ส่งให้โมเดลจริง ตรวจ document/page/claim binding ก่อนแสดง เลขหน้า prose ต้องสอดคล้องกับ PDF link
3. ก่อนยืนยันตัวเลข ตรวจ tuple กับ source cell/ข้อความที่รองรับ ระบุ approximate/bound/range ตามต้นฉบับ หากยืนยันได้บางส่วนให้ตอบส่วนนั้นและชี้ส่วนที่ขาด
4. แก้ false refusals จาก verifier โดยมี regression examples: คำถามไม่มีตัวเลขกลับได้ข้อความ “ไม่พบหลักฐาน…รองรับตัวเลข”; ตรวจเส้นทาง verifier ที่พิจารณาเลขปี/เลขหัวข้อผิดเป็น financial quantity
5. ตรวจข้อมูลจริงก่อนเปิด SQL/graph tool ให้ agent; table/view ที่ไม่มีต้องไม่ถูกเสนอเป็น tool ที่พร้อมใช้
6. ตั้งงบต่อคำถามชัดเจน เริ่มจากไม่เกิน 2 evidence tool calls และไม่เกิน 3 generation/verification model calls รวม self-correction ตรวจ counter ใน code และรายงาน tool calls แยก model calls ห้ามกล่าวว่าเท่ากัน
7. อนุญาตค้นแก้ได้หนึ่งรอบภายใน budget เมื่อหลักฐานไม่ครบ; กรณี search repair ต้องเปลี่ยนคำค้นตาม missing fact ไม่ถามซ้ำเหมือนเดิม
8. ตรวจ factuality เทียบ PDF และ faithfulness เทียบ actual context แยกกัน ความ faithful ต่อ OCR ผิดยังเป็น factual error
9. คำนวณ citation precision จาก emitted links จริงเท่านั้น; source list ที่คืนแต่ไม่ได้อ้างเป็น retrieval data ส่วน citation coverage วัดทุก claim ที่ต้องการหลักฐาน

รัน 20 smoke แล้ว 50 paired คำถามเดิม ทั้ง baseline/candidate บน frozen labels และ inference inputs เท่ากัน หากมี nondeterminism ให้เก็บทุก run และตรวจ stability บน subset ที่กำหนดไว้ ห้ามเลือก best answer จากหลายครั้ง

**Exit evidence:** generated answers, canonical claims, actual citations, exact prompts, all judge outputs/errors, factual/faithfulness/relevance/recall/complete-success metrics, calls/tokens/time และ regression tests

## 11. ขั้น 5 — พิสูจน์เส้นทาง production ingestion

ใช้ **อัปโหลด → Typhoon/Gemini → จัดเก็บ → retrieval → answer → เปิด PDF reference** ใน test environment แยก

- เริ่มหน้าไทย 30–50 หน้า stratified: prose, normal/merged financial tables, chart, multi-page continuation, bad embedded text, prior failures รวมหน้า 46 หากอยู่ใน corpus ที่มี
- ใช้ upload path จริงและ scraped-PDF path จริงตรวจว่าเข้าฟังก์ชัน ingestion เดียวกันและได้ quality/provenance เหมือนกัน
- ถ้าใช้ subset PDF เพื่อประหยัด OCR ต้องเก็บ original file hash และ original↔subset page mapping; ระบุชัดว่าเป็น selected-page integration test ไม่ใช่ full-report upload
- ตรวจให้ข้อมูลใน PostgreSQL/DuckDB มี company/row/year/unit/page/source hash จริง ไม่เพียงมีคอลัมน์ว่าง ๆ
- Reingest ข้อมูลเก่าที่ขาด provenance ในฐานข้อมูลสำเนาหรือ staging ก่อน เก็บ migration manifest, row counts, evidence coverage, duplicate handling และ rollback ห้ามเติมหน้าโดยเดา
- ทดสอบ failed page, interruption/resume, idempotent re-run และป้องกัน duplicate facts
- วัด extraction/cell relationship accuracy แยกจากการค้น/ตอบ เปรียบเทียบ native-text route กับ production-extracted route บนคำถามเดียวกัน
- เปิด citation ใน UI แล้วตรวจ physical page และหลักฐานจริง บันทึก screenshot ของหน้าใช้งานจริงกับคำถาม/คำตอบที่รันได้ ไม่สร้างรูป demo แทนผลจริง
- ถ้า cached extraction เดิมไม่มี input hash/model version ให้แสดง provenance gap และรันใหม่เฉพาะส่วนจำเป็น ไม่เรียกว่า fresh controlled run

**Exit evidence:** ingestion events/page statuses, table relationship audit, old-data reingest coverage, real UI citation screenshots, stage-level latency and memory, known failures

## 12. ขั้น 6 — รายงานไทยที่ยังไม่เคยใช้พัฒนา และขยายขนาดอย่างมีหลักการ

1. สร้าง `corpus_history.json` จาก experiments/code/docs เดิม ระบุรายงานที่เคยใช้ตั้งคำถาม/แก้ระบบ/ดูคะแนนแล้ว รวมชุดเก่า 20 คำถามและ branch eval-accuracy-bge-m3
2. เลือกรายงานไทยใหม่จากเว็บไซต์บริษัท/แหล่งทางการ ตรวจภาษา ชื่อบริษัท ปี และ file hash กัน duplicate ภาษาอังกฤษหรือไฟล์เดิมเปลี่ยนชื่อ
3. แยกทั้งรายงาน และถ้าเป็นไปได้แยกบริษัท/issuer family เพื่อทดสอบ transfer; รายงานใหม่คนละปีแต่ template บริษัทเดิมให้บอกระดับ independence ตามจริง
4. สร้าง reference จาก PDF ต้นฉบับโดยไม่ใช้ extraction ที่กำลังทดสอบเป็นผู้กำหนดความจริง ตรวจคำถาม/เฉลยด้วย AI visual review และล็อกก่อน inference
5. เริ่ม 100–150 คำถามบนหลายรายงาน รวม prose, numeric tables, comparisons, multi-page, subsidiary scopes, charts ที่ตรวจได้ และ unanswerable controls ราว 10–15% ที่ยืนยันขอบเขตการไม่ตอบได้
6. “ไม่พบจาก search” อย่างเดียวไม่พอยืนยัน unanswerable ต้องตรวจ scope, year/entity และเอกสารที่ให้จริง ไม่อ้างว่าโลกภายนอกไม่มีคำตอบ
7. Lock code/model/prompt/scorer/corpus/reference hashes ก่อน final run ทุก baseline ใช้เอกสารเดียวกันและ conditions เดียวกัน รวม simple keyword, dense, simple RAG และ improved system ตาม budget
8. หลังเห็น final test แล้วห้าม tune และยังเรียกชุดเดิม unseen หากต้องแก้ให้ย้ายชุดนั้นเป็น development และหาชุดใหม่ หรือรายงาน final limitation โดยไม่แก้ซ้ำ
9. ขยายรวม 500 ก่อน แล้ว 1,000 เมื่อ schema, calibration, resource budget และ error rate พร้อม ต้องนับ unique questions และ source diversity ไม่ทำ paraphrase หลายสิบข้อจากข้อเท็จจริงเดียวเพื่อปั้น sample size
10. รายงานจำนวน retrieval questions, answer generations, claims judged, original pages และ reports แยกกัน; retrieval 500 ไม่เท่ากับ full evaluation 500

**Gate ก่อนขยาย cloud answers:** 50 paired ไม่มี pipeline/scorer systemic errors ค้าง, coverage ≥95%, citations ถูกเก็บจริง, numeric tuple ตรวจได้, ไม่มี collapse ด้าน refusals และ budget เพียงพอ หากยังไม่ถึง quality target ให้แก้ systematic issue ก่อนเพิ่มขนาด

**Exit evidence:** unseen corpus/label freeze, split and exposure history, fair baseline outputs, all applicable metrics/CI/category breakdown, limitations and leakage statement

## 13. การเก็บผลที่ต้องทำในทุกขั้น

โครงสร้างแนะนำใน run directory ใหม่:

```text
run_manifest.json          # start/deadline, code/model/inputs, thresholds, budgets
RUN_STATE.json             # stage, completed IDs, last error, next command
DECISIONS.md               # hypothesis → change → measured result → decision
COMMANDS.log               # reproducible commands, without secrets
NEXT_ACTION.md             # exact resume location and remaining blockers
baseline_code/
labels/                    # frozen references, numeric facts, AI review ledger
retrieval/<variant>/       # candidates/ranks/predictions/metrics/misses
answers/<variant>/         # response/context/claims/actual citations
judges/<variant>/          # raw inputs/outputs, validation errors, calibration
integration/               # ingestion stages, table provenance, screenshots
heldout/                   # locked corpus, labels, scores after freeze
resources/                 # model attempts, tokens, time/RSS/GPU samples
tests/                     # commands + exit codes + JUnit where useful
REPORT_th.md               # concise results and honest remaining work
METRICS.csv
SHA256_MANIFEST.json
```

- Atomic save ต่อคำถาม/หน้า; process failure ต้อง resume โดยไม่จ่ายซ้ำที่สำเร็จแล้ว ตรวจ schema และ hashes ก่อน reuse
- แยก experiment runtime จาก model-call latency, cold จาก cached, runner RSS จาก PostgreSQL/Ollama, total device GPU จาก process GPU; cloud memory ที่วัดไม่ได้ให้ N/A
- Token usage ที่ SDK ไม่คืนให้เป็น unknown ไม่เติม 0 แล้วคำนวณต่ำผิด
- เก็บ model/API errors ใน denominator ของ operational success; judge failed เป็น evaluation missing พร้อม coverage/lower bound ไม่ตีความอัตโนมัติว่าคำตอบถูกหรือผิด
- เก็บทั้ง predictions และ qrels แต่ inference function รับเพียง query/corpus/config; tests ต้องกัน accidental gold leakage
- Publish สรุปไป `REPO/docs/<new-version>/` และ raw evidence archive ไป `REPO/TestFile/<new-version>/` ตรวจ ZIP CRC/SHA และไม่รวม credentials/weights/ไฟล์ส่วนตัว
- สร้าง reproduction command ที่ตรงกับ CLI จริง ใช้ `--help` ตรวจ flags ก่อนเขียนในรายงาน ห้ามใส่คำสั่งที่ยังไม่มี implementation แล้วบอกว่ารันได้

## 14. การทดสอบโค้ดและเงื่อนไขเลือกผล

- เริ่ม `python -m pytest backend/eval/tests -q` และ tests ของ retrieval/source gates/provenance/agent ที่ถูกแก้ ตรวจ test file paths จริงก่อนเรียก
- ทดสอบ wrong-sign/scale/year/entity/measure รวม negative cases ต้องยังตก ไม่แก้ test expectations เพื่อให้ implementation ผ่าน
- Source gates: failed/quarantined/raw audit chunks ไม่กลายเป็น answer evidence; missing page/cell provenance ต้องแสดงสถานะ
- Resume/idempotency: หยุดหลังบันทึกบางรายการ เริ่มใหม่แล้วไม่ทำซ้ำผลสำเร็จ ไม่ข้าม failed item เงียบ ๆ
- ทำ paired comparison ด้วย full same-question set ทุกครั้งที่เลือก candidate สุดท้าย เก็บ regressions ไม่ใช้เฉพาะ 125 misses เป็นคะแนนรวม
- รัน performance comparison แยก process ตามลำดับภายใต้สภาวะเท่ากัน ห้าม benchmark สองรุ่นแย่ง GPU/DB แล้วสรุปความเร็ว
- เลือกผลจากกฎ frozen selection ไม่ cherry-pick seeds, answers, reports หรือ graders หาก metric definitions เปลี่ยนให้ version และ replay ทั้งสองฝั่ง

## 15. การจัดเวลาข้ามคืนและการจบ run

เวลาต่อไปนี้เป็นการจัดลำดับความสำคัญ ไม่ใช่ ETA ที่รับประกัน:

| ช่วง | งานหลัก | หากยังไม่ผ่าน |
|---|---|---|
| เริ่มต้น | checkpoint + verify baseline + step 1 AI review | แก้ labels/scorer ก่อนเผยคะแนนใหม่ |
| ช่วงแรก | retrieval diagnosis และ local ablations ครบ 498 | สรุป cause และเลือกวิธีที่ตรวจได้ดีที่สุด |
| ช่วงกลาง | context/table/answer/citation fixes + 20→50 paired | แก้ error เชิงระบบก่อนขยาย calls |
| ช่วงท้าย | production-path sample และ heldout preparation/run เท่าที่ผ่าน gates | เก็บ partial coverage และ resume manifest |
| ก่อน deadline | tests, artifacts, scorecard, morning report | แสดง blocked/not run ให้ครบ |

ถ้า API error 3 attempts ให้ checkpoint รายการนั้นแล้วไปงานที่ไม่พึ่ง API; ถ้า scoring contract ยังไม่ชัด ห้ามผลิต headline accuracy จากเกณฑ์ที่รู้อยู่แล้วว่าผิด แต่ทำ retrieval/code/diagnostics ต่อได้

หาก 3 รอบทดลองที่มีสมมติฐานต่างกันไม่เกิดผลดีที่พิสูจน์ได้ ให้หยุด tuning ชั้นนั้น เลือก best validated checkpoint แล้วแก้คอขวดชั้นถัดไป ไม่ใช้เวลาเพิ่มกับ search weights เพียงอย่างเดียว

**ผลจบ run มีได้สองแบบ:**

1. `targets_met_in_measured_scope`: มีผลจริงผ่าน targets ใน scope ที่ระบุ พร้อม tests/artifacts และข้อจำกัด diagnostic vs heldout
2. `bounded_run_finished_targets_remaining`: ทำรอบที่อนุญาตภายใต้เวลา/งบแล้ว ส่งผลดีที่สุด พร้อม gap/failed experiments/สิ่งที่ยังไม่ได้วัด และ resume commands

การจบงานของคืนแรกไม่เท่ากับประกาศ thesis-ready หรือ complete ทั้งโครงการ ถ้าใช้ Goal ให้กำหนด objective เป็นการทำ run ตามขอบเขตและส่งมอบ evidence report; ห้าม mark quality goal ว่าสำเร็จถ้า target จริงยังไม่ผ่าน

Morning report ต้องตอบให้ได้: แก้อะไร, ก่อน/หลังเท่าไรบนชุดเดียวกัน, ดีขึ้นกี่ข้อ/ถอยหลังกี่ข้อ, human review=0/AI scope อะไร, จำนวน calls/tokens/เวลา/หน่วยความจำ, ตอนนี้ถึงขั้นไหน, ขั้นต่อไปพร้อมคำสั่งอะไร

## 16. คำสั่งรับช่วงและวิธีให้ทำต่อโดยไม่ถาม

### 16.1 เลือกโมเดลแล้วเริ่ม Goal ในแชตเดิม

ผู้ใช้เลือก **GPT-6.1 Sol** ในตัวเลือกโมเดลก่อน จากนั้นส่งคำสั่งนี้เป็นข้อความใน Codex ไม่ใช่ PowerShell:

```text
/goal อ่านและลงมือทำตาม C:\Users\nonga\OneDrive\Desktop\Project_2\Agentic_RAG_Business-Insight-Analysis\docs\RAG_EVALUATION_IMPROVEMENT_PLAN_2026-10-05.md ให้ครบขอบเขต run คืนแรก ทำขั้น 0–7 ตาม dependency และ gates เพื่อเพิ่มคุณภาพ RAG ให้ใกล้ targets มากที่สุด ตัดสินใจเองโดยไม่ถามระหว่างฉันนอน ตรวจ PDF ด้วย AI ตามที่อนุญาต รักษาคะแนนเก่าและเกณฑ์เข้มงวด เก็บ checkpoints ทุกขั้น ใช้งบและ deadline 8 ชั่วโมงตามแผน เมื่อถึงขอบเขตให้จบด้วยผลที่รันจริง tests artifacts และ REPORT_th.md พร้อม NEXT_ACTION.md ถ้ายังไม่ถึง targets ให้บอกตามจริง ห้ามแต่งคะแนนหรือถือว่าการหยุดเพราะงบคือผ่านเป้าคุณภาพ
```

Goal ช่วยให้ทำต่อข้าม turns ได้ตาม stopping conditions ของแอป สามารถดูด้วย `/goal`, หยุดชั่วคราวด้วย `/goal pause` และกลับมาด้วย `/goal resume` รายละเอียดจาก [OpenAI: Using Goals in Codex](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)

ถ้า UI ไม่รับ slash command ให้พิมพ์ว่า **“สร้าง Goal และเริ่มทำตามแผนไฟล์นี้ด้วย GPT-6.1 Sol”** ในแชตที่เลือกโมเดลแล้ว Agent สามารถใช้ goal tool ที่มีให้ได้ ไม่ต้องสร้าง cron/heartbeat ซ้ำเพื่อขับงานเดียวกัน

### 16.2 ก่อนทิ้งเครื่อง

- เสียบไฟ เปิด Codex และ services ของโปรเจกต์ไว้ เปิด **Settings → General → Prevent sleep while running** หากมีในเวอร์ชันที่ใช้; ตรวจ Windows ว่าไม่ sleep/hibernate ระหว่างงาน ดู [OpenAI: Settings](https://learn.chatgpt.com/docs/reference/settings)
- ปิดหน้าจอได้โดยเครื่องยังทำงาน แต่การปิดฝา notebook อาจทำให้ sleep ตาม Windows settings
- ต้องมี internet สำหรับ Codex/Gemini/Typhoon และ quota เหลือ เป้าหมายต่อเนื่องไม่สามารถข้าม usage limit, account authentication, permission restriction หรือทำงานขณะเครื่องดับ
- Environment ปัจจุบันให้สิทธิ์รัน local commands โดยไม่ถามอนุมัติแล้ว ไม่ต้องตั้ง bypass เพิ่มเพื่อแผนนี้ การเปลี่ยน environment อาจมีข้อจำกัดต่างออกไป
- ถ้าต้องการแค่ nightly follow-up แบบตามเวลาในอนาคตจึงค่อยใช้ scheduled task; การลงมือทำงานต่อเนื่องครั้งนี้ใช้ Goal เพียงอย่างเดียว

## 17. Checklist ก่อน Sol สรุปว่าเสร็จตามขอบเขต

- [ ] ระบุสถานะ Step 1 AI review ตามจริง ไม่ติด human pending gate ที่ผู้ใช้ยกเลิกแล้ว และไม่ปลอม human certification
- [ ] เฉลย B0286/B0306 และกรณีอื่นที่พบมี evidence และ versioned change log
- [ ] เปรียบเทียบ ranking แบบ same inputs/labels/scorer มีรายการ recovered/regressed
- [ ] เก็บ exact context และ numeric relationships พร้อม provenance
- [ ] แอปส่ง actual claim→citation links ที่ตรวจได้ หรือรายงานว่ายังไม่เสร็จ/N/A
- [ ] มี generation/judge outputs, denominator, missingness และ model/resource ledger
- [ ] มี production ingestion evidence หรือแสดงว่ายังเป็น native-text diagnostic เท่านั้น
- [ ] มี report-level unseen split จริง หรือระบุว่ายังไม่มี final heldout result
- [ ] คะแนนใหม่ไม่เขียนทับคะแนนเดิม และทุก headline link ไป raw evidence ได้
- [ ] Tests ที่เกี่ยวข้องผ่าน หรือมี failure/blocker ชัดเจน
- [ ] REPORT_th.md และ NEXT_ACTION.md บอกสิ่งที่ทำต่อได้ทันที รวม artifact paths และคำสั่งที่ตรวจแล้ว

## การทำงานข้ามแชทและแยกเป้าหมาย

- เริ่มอ่าน `docs/HANDOFF_2026-10-05.md` และ `docs/goals/README.md` ก่อนดำเนินการ
- ทุกเป้าหมายใหม่สร้าง `docs/goals/YYYY-MM-DD-NN-short-name.md` จาก `GOAL_TEMPLATE.md`; การย้ายแชทเพื่อทำเป้าหมายเดิมให้ต่อไฟล์เดิม ไม่สร้างเป้าหมายซ้ำ
- แผนหลักเก็บลำดับและเกณฑ์; goal file เก็บ scope/สถานะ/acceptance/next action; run directory เก็บ raw evidence; handoff เก็บจุดรับช่วง
- อัปเดต checkpoint เมื่อจบการทดลอง เปลี่ยนวิธี พบข้อจำกัด และก่อนย้ายแชท ระบุ failed/reverted experiments ด้วย
- สถานะ completed ต้องมีหลักฐานครบ acceptance; หมดเวลา/โควตา/ย้ายแชทไม่ใช่ completed
- แชทใหม่ต้องตรวจ deadline และงบสะสมเดิมก่อน cloud calls ห้ามรันงานซ้อนกับแชทเดิม


## ผล continuation 2026-10-05T09:43:58.469687+07:00

ดู [รายงานรุ่นใหม่](rag-continuation-2026-10-05-v5/REPORT_th.md) และ [งานรับช่วง](rag-continuation-2026-10-05-v5/NEXT_ACTION.md). ตารางสถานะก่อนส่งต่อในข้อ3เป็น historicalcheckpoint. ค่า90%เดิมคือanswerrelevancy ไม่ใช่contextrelevancy; strictappnumeric/citationยังN/A. Latestbankv5แก้B0001หนึ่งข้อ;factualmacro saved20=50.17%,ไม่เปลี่ยนคำตอบหรือrawscoresเก่า. Five selectedpages andpairedcachedunitrepair validated;unseenไม่รันเพราะcoverage/capturegateยังไม่ผ่าน. QualityGoalpartial; bounded evidence delivery complete.


## Final evaluation delivery — 2026-10-07

All532 final answers and judge outcomes are saved; offline integrity/metric reproduction passed. See docs/evaluation-completion-2026-10-07/REPORT_th.md, COMPLETION_STATUS.md, METRICS.json and ARCHIVE_VERIFICATION.json. Approximate full-plan workflow completion90–95%; quality objective remains partial. This is native-report transfer with disclosed technical-repair exposure, not pristine never-exposed questions or certified full-report OCR. Interrupted accounting is preserved as lower bounds, not reset. No500–1000 expansion while quality gates fail. Next actions/commands are recorded in that report directory.


## User-approved A/B/C chat grouping — 2026-10-08

Latest controlling chat plan: docs/EVALUATION_CHAT_ROADMAP_2026-10-08.md. A=Stage2+4 (numeric/capture and context/table), B=Stage3+5 (retrieval and real ingestion acceptance), C=Stage6+7 (new-report final evaluation and delivery). This supersedes earlier one-chat-per-stage transfer instructions; original Astra steps/targets and cumulative resource accounting remain intact. User authorized starting a new chat for A now. Use the existing goal, preserve the dirty checkout and old evidence, and do not launch B/C before their dependencies/gates.
