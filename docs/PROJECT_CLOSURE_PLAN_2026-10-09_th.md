# แผนปิดจบโปรเจกต์: Thai Business Report RAG

วันที่อัปเดต: **9 ตุลาคม 2026**
ช่วงสอบที่ผู้ใช้แจ้ง: **8–11 พฤศจิกายน 2026**
เป้าหมายเตรียมผลงานพร้อมใช้: **6 พฤศจิกายน 2026** พร้อมเวลาซ้อมและสำรองก่อนวันสอบแรก

แผนนี้เป็นแผนหลักล่าสุด ใช้แทนลำดับงานเดิมเมื่อขัดกัน **ตัด Docling และการพัฒนา OCR/LLM แบบ fully offline ออกจากขอบเขตปิดจบ** เก็บโค้ดและผลเก่าไว้เป็นประวัติ ไม่ต้องลบหรือทดลองส่วนนี้ต่อ Knowledge Graph และ Tavily ไม่เป็นเงื่อนไขจบงาน และจะไม่เพิ่มเป็นงานหลักเพียงเพื่อให้ตรงแผนภาพ

ผู้ใช้ต้องการผล evaluation ที่ดี ระบบเสถียรและน่าเชื่อถือ พร้อมทดสอบ PDF ไทยที่ไม่เคยใช้พัฒนา และนำเสนอข้อดีเฉพาะทางของโปรเจกต์ การเทียบตลาดเป็น **desk research จากข้อมูลทางการ** ไม่ซื้อ subscription ไม่ทำ benchmark กับบริการคู่แข่งหลายรอบ ไม่ต้องรอมีบัญชีคู่แข่งก่อนเริ่มงาน

## 1. Story ที่จะใช้เล่า

### ผู้ใช้เป้าหมาย

ผู้ช่วยนักวิเคราะห์หรือนักวิจัยธุรกิจไทยที่ต้องอ่านรายงานบริษัทเป็นประจำ มีเอกสารของตนเอง ต้องค้นตัวเลขและคำอธิบายซ้ำ และต้องย้อนตรวจหลักฐานก่อนนำข้อมูลไปเขียนรายงาน ผู้ใช้งานหลักของ prototype เป็นผู้ใช้หนึ่งคนหรือผู้ปฏิบัติงานหนึ่งคนในทีมเล็ก ยังไม่อ้างว่าเป็นระบบหลายผู้ใช้ระดับองค์กร

### Use case หลัก

ผู้ใช้รวบรวมรายงานบริษัทไทยหลายฉบับ เตรียมข้อมูลครั้งหนึ่ง แล้วถามเรื่องรายได้ สินทรัพย์ ปี หน่วย หรือแนวทางด้าน ESG จากนั้นเปิดหน้า PDF เพื่อเช็กคำตอบได้ การนำข้อมูลเดิมกลับมาใช้ซ้ำช่วยให้วัดต้นทุนการเพิ่มเอกสารแยกจากต้นทุนการถามได้

### Motivation และจุดขาย

ข้อความหลักที่เสนอให้ใช้:

> A purpose-built assistant for Thai business reports, with numerical context, traceable PDF evidence, and controlled operating costs.

จุดขายเชิงบวกที่ต้องพัฒนาและมีหลักฐานรองรับ:

- เจาะจง workflow ของรายงานธุรกิจไทยและข้อมูลตาราง มากกว่าการเป็นแชตสำหรับงานทั่วไป
- เก็บบริษัท รายการ ปี หน่วย แถว/คอลัมน์ และ physical PDF page เป็นข้อมูลที่ตรวจย้อนกลับได้
- มีการเตรียมข้อมูลตารางสำหรับ SQL และค้นข้อความตามชื่อรายการร่วมกับ semantic search
- ผู้พัฒนาตรวจ raw OCR ข้อมูลที่เก็บจริง และสาเหตุของหน้าที่ผิดได้
- เก็บข้อมูลและ embeddings ในเครื่อง และใช้ข้อมูลเดิมซ้ำเพื่อลดงานประมวลผลซ้ำ
- มีบันทึกการทดลองและต้นทุนต่อขั้นตอน ทำให้การอ้างคุณภาพและราคามีหลักฐาน

ข้อเหล่านี้เป็นจุดเน้นของการออกแบบ บางข้อยังต้องพิสูจน์ผ่านการทดลองสุดท้าย การเขียนว่าเฉพาะทางไม่ได้ยืนยันว่าแม่นกว่าทุกผลิตภัณฑ์

### คำว่า local และราคาถูก

Frontend, backend, ฐานข้อมูล และ embeddings ทำในเครื่อง แต่เส้นทางหลักยังใช้ **Typhoon prose OCR + Gemini table extraction + Gemini generation** จึงระบุว่าเป็นแอปที่ติดตั้งในเครื่องและใช้บริการ AI ออนไลน์ ไม่อ้างว่าเป็น fully offline หรือเก็บข้อมูลทุกขั้นตอนในเครื่อง

การชูราคาถูกต้องใช้ข้อความแบบมีเงื่อนไข เช่น “ต้นทุนต่ำสำหรับการใช้งาน N คำถามกับรายงานที่เตรียมไว้แล้ว” หลังวัดจริง ไม่ตั้งข้อสรุปล่วงหน้าว่าถูกกว่า Claude หรือทุกบริการ เพราะตลาดมี free plans และ subscription มีความสามารถอื่นรวมอยู่ด้วย

## 2. Feedback อาจารย์จะตอบด้วยหลักฐานอะไร

| คำแนะนำ | สิ่งที่จะส่ง | หลักฐานที่ใช้ |
|---|---|---|
| มีเรื่องเล่าและผู้ใช้ชัด | Story/use-case หนึ่งหน้า | Persona และงานที่ prototype รองรับ |
| ทำไมเลือกแอปเรา | ตารางจุดเด่นเฉพาะทาง | โค้ด ฟีเจอร์ที่ทดสอบ และ demo |
| ราคาถูกกว่าหรือไม่ | Cost table และกราฟ workload | Usage ที่วัดจริง + ราคาทางการ |
| ต้องมี baseline | เปรียบเทียบ full app กับ simple RAG | ข้อมูล/คำถาม/โมเดล/เกณฑ์ร่วมกัน |
| 80% ต้องมี context | ผลแยกตามโจทย์และรายงาน | Denominator, baseline, scope และ unknown |
| ต้อง survey ตลาด | ตาราง Claude, ChatGPT และ Google notebook product | เอกสารทางการพร้อมวันที่ ไม่อ้างผลทดลองตลาด |
| โฟกัส experiment ตาม story | ชุด QA รายงานธุรกิจไทยใหม่ | ตัวเลข ตาราง ปี หน่วย และ citation เป็นโจทย์สำคัญ |

## 3. ฐานปัจจุบันที่ต้องรักษา

- ผล development เดิมครบ **498 ข้อ** มีแปด conservative RAG scores **85.96–96.69%** เป็น AI provisional ไม่ใช่ unseen result
- Complete-answer baseline **302/498 = 60.64%**, unresolved 59
- Strict numerical baseline **18/102 = 17.65%**, unresolved 15 ความสัมพันธ์ จาก 94 คำถามตัวเลข
- ผล full498 เป็นของ frozen capture **v1.16** โค้ดปัจจุบันเป็น **v1.22** ยังไม่มี full498 live score ใหม่ของ v1.22
- Candidate98 v1.21 ไม่ถูกเลือก: numerical 17/102 เทียบ baseline18/102 และมี regression4
- selected OCR cells123/169→166/169 และ actual isolated ingestion32หน้า เป็นหลักฐาน development คนละขอบเขตกับ full-report unseen OCR
- ชุดโค้ดล่าสุดที่บันทึกไว้470passed/5skipped ไม่ใช่คะแนนตอบถูก และ skipped live DB tests ต้องไม่แสดงว่าได้ทดสอบจริงแล้ว
- Global resource ledger: `TestFile/evaluation_completion_2026-10-07/resource_ledger.json` ไม่ reset และไม่ใช้ยอดสะสมของการวิจัยเป็นค่าใช้แอปต่อเดือน
- ห้ามแสดงคะแนนบนชุดใหม่เป็น improvement จากชุดเก่าโดยตรง เพราะข้อมูลและความยากต่างกัน

ผล transfer133 ของ Bangchak/WHAUP/CPN วันที่7ตุลาคมมีการรันและดูผลแล้ว แม้ชื่อไฟล์/manifest เก่าเรียก final/unseen ก็ต้องถือว่าเป็น **exposed historical evaluation** สำหรับงานปิดจบครั้งนี้ ห้ามนำกลับมาประกาศว่าไม่เคยเห็น

## 4. ขอบเขตที่จะทำและไม่ทำ

**ทำ:** story, market survey, cost instrumentation, calibration ของ reference/เกณฑ์, เสถียรภาพ API/ingestion/query, actual SQL/vector tool traces, fresh full-PDF ingestion, unseen evaluation498, technical baseline, รายงาน/สไลด์/demo/reproducibility package

**ไม่ทำ:** Docling, เปรียบเทียบ local LLM หลายรุ่น, เพิ่ม KG เป็นโครงการใหม่, ซื้อ Claude/ChatGPT/Google subscriptions, ทดลองคู่แข่งแบบ paid benchmark, fine-tuning, การเพิ่มฟีเจอร์ทั่วไปที่ไม่เกี่ยวกับ story, production deployment โดยไม่ได้รับคำสั่ง

PDF ใหม่เก็บในพื้นที่ downloads ที่ git-ignore และใช้ database/warehouse ทดลองแยก ไม่แก้หรือ reset ฐานข้อมูล production

## 5. ชุดการทดลองขั้นต่ำที่มีเหตุผล

### Experiment A: ความสามารถเฉพาะทางและ reference calibration

ใช้ development cases เดิมแยกสาเหตุ: OCR ผิด, retrieval/context หาย, source page ไม่ครบ, wrong entity/year/unit, missing annotation หรือข้อกำหนดอ้างอิงกำกวม แก้ที่ต้นเหตุและใช้ regression controls ไม่ทดลองแก้ prompt ซ้ำโดยไม่มีสมมติฐานใหม่

ตรวจคำถามตัวเลข94ข้อและ102ความสัมพันธ์จาก original PDFs โดยใช้ source-review packet ที่เตรียมไว้ ผู้ตรวจ reference ไม่เห็นคำตอบของแอปในขั้นตั้งข้อกำหนด แยก expected reference ออกจาก original PDF evidence เพื่อไม่ใช้ข้อความในเฉลยเป็น proof ว่า quote อยู่ใน PDF

ก่อน final run ต้องตกลงและล็อกวิธีตรวจ identity ที่มีความหมาย เช่น parent/subsidiary, consolidated/separate, actual/target และ event/report year ต้องแยกกัน คำที่หมายถึง entity/measure เดียวกันยอมรับได้เมื่อมี source proof ไม่ใช้ aliases ที่แต่งตามคำตอบแอป

หากแก้ reference/scorer อย่างมีเหตุผล ให้ version ใหม่ เก็บ old strict scores และวัด baseline/candidate ที่เกี่ยวข้องด้วยวิธีเดียวกัน ต้องล็อกเกณฑ์ก่อนเห็นคำตอบ final unseen ห้ามเปลี่ยนเกณฑ์หลังรู้ผลเพื่อให้ผ่าน

### Experiment B: สถาปัตยกรรมที่เลือกใช้จริงเทียบ simple RAG

ระบบหลัก **S1: Full app** ใช้ OCR/corpus ใหม่, lexical-first, SQL/vector routing ตามข้อมูลที่พร้อม และ citation capture

Baseline **S0: Simple dense RAG** ใช้ OCR/corpus เดียวกัน, bge-m3 retrieval หนึ่งรอบ, Gemini model เดียวกัน, final-answer format/prompt และ context budget เดียวกัน โดยไม่มี agent routing/SQL/search repair

ให้ทั้งสองระบบใช้คำถามครบ498และcontrolsชุดเดียวกัน มีค่าตั้ง generation และ validators ที่ล็อกไว้ baseline ไม่ถูกลด context หรือให้ prompt ที่เสียเปรียบ การเปรียบเทียบนี้เป็น **system comparison** ไม่ใช่ ablation ของ lexical ranking เพียงตัวเดียว

วัด retrieval-only BM25/dense/lexical บนคำถามชุดเดียวกันได้โดยใช้ embeddings/cache เดิม เป็นการทดลองเสริมที่ไม่ต้องสร้างคำตอบอีกหลายชุด

ไม่จำเป็นต้องรัน baselineสี่หรือห้าระบบเต็มชุด หากไม่มีสมมติฐานเฉพาะใหม่ โฟกัส full app กับ simple RAG เป็นหลัก

### Experiment C: PDF ไทยที่ไม่เคยใช้พัฒนา

1. สร้าง seen-document registry จาก **ทุกการทดลองเดิม** ด้วย PDF hashes, URLs, filenames, issuers และ issuer families รวมทั้ง metadata ของ final133
2. ใช้ existing scraper/PDF discovery ค้นจากเว็บไซต์ผู้เผยแพร่ทางการอย่างน้อย6 candidates เลือก4รายงานและ2สำรองตามเกณฑ์ที่ล็อกไว้ก่อนดู system answers
3. เลือกรายงานภาษาไทยจาก issuer families ที่ไม่เคยใช้ tune/evaluate ตรวจภาษาในหลายส่วน ไม่ดูเฉพาะปก ต้องมีทั้ง prose และตารางที่เกี่ยวกับ story
4. บันทึก blocked/download failures และเหตุผลตัดออก ไม่หลบ robots/CAPTCHA และไม่เลือกแทนภายหลังเพราะระบบทำคะแนนต่ำ
5. แยก calibration reports ที่อนุญาตให้ tune ออกจาก final held-out reports รายงานใดถูกใช้แก้ระบบแล้วจะไม่กลับมาเป็น final unseen
6. ใช้ **fresh ingestion ของทั้ง PDF ที่เลือก** ผ่านเส้นทางจริง เก็บ per-page OCR/status/quality metadata ไม่เรียก prepared native text ว่าเป็น fresh OCR
7. สร้าง **498 answerable questions** ที่เป็นข้อเท็จจริงต่างกันและมีหลักฐาน original PDF ไม่เพิ่มจำนวนด้วย paraphrases จำนวนมาก
8. การจัดหมวดเริ่มต้นที่เสนอ:200 numerical lookups,100 comparisons/multiple-fact questions,198 narrative/policy/ESG/governance รวม498 ปรับตาม source coverage ได้ก่อน freeze แต่บันทึกเหตุผลและไม่ปรับตาม system scores
9. เพิ่ม **32 unanswerable/unsupported controls** แยกจาก498หลัก เพื่อวัด false assertions และการปฏิเสธให้เหมาะสม รวม530 outcomesต่อระบบ
10. Balance report coverageประมาณ124–125คำถามต่อรายงาน พร้อมกระจายหน้า/ตาราง ไม่ให้หลายร้อยข้ออยู่บนไม่กี่หน้า เก็บ clustering metadata สำหรับ analysis
11. Freeze bank, reference, source pages, numeric requirements, code, config, scorer, analysis protocol และ baseline conditions ก่อน generation
12. รัน S0/S1ครบทุกข้อ เก็บ first outcomes, errors, refusals และ partial records ไม่เลือกคำตอบดีที่สุดจากหลายรอบ

โค้ดปัจจุบันต้องมี populated DuckDB ในเส้นทาง S1 จึงจะพิสูจน์ SQL/vector routing ได้ เก็บ actual tool traces และจำนวนคำถามต่อ tool ไม่บังคับเรียกเครื่องมือเพื่อสร้างตัวเลขสวย และไม่อ้างว่าได้ใช้ทุก tool เพราะมีในregistry

คำว่าunseenหมายถึงไม่เคยใช้รายงานนั้นปรับหรือประเมินระบบของโครงการ ไม่สามารถรับรองว่าโมเดลfoundationไม่เคยเห็นรายงานสาธารณะระหว่างpretrainingได้

หากจำเป็นต้องแก้ระบบหลังเห็นผล final ให้ถือชุดนั้น exposed และเก็บผลครั้งแรกไว้ การทดสอบ finalใหม่ต้องแยก source/questions ที่ไม่เคยใช้แก้ ไม่ rewrite manifest ให้ดูเหมือนไม่เคยเห็น

### Experiment D: ราคาและต้นทุนที่ผูกกับ story

เก็บต้นทุนใหม่แยกจากค่าการวิจัยสะสม:

- Discovery/download
- Typhoon prose OCR และ Gemini tables
- Chunking/embedding/indexing ในเครื่อง
- Agent planning, SQL selection/generation, final generation และ corrective calls
- Retries/failed requests ที่ทราบ usage และส่วนที่ยัง unknown
- Evaluation/judging เป็น **research cost** แยกจากการใช้งานแอปของผู้ใช้

ใช้ usage metadata จริง และราคาของ endpoint/SKU/tierที่ใช้จริง Gemini output billing รวม reasoning ต้องนับครั้งเดียว Global meter ปัจจุบันรวม candidates+thinkingในknown_outputแล้ว จึงห้ามบวกthoughtsซ้ำ เก็บcached input,credits,free tier,tax และunknownแยก

Typhoon pageทางการระบุ free hosted OCR tier แต่ต้องยืนยันตรงกับ endpoint/accountที่ใช้จริง ไม่ใช้ fieldชื่อpaid_ocr_pagesเป็นหลักฐานว่ามีค่าใช้จ่ายเงินจริง และไม่ใช้ cloud GPU self-host benchmarkของผู้ให้บริการแทน hosted API tariff

รายงานทั้ง:

- API cash cost ที่มีหลักฐานหรือ estimate ตามusageที่วัด พร้อมราคา/วันที่
- Costต่อหน้าและต่อรายงานที่เตรียมข้อมูล
- Marginal costต่อคำถามหลังเตรียมข้อมูลแล้ว
- Costต่อคำตอบที่ผ่าน factual/source criteria เพื่อไม่ให้งานราคาถูกแต่ตอบผิดดูดี
- Local compute: ระบุhardware เวลา RSS/VRAMที่วัดได้ และค่าไฟ/ค่าเสื่อมเป็นsensitivity ถ้าไม่ได้วัดให้N/A ไม่ใส่ศูนย์

สูตรสำหรับหนึ่งเดือน:

`C_month = C_new_document_ingestion + Q × C_query + C_local_compute + C_storage/maintenance`

แยก first month กับ reuse month และcold/warm conditions ตัวอย่างworkloadเพื่อวิเคราะห์ ไม่ใช่ข้อมูลสำรวจผู้ใช้จริง:50,200,1000คำถาม/เดือน และ0,1,4รายงานใหม่/เดือน ใช้ขนาด PDF ที่วัดจริง

เทียบกับค่ารายเดือนทางการของpaid plansและรวมfree alternativesด้วย ไม่เอาAPIราคาtokenไปเรียกว่าClaude Pro/ChatGPT Plus subscription cost และไม่ซื้อบริการมาทดสอบ

หาbreak-evenด้วยusage profileที่วัด และรายงานว่าในscenarioใดเราอาจถูกกว่า/แพงกว่า หากunknown costมีนัยสำคัญ ต้องแสดงช่วงหรือสถานะestimated ไม่อ้างตัวเลขจ่ายจริง

### Experiment E: ความเสถียร

ทำactual isolated API testsด้วยเอกสาร/ข้อมูลที่เตรียมไว้:

- Uploadผ่านAPI, รอprocessing, query, เปิดphysicalPDFpage
- Restartระหว่างingestionและทำต่อจากcheckpoint ตรวจไม่ซ้ำ/ไม่หาย
- Re-ingestion/idempotency และrollbackเฉพาะowned test data
- ทดสอบqueryขณะมีงานingestion และการเรียกพร้อมกันในขอบเขตsingle-instanceที่ประกาศ
- Provider timeout/429/empty response ด้วยcontrolled fault tests ให้แสดงผลตรงไปตรงมา ไม่สร้างคำตอบขึ้นมา
- วัดcompletion/error rates, timeouts, p50/p95 latency, RSS/VRAMที่มีเครื่องมือรองรับ พร้อมsample sizes
- ระบุจำนวนretriesแยกจากsuccess และruntimeที่รวมpacing/cache เงื่อนไขทดสอบต้องเทียบกันได้

เป้าหมายtechnical stabilityที่เสนอให้ล็อกก่อนรัน:ไม่มีdata loss/source-page corruptionในrecovery tests,ไม่มีduplicate rowsในidempotency,technical completionอย่างน้อย99%บนquery cohortที่กำหนด Refusalและwrong answerแยกจากtechnical errors ไม่ใช้การไม่มีexceptionเป็นaccuracy

## 6. Market Survey: เปรียบเทียบเชิงบวกโดยมีหลักฐาน

ให้surveyอย่างน้อยClaude Pro,ChatGPT Plus และNotebookLM/Google notebook productทั้งfree/paidจากแหล่งทางการ โดยยืนยันชื่อผลิตภัณฑ์/planล่าสุด แหล่งข้อมูลGoogleปัจจุบันบางหน้าระบุGemini Notebookและlimitsเปลี่ยนไป ไม่คัดลอกquotaจากเอกสารเก่าอัตโนมัติ

ตารางsurveyต้องมี:กลุ่มผู้ใช้/task,PDFและsource-grounded QA,การอ้างอิง,custom instructions/projects,workflowตาราง/ข้อมูลปีหน่วย,การเก็บ/ตรวจOCR,observability/reproducibility,cost model,limits,source URL,date และevidence status

ใช้สถานะ **documented / designed in our code / tested in our app / not documented / not evaluated** คำว่าnot documentedไม่แปลว่าคู่แข่งทำไม่ได้

ไม่เขียนว่าแอปตลาดมีแต่general knowledge:หลายบริการรับเอกสารผู้ใช้และมีcustom context/source citationsได้ จุดต่างที่ชูคือworkflowเฉพาะรายงานธุรกิจไทยและความโปร่งใสของpipelineเรา ไม่ใช่อ้างความสามารถที่คู่แข่งไม่มีโดยไม่ตรวจ

ไม่สร้างmarket accuracy80%ขึ้นเอง ไม่มีการทดลองตลาด จึงไม่จัดอันดับqualityว่าเหนือกว่าClaude/ChatGPT/NotebookLM แผนนี้ใช้ **market feature/price survey + measured technical baselineของเรา** เป็นหลักฐานคนละประเภท

ข้อมูลเริ่มต้นจากการตรวจวันที่9ตุลาคมอยู่ที่ [Market Survey Seed](MARKET_SURVEY_SEED_2026-10-09.md) ต้องrefreshราคา/เงื่อนไขก่อนส่งรายงานและเก็บsnapshotของข้ออ้างที่ใช้จริง

## 7. Metrics และวิธีรายงาน

บน498answerableหลักให้รายงานแปดRAG metrics พร้อมassessableN,missing/N/A และconservative full-set denominator498 เป้าใช้งานยังมากกว่า80% ไม่ย้ายตัวหารเป็นเฉพาะข้อที่ง่าย

รายงานเพิ่มเติม:source-supported numerical correctness,complete numerical relationships,complete-answer success,retrieval hit/required-evidence recall,false-refusal,claim/citation errors แยกnumerical lookup/comparison/narrativeและรายงานแต่ละฉบับ

แยกcontrols32ข้อ:correct abstention,false factual assertions และtechnical errors ไม่ปนกับ498หลักแล้วเรียกpercentเดียว

รายงานbaseline deltaเฉพาะmatched data/criteria ใช้paired analysisและsource-page/report clusteringเพื่ออธิบายuncertainty จำนวน4รายงานยังจำกัดgeneralization ไม่เรียกconservative aggregationว่าstatistical confidence interval

ตรวจcalibrationของAI judgeด้วยoriginal source proofsและstratified audit across systems/categories สามารถทำsource reviewด้วยAIได้เมื่อไม่มีhuman แต่ต้องระบุAI-assisted ไม่อ้างhuman confirmation หากได้ผู้ตรวจอิสระให้ทำก่อนsubmissionโดยไม่ขวางงานที่ดำเนินต่อได้

เป้าหมายqualityไม่ใช่คำรับประกัน ถ้าผลยังต่ำ ให้บอกfailure categoriesและขอบเขตที่รองรับจริง ห้ามmarkว่าทุกเกณฑ์ผ่านหรือปิดquality goalเพียงเพราะกำลังถึงวันสอบ

## 8. ลำดับงานและปฏิทิน

| ช่วง | งานหลัก | Deliverables และ dependency |
|---|---|---|
| **9–12 ต.ค.** | P0 Story, market desk research, seen registry, cost/integrity preflight | STORY.md, MARKET_SURVEY.md, SEEN_DOCUMENTS.json, EXPERIMENT_PROTOCOL_DRAFT.md, initialRUN_STATE;ยังไม่รันfinalanswers |
| **13–20 ต.ค.** | P1 Dev/reference calibration, targeted repairs, stability/cost instrumentation,หาและคัดPDFใหม่ | Failure inventory,versionedcalibration,actualAPIchecks,newPDFmanifest;แยกcalibrationกับheldout |
| **21–29 ต.ค.** | P2 Freshfullingestion,blind498+32bank,freezeและรันS0/S1 | Frozenmanifest,530outcomesต่อระบบ,rawcalls,source/citationaudit;costinstrumentationต้องพร้อมก่อนcloudwork |
| **30 ต.ค.–4 พ.ย.** | P3 Analysis,costscenarios,claim-evidence matrix,Englishreport | Resultsbytask/report,matchedbaseline,costbreak-even,limitations;แก้coreเฉพาะมีเหตุผลและเก็บfirstfinalผลไว้ |
| **5–6 พ.ย.** | P4 Finalpackage,slides,Thaiscript,demoและrehearsal | Code/configตรงrun,Englishslides/report,Thaiscript,Q&A,recordeddemo,fallback,resumecommands/checksums |
| **7 พ.ย.** | Bufferและซ้อม | เช็กลิงก์source/demo/servicesและความเข้าใจของผู้นำเสนอ หลีกเลี่ยงfeatureใหม่ที่ยังไม่ได้ประเมิน |
| **8–11 พ.ย.** | ช่วงสอบ | นำเสนอข้ออ้างตามผลที่มีจริง |

วันในตารางเป็นworking scheduleตามช่วงสอบที่ผู้ใช้แจ้ง ไม่ใช่APIharddeadlineหรือbudgetใหม่ ถ้าติดข้อมูล/บริการให้ดำเนินงานที่ไม่ขึ้นกับสิ่งนั้นต่อและรายงานผลกระทบ ไม่หยุดทั้งโครงการ

## 9. นิยามปิดงานเพื่อส่งสอบ

- Storyระบุผู้ใช้ งาน และเหตุผลเลือกแอปในหนึ่งหน้า พร้อมข้อดีเฉพาะทางที่มีหลักฐาน
- Market surveyมีofficialsourcesและวันตรวจ ไม่มีการอ้างว่าทดสอบคู่แข่งหรือถูกกว่าทุกfreeplan
- มีmatchedtechnicalbaselineบนชุดที่ล็อกครบ ไม่ใช้คะแนนตลาดที่ไม่มีข้อมูล
- PDFfinalไม่เคยใช้tune/evaluate มีseen-registry/sourcehash/issuer-familychecks และfreshingestionที่เปิดเผยfailedpages
- Finalbank498+controlsมีcoverage/referencesล็อกก่อนanswers และเก็บทุกoutcome
- รุ่นโค้ดที่จะส่งตรงกับรุ่นที่ประเมินและมีrun/config/artifacthashes
- มีactualAPI/source-opening/recovery/idempotency/faultresultsตามscope ไม่ใช้unit testsแทนruntimeevidence
- ต้นทุนแยกresearchจากoperation รวมOCR/retries/computeตามข้อมูลที่ทราบ และระบุunknown
- ข้ออ้างด้านราคา/คุณภาพทุกข้อมีcontext workload/source บรรยายข้อจำกัดครบ
- Englishreport/slidesและThaiscript/Q&Aสอดคล้องกัน พร้อมdemobackupและผู้นำเสนออธิบายtool/dataflowได้

การส่งผลงานและการบรรลุทุกqualitytargetเป็นคนละสถานะ ถ้ายังไม่ผ่านต้องเก็บqualitygoalว่าunmetและตกลงscopeกับอาจารย์ตามหลักฐาน ไม่แก้ตัวเลขเพื่อให้ดูจบ

## 10. วิธีรับช่วงและเริ่มงานทันที

อ่านแผนนี้กับ [policyล่าสุด](PROJECT_CLOSURE_POLICY_2026-10-09.json) และ [market seed](MARKET_SURVEY_SEED_2026-10-09.md) ก่อน ส่วนเอกสาร8ตุลาคมเก็บเป็นhistorical/development evidence

ใช้branch `auto1` และworkspaceเดิม ตรวจAGENTS.mdถ้ามี รักษาuntracked `tmp/` และงานของแชทสไลด์ ไม่เปิดownerทดลองพร้อมกันหลายแชท ไม่spawnsubagentsจากการอนุมานคำสั่งนี้

Outputใหม่: `TestFile/project_closure_2026-10-09/` ซึ่งเป็นlocal workspace แยกจากประวัติ8ตุลาคม SourcePDFsใช้ignoreddownloads เก็บgloballedgerเดิม ไม่resetต้นทุนหรือtokens ไม่มีงบGemini/deadlineที่แต่งขึ้นจากคำว่าประหยัดCodex

**งานแรกของแชทใหม่:** preflightแบบread-only,claimownershipหลังhandoff,ทำstory/claim-evidence matrix,marketdesk surveyต่อจากseed,สร้างseenregistryและcostmeasurementgaplist แล้วเริ่มtargetedcalibration/ingestionตามdependency ไม่จบที่การเสนอแผนอีกครั้ง

ไม่ซื้อบริการและไม่รันmarketbenchmarkตามคำสั่งล่าสุด Gemini/Typhoonที่มีอยู่ใช้สำหรับการทดลองระบบของเราได้ตามความจำเป็น เก็บ usageครบและไม่dumpcredentials การไม่มีบัญชีคู่แข่งไม่ใช่blockerของแผนนี้

Historical rawanswers,gold/scorer versions,failedattempts,candidatesและarchivesทั้งหมดต้องคงไว้ ไม่resume frozenrunด้วยcodeที่เปลี่ยน ไม่ทับคำตอบด้วยgold ไม่retry known-wrong outcomeจนเลือกคำตอบผ่าน

## 11. ไฟล์ตั้งต้นที่ควรใช้

- `docs/GEMINI_RAG_FULL498_REPORT_2026-10-08.md`
- `TestFile/published_2026-10-08/metrics498.json`
- `TestFile/published_2026-10-08/numeric_diagnosis102.json`
- `TestFile/published_2026-10-08/candidate98_comparison.json`
- `TestFile/evaluation_B_2026-10-08/recovery_root_2026-10-08/numeric_reference_blind_review_v1/`
- `docs/evaluation-completion-2026-10-07/REPORT_th.md` เพื่อกันนำfinal133กลับเป็นunseen
- `docs/pdf-discovery.md`, `backend/services/pdf_discovery.py`
- `scripts/run_capture_paired.py`, `scripts/audit_capture_run.py`, `scripts/bounded_cloud_meter.py`
- `backend/services/agent.py`, `tools.py`, `rag.py`, `answer_capture.py`, `duckdb_warehouse.py`, `document_jobs.py`

เก็บconfiguration/codeตรวจปัจจุบันและเลือกรุ่นหลังdevcalibration ไม่รับช่วงแล้วอ้างว่าต้องใช้v1.22ตลอดโดยไม่มีregressioncheck การสำรวจข้อมูลหรืออ่านPDFเพื่อทำlabelsไม่เท่ากับการใช้ข้อมูลนั้นtuneระบบ แต่ต้องบันทึกexposureแยกทุกชนิด

## 12. งานส่งสอบเพิ่มเติมตามคำสั่งผู้ใช้ 9 ตุลาคม 2026

หลังรัน S0/S1 และวิเคราะห์/ตรวจหลักฐานผลเสร็จ ให้จัดทำ **รายงานฉบับขอสอบ** และ **โปสเตอร์โครงงาน** เป็น deliverables หลักของ P3/P4 ภายในเป้าหมาย 6 พฤศจิกายน ไม่จบเพียงเอกสารสรุปผลหรือสไลด์

- รายงานอิงรูปแบบและคุณภาพการจัดหน้าจาก `C:/Users/nonga/Downloads/นอกจากรายงานฉบับขอสอบ ทำ poster ด้วย/รายงานฉบับขอสอบ (Final report)-1658-0.pdf` ซึ่งตรวจแล้วมี 27 หน้า ขนาด Letter 612×792 pt: ปกพร้อมตราสถาบัน สารบัญ สารบัญตาราง/รูป บทคัดย่อ กิตติกรรมประกาศ บทที่ 1–5 บรรณานุกรม และประวัติผู้จัดทำ ใช้รูปแบบนี้เป็นต้นแบบการจัดหน้า ไม่ใช้ผลทดลอง/สถาปัตยกรรมเก่าในไฟล์แทนผลล่าสุด
- คงชื่อสมาชิก รหัสนักศึกษา อาจารย์ที่ปรึกษา สถาบัน คณะ สาขา อีเมล และข้อมูลระบุตัวบุคคลตามต้นฉบับทุกประการ ตรวจเทียบหน้า 1 และ 27 แบบ visual ก่อนส่ง ไม่แต่งหรือแปลชื่อเป็นอักษรโรมันเอง คงชื่อโครงงานทางการและข้อมูลการศึกษาเดิมตามคำสั่ง “ทุกอย่างเหมือนเดิม”
- รายงานเนื้อหาหลักเป็นอังกฤษตามแผนเดิม โดยคงชื่อ/ข้อมูลทางการตามต้นฉบับ ใช้ editable source และ PDF พร้อมตรวจทุกหน้า รวมสารบัญ เลขหน้า ตาราง ภาพ และแหล่งอ้างอิง
- โปสเตอร์ clean minimal มีพื้นที่ว่างและลำดับสายตาชัด ดูเป็นมืออาชีพ น่าเชื่อถือ และเป็นธรรมชาติ ใช้ภาพระบบ/เส้นทางข้อมูลและกราฟผลจริงอย่างพอดี มีชื่อโครงงาน สมาชิกและอาจารย์ตามต้นฉบับ อธิบาย use case วิธีทำ ผลทดลอง ต้นทุน และข้อจำกัด ไม่ใช้คำโฆษณาหรือเปอร์เซ็นต์ที่ยังไม่วัด
- เตรียมโปสเตอร์ PDF สำหรับพิมพ์ พร้อม PNG preview และ editable source ตั้งต้น A1 แนวตั้งเมื่อยังไม่มีข้อกำหนดขนาดจากคณะ เปลี่ยนได้ก่อน final export หากมีข้อกำหนดจริง ภาพประกอบที่สร้างด้วย AI ใช้ได้ตามความเหมาะสม แต่ข้อความ ตัวเลข ชื่อ โลโก้ และกราฟต้องควบคุมในไฟล์แก้ไขได้และตรวจความถูกต้อง
- ผลรายงาน โปสเตอร์ สไลด์ และสคริปต์ไทยต้องใช้ result manifest/claim-evidence matrix รุ่นเดียวกัน เก็บ final outputs ภายใต้ `TestFile/project_closure_2026-10-09/` และไม่เขียนทับงานสไลด์ของแชทอื่น

รายละเอียดการจัดหน้าและข้อมูลตั้งต้น: `TestFile/project_closure_2026-10-09/REPORT_POSTER_BRIEF.md` งานนี้รอผล final analysis แต่เริ่มตรวจต้นแบบและเตรียม structure ได้ทันที

## 13. ผลส่งงานฉบับตรวจครบ 13 ตุลาคม 2026

ประเมินคำตอบชุดเดิมครบ 1,060/1,060 รายการตามคำสั่งล่าสุด ไม่มีงานตรวจค้างและไม่มี Gemini API calls ใหม่ เก็บคำตอบแรกและผลเก่าทั้งหมด ใช้ completion overlays 348 รายการ และบันทึกการแก้ผลตัดสิน 34 รายการแยกจากต้นฉบับ ตรวจ hash หลักฐานเดิม 2,124 ไฟล์และโค้ดชุดทดลอง 239 ไฟล์ผ่าน

ผลหลัก S0/S1: คำตอบครบตามเกณฑ์ 79/498 และ 60/498; ความสัมพันธ์ตัวเลข 119/356 และ 106/356; controls เหมาะสม 24/32 และ 28/32 ข้ออ้างอิงบกพร่อง 3 ข้อมี paired sensitivity แยก ไม่เปลี่ยนตัวหารหลัก ไม่อ้างว่าเป้าหมายคุณภาพเกิน 80% สำเร็จ และไม่มีการยืนยันโดยมนุษย์

รายงานอังกฤษ 24 หน้า โปสเตอร์ A1 และทุกหน้า preview ผ่าน render/visual QA แล้ว ใช้ manifest เดียวกัน รักษาชื่อและข้อมูลต้นฉบับ ชุดทดสอบโค้ดที่เกี่ยวข้องผ่าน 96 ข้อ ส่ง editable sources, PDFs และ PNGs ใน [แพ็กเกจส่งงาน](../TestFile/published_2026-10-13/README.md) งานตามรอบคงปิดไว้ ไม่เริ่มปรับระบบหรือทดลองใหม่อัตโนมัติ
